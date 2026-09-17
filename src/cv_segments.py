"""Découpage du CV HTML en segments de texte, et réinjection de nouveaux textes sans toucher au design.

- Segment « texte » : un bloc de texte (puce, paragraphe, titre). Le gras est représenté par **...**.
- Segment « liste » : un groupe d'étiquettes (compétences, chiffres clés), représenté par une liste de textes.
Chaque segment reçoit un attribut data-cv-id, utilisé pour la réinjection et le contrôle de mise en page.
"""

import copy
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

BALISES_EN_LIGNE = {"span", "br", "b", "strong", "em", "i", "sup", "sub", "a"}
SECTIONS_PROTEGEES = {"FORMATION", "LANGUES", "RÉFÉRENCE"}
MOTIFS_PROTEGES = [
    re.compile(r"@|https?://|www\.|\.app\b|\.fr\b|\bin/"),  # coordonnées
    re.compile(r"(\d[\s.]?){8,}"),  # téléphone
    re.compile(r"\b(19|20)\d{2}\b"),  # dates
]


@dataclass
class Segment:
    id: str
    type: str  # texte, liste
    section: str
    texte: str = ""  # type texte, avec **gras**
    elements: list[str] = field(default_factory=list)  # type liste
    modifiable: bool = True
    raison: str = ""  # pourquoi il est protégé


def _style(element: Tag) -> str:
    # Espaces retirés autour de « : » et « ; » seulement : « font:600 9.6px » ne doit pas devenir « 6009.6px »
    return re.sub(r"\s*([:;])\s*", r"\1", element.get("style") or "").lower()


def _est_mise_en_page(element: Tag) -> bool:
    style = _style(element)
    return "display:flex" in style or "position:absolute" in style or "display:grid" in style


def _texte_direct(element: Tag) -> bool:
    return any(isinstance(e, NavigableString) and re.search(r"\w", e) for e in element.children)


def _enfants(element: Tag) -> list[Tag]:
    return [e for e in element.children if isinstance(e, Tag)]


def _est_bloc_texte(element: Tag) -> bool:
    if not re.search(r"\w", element.get_text()):
        return False
    for enfant in _enfants(element):
        if enfant.name not in BALISES_EN_LIGNE or _est_mise_en_page(enfant) or _enfants(enfant) and enfant.name != "span":
            return False
    # Une rangée flex sans texte direct (ex. « + » puis la puce) est une mise en page, pas un texte
    return not (_est_mise_en_page(element) and not _texte_direct(element))


def _est_liste(element: Tag) -> bool:
    enfants = _enfants(element)
    return (len(enfants) >= 2 and not _texte_direct(element)
            and all(e.name == "span" and not _enfants(e) and re.search(r"\w", e.get_text()) for e in enfants))


def _en_balisage(element: Tag) -> str:
    """HTML du segment → texte avec **gras** (les <br> manuels deviennent des espaces)."""
    morceaux = []
    for enfant in element.children:
        if isinstance(enfant, NavigableString):
            morceaux.append(str(enfant))
        elif enfant.name == "br":
            # « non-<br>technicien » : pas d'espace après un trait d'union coupé en fin de ligne
            morceaux.append("" if "".join(morceaux).endswith("-") else " ")
        elif re.search(r"font-weight:(600|700|bold)", _style(enfant)):
            morceaux.append(f"**{_en_balisage(enfant).strip()}**")
        else:
            morceaux.append(_en_balisage(enfant))
    return re.sub(r"\s+", " ", "".join(morceaux)).strip()


def _en_capitales(texte: str) -> bool:
    lettres = re.sub(r"[^A-Za-zÀ-ÿ]", "", texte)
    return bool(lettres) and lettres == lettres.upper()


def _est_titre_section(texte: str) -> bool:
    # « AVRIL — JUIN 2026 » ou « PYTHON · MONGODB » sont en capitales mais ne sont pas des titres de section
    return _en_capitales(texte) and len(texte) <= 40 and not re.search(r"[\d·]", texte)


def _taille_police(element: Tag) -> float:
    while isinstance(element, Tag):
        trouve = re.search(r"font(?:-size)?:[^;]*?(\d+(?:\.\d+)?)px", _style(element))
        if trouve:
            return float(trouve.group(1))
        element = element.parent
    return 0.0


def decouper(html: str) -> tuple[BeautifulSoup, list[Segment]]:
    """Analyse le CV : renvoie le document (avec data-cv-id) et ses segments, dans l'ordre de lecture."""
    document = BeautifulSoup(html, "html.parser")
    page = document.body.find("div")
    segments: list[Segment] = []
    etat = {"section": "EN-TÊTE", "titre_vu": False}

    def ajouter(element: Tag, segment: Segment) -> None:
        element["data-cv-id"] = segment.id
        segments.append(segment)

    def parcourir(element: Tag) -> None:
        for enfant in _enfants(element):
            identifiant = f"s{len(segments) + 1}"
            if _est_liste(enfant):
                ajouter(enfant, Segment(identifiant, "liste", etat["section"],
                                        elements=[e.get_text(strip=True) for e in _enfants(enfant)]))
            elif _est_bloc_texte(enfant):
                texte = _en_balisage(enfant)
                segment = Segment(identifiant, "texte", etat["section"], texte=texte)
                if _en_capitales(texte) and not etat["titre_vu"]:
                    etat["titre_vu"] = True  # le premier texte en capitales est l'intitulé du poste : adaptable
                    segment.raison = "intitulé du poste"
                elif _est_titre_section(texte):
                    etat["section"] = texte.upper()
                    segment.modifiable, segment.raison = False, "titre de section"
                ajouter(enfant, segment)
            else:
                parcourir(enfant)

    parcourir(page)

    for segment in segments:
        texte = segment.texte or " ".join(segment.elements)
        if not segment.modifiable:
            continue
        element = document.find(attrs={"data-cv-id": segment.id})
        if segment.raison == "intitulé du poste":
            continue
        if element.name == "h1":
            segment.modifiable, segment.raison = False, "nom"
        elif any(motif.search(texte) for motif in MOTIFS_PROTEGES):
            segment.modifiable, segment.raison = False, "coordonnées ou date"
        elif segment.section == "EN-TÊTE" and len(texte.split()) < 12:
            segment.modifiable, segment.raison = False, "informations pratiques"
        elif segment.type == "texte" and _en_capitales(texte):
            segment.modifiable, segment.raison = False, "étiquettes (technologies utilisées)"
        elif segment.section in SECTIONS_PROTEGEES:
            segment.modifiable, segment.raison = False, f"section {segment.section.lower()}"
        elif segment.type == "texte" and _taille_police(element) >= 13:
            segment.modifiable, segment.raison = False, "intitulé (poste, projet, chiffre clé)"
    return document, segments


# ---------------------------------------------------------------- Réinjection

def _style_gras(element: Tag) -> str | None:
    for span in element.find_all("span"):
        if re.search(r"font-weight:(600|700|bold)", _style(span)):
            return span.get("style")
    return None


def _style_exposant(element: Tag) -> str | None:
    for span in element.find_all("span"):
        if "vertical-align" in _style(span):
            return span.get("style")
    return None


def remplacer_texte(document: BeautifulSoup, identifiant: str, texte: str) -> None:
    element = document.find(attrs={"data-cv-id": identifiant})
    style_gras, style_exposant = _style_gras(element), _style_exposant(element)
    element.clear()
    for i, morceau in enumerate(re.split(r"\*\*", texte)):
        if not morceau:
            continue
        if i % 2 == 1 and style_gras:
            gras = document.new_tag("span", style=style_gras)
            gras.string = morceau
            element.append(gras)
            continue
        # « 3e année » : on restaure l'exposant du modèle s'il en avait un
        position = 0
        for trouve in re.finditer(r"(?<=\d)(e|er|ère)\b", morceau) if style_exposant else []:
            element.append(NavigableString(morceau[position:trouve.start()]))
            exposant = document.new_tag("span", style=style_exposant)
            exposant.string = trouve.group(0)
            element.append(exposant)
            position = trouve.end()
        element.append(NavigableString(morceau[position:]))


def remplacer_liste(document: BeautifulSoup, identifiant: str, elements: list[str]) -> None:
    conteneur = document.find(attrs={"data-cv-id": identifiant})
    modele = copy.copy(_enfants(conteneur)[0])  # même style d'étiquette pour chaque élément
    separateur = next((str(e) for e in conteneur.children if isinstance(e, NavigableString)), "\n")
    conteneur.clear()
    for texte in elements:
        etiquette = copy.copy(modele)
        etiquette.string = texte
        conteneur.append(NavigableString(separateur))
        conteneur.append(etiquette)
    conteneur.append(NavigableString(separateur))


def sans_marqueurs(document: BeautifulSoup) -> str:
    propre = copy.copy(document)
    for element in propre.find_all(attrs={"data-cv-id": True}):
        del element["data-cv-id"]
    return str(propre)
