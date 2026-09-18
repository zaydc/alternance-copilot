"""CV adapté à une offre : Claude réécrit uniquement des textes du modèle, le programme vérifie tout.

Étapes : réécriture par Claude → garde-fous (zones protégées, chiffres, compétences non confirmées)
→ contrôle de mise en page dans Edge → raccourcissement des textes qui débordent → PDF.
"""

import json
import re
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field
from pypdf import PdfReader

from src import competences, cv_modele, cv_segments, stockage
from src.assistant import contexte_cible
from src.llm_client import generer_json
from src.profil import DOSSIER_DATA, charger_profil

DOSSIER_CV = DOSSIER_DATA / "cv_adaptes"
TENTATIVES_RACCOURCISSEMENT = 2


class TexteModifie(BaseModel):
    id: str
    texte: str = Field(description="Nouveau texte ; le gras s'écrit **ainsi**")
    pourquoi: str = Field(description="Raison du changement en une phrase")


class ListeModifiee(BaseModel):
    id: str
    elements: list[str]
    pourquoi: str


class Adaptation(BaseModel):
    textes: list[TexteModifie] = Field(description="Uniquement les segments texte modifiés")
    listes: list[ListeModifiee] = Field(description="Uniquement les listes modifiées")
    mots_cles: list[str] = Field(description="Mots-clés de l'offre repris dans le CV")
    conseil: str = Field(description="Un conseil en 1 à 2 phrases sur ce que le CV ne peut pas couvrir pour cette offre")


class Raccourcissement(BaseModel):
    textes: list[TexteModifie]


SYSTEME = """Tu adaptes le CV d'un étudiant à une offre d'alternance. Le design est figé : tu ne modifies que des textes,
identifiés par leur id, et chaque texte doit tenir dans la même place.

Règles absolues :
- Vérité : reformule, mets en avant, réordonne. N'invente JAMAIS une compétence, un outil, une responsabilité,
  un chiffre ou un résultat. Les seules compétences ajoutables sont celles du profil ou de la liste « confirmées ».
- Compétences interdites : ne mentionne jamais celles de la liste « non confirmées », même indirectement.
- Longueur : chaque nouveau texte fait au plus la longueur d'origine (± 10 %).
- Puces : garde la forme « **début en gras** suite du texte ».
- Intitulé du poste (segment en capitales de l'en-tête) : en capitales, adapté au poste visé, pas plus long que +10 caractères.
- Accroche : oriente-la vers le poste et l'entreprise ciblés, à la première personne comme l'original.
- Listes de compétences : place les plus pertinentes pour l'offre en premier. Tu peux remplacer l'élément le moins utile
  par une compétence confirmée pertinente de la même catégorie, en gardant le même nombre d'éléments.
- Reprends le vocabulaire de l'offre uniquement pour décrire ce que le candidat a réellement fait.
- Candidature spontanée (fiche d'entreprise, sans offre) : appuie-toi sur l'activité réelle de l'entreprise et son
  secteur ; n'invente ni intitulé de poste ni mission, et reste sur le métier visé par le candidat.
- Ne renvoie que ce que tu modifies. Français soigné, sans faute."""

SYSTEME_RACCOURCIR = """Des textes d'un CV à mise en page fixe débordent. Raccourcis chacun jusqu'à la longueur cible
en gardant le sens, la vérité des faits, les chiffres et la forme « **début en gras** suite »."""


@dataclass
class Resultat:
    chemin_pdf: str
    changements: list[dict] = field(default_factory=list)  # section, avant, apres, pourquoi
    alertes: list[str] = field(default_factory=list)
    mots_cles: list[str] = field(default_factory=list)
    conseil: str = ""


def _nombres(texte: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", texte.replace(" ", " ")))


def _mentionne(texte: str, nom: str) -> bool:
    # « Java » ne doit pas correspondre à « JavaScript »
    return re.search(rf"(?<![\w+#.]){re.escape(nom)}(?![\w+#])", texte, re.IGNORECASE) is not None


def _valider(adaptation: Adaptation, segments: dict[str, cv_segments.Segment], autorisees: set[str],
             interdites: list[str], nombres_connus: set[str]) -> tuple[dict, list[str]]:
    """Garde les modifications conformes aux règles ; les autres sont écartées avec une alerte."""
    retenues, alertes = {}, []
    for modif in adaptation.textes:
        segment = segments.get(modif.id)
        texte = modif.texte.strip()
        if segment is None or segment.type != "texte" or not segment.modifiable:
            alertes.append(f"Zone protégée ou inconnue ignorée ({modif.id}).")
        elif texte.count("**") % 2:
            alertes.append(f"Mise en forme invalide, texte d'origine conservé : « {segment.texte[:50]}… »")
        elif nouveaux := _nombres(texte) - nombres_connus:
            alertes.append(f"Chiffre absent de ton parcours ({', '.join(sorted(nouveaux))}), modification refusée : « {texte[:60]}… »")
        elif interdite := next((n for n in interdites if _mentionne(texte, n) and not _mentionne(segment.texte, n)), None):
            alertes.append(f"Compétence non confirmée « {interdite} », modification refusée : « {texte[:60]}… »")
        elif texte != segment.texte:
            retenues[modif.id] = (texte, modif.pourquoi)

    for modif in adaptation.listes:
        segment = segments.get(modif.id)
        if segment is None or segment.type != "liste" or not segment.modifiable:
            alertes.append(f"Zone protégée ou inconnue ignorée ({modif.id}).")
            continue
        existants = {competences.cle(e) for e in segment.elements}
        elements = []
        for element in modif.elements:
            if competences.cle(element) in existants or competences.cle(element) in autorisees:
                elements.append(element.strip())
            else:
                alertes.append(f"« {element} » retiré de la liste : absent de ton profil et non confirmé.")
        if elements and elements != segment.elements:
            retenues[modif.id] = (elements, modif.pourquoi)
    return retenues, alertes


def _appliquer(html_modele: str, retenues: dict) -> tuple:
    document, segments = cv_segments.decouper(html_modele)
    for identifiant, (valeur, _) in retenues.items():
        if isinstance(valeur, list):
            cv_segments.remplacer_liste(document, identifiant, valeur)
        else:
            cv_segments.remplacer_texte(document, identifiant, valeur)
    return document, segments


def adapter(offre_id: str, progression: Callable[[str], None] = print) -> Resultat:
    if not cv_modele.CHEMIN_MODELE.exists():
        raise cv_modele.ErreurModele("Aucun modèle de CV : importe l'export HTML de ton CV (page Profil).")
    html_modele = cv_modele.CHEMIN_MODELE.read_text(encoding="utf-8")
    document_reference, liste_segments = cv_segments.decouper(html_modele)
    reference = str(document_reference)
    segments = {s.id: s for s in liste_segments}

    profil, _ = charger_profil()
    confirmees = competences.competences_confirmees()
    analyse = competences.analyser_offre(offre_id)
    noms_confirmes = {competences.cle(c["nom"]) for c in confirmees}
    interdites = [c["nom"] for c in analyse if competences.cle(c["nom"]) not in noms_confirmes]
    autorisees = noms_confirmes | {competences.cle(x) for liste in profil.competences.values() for x in liste} \
        | {competences.cle(t) for projet in profil.projets for t in projet.technologies}
    nombres_connus = _nombres(json.dumps([s.texte or s.elements for s in liste_segments], ensure_ascii=False)) \
        | _nombres(profil.model_dump_json()) | _nombres(" ".join(c["resume_cv"] or "" for c in confirmees))

    progression("✍️ Claude réécrit les textes du CV pour cette offre…")
    zones = [{"id": s.id, "section": s.section, "type": s.type, **({"texte": s.texte, "longueur": len(s.texte)} if s.type == "texte"
              else {"elements": s.elements})} for s in liste_segments if s.modifiable]
    prompt = (
        f"## Cible\n{contexte_cible(offre_id)}\n\n## Profil du candidat\n{profil.model_dump_json(indent=1)}\n\n"
        f"## Compétences confirmées (hors CV)\n"
        + ("\n".join(f"- {c['nom']} : {c['resume_cv']}" for c in confirmees) or "aucune")
        + f"\n\n## Compétences NON confirmées (interdites)\n{', '.join(interdites) or 'aucune'}\n\n"
        f"## Zones modifiables du CV\n{json.dumps(zones, ensure_ascii=False, indent=1)}"
    )
    adaptation = generer_json(prompt, SYSTEME, Adaptation)
    retenues, alertes = _valider(adaptation, segments, autorisees, interdites, nombres_connus)

    for tentative in range(TENTATIVES_RACCOURCISSEMENT + 1):
        progression("📐 Contrôle de la mise en page…")
        document, _ = _appliquer(html_modele, retenues)
        problemes = {i: p for i, p in cv_modele.controler_mise_en_page(str(document), reference).items() if i in retenues}
        if not problemes:
            break
        textes_a_raccourcir = {i: retenues[i][0] for i in problemes if isinstance(retenues[i][0], str)}
        for identifiant in set(problemes) - set(textes_a_raccourcir):  # liste qui déborde : on garde l'originale
            alertes.append(f"Liste « {segments[identifiant].section.title()} » : modification annulée (manque de place).")
            del retenues[identifiant]
        if not textes_a_raccourcir:
            continue
        if tentative == TENTATIVES_RACCOURCISSEMENT:
            for identifiant in textes_a_raccourcir:
                alertes.append(f"Texte trop long malgré les essais, original conservé : « {segments[identifiant].texte[:50]}… »")
                del retenues[identifiant]
            document, _ = _appliquer(html_modele, retenues)
            break
        progression(f"✂️ {len(textes_a_raccourcir)} texte(s) débordent : raccourcissement (essai {tentative + 1})…")
        demande = [{"id": i, "texte": t, "longueur_actuelle": len(t), "longueur_cible": int(len(t) * 0.8),
                    "probleme": problemes[i]} for i, t in textes_a_raccourcir.items()]
        raccourcis = generer_json(json.dumps(demande, ensure_ascii=False, indent=1), SYSTEME_RACCOURCIR,
                                  Raccourcissement, effort="low")
        for modif in raccourcis.textes:
            if modif.id in textes_a_raccourcir and not (_nombres(modif.texte) - nombres_connus) and modif.texte.count("**") % 2 == 0:
                retenues[modif.id] = (modif.texte.strip(), retenues[modif.id][1])

    progression("🖨️ Création du PDF…")
    DOSSIER_CV.mkdir(parents=True, exist_ok=True)
    chemin_pdf = DOSSIER_CV / f"{datetime.now():%Y-%m-%d_%H%M%S}_{offre_id}.pdf"
    cv_modele.imprimer_pdf(cv_segments.sans_marqueurs(document), chemin_pdf)
    if len(PdfReader(chemin_pdf).pages) != 1:
        alertes.append("⚠️ Le PDF fait plus d'une page : vérifie l'aperçu.")

    changements = []
    for identifiant, (valeur, pourquoi) in retenues.items():
        segment = segments[identifiant]
        avant = segment.texte if segment.type == "texte" else " · ".join(segment.elements)
        apres = valeur if isinstance(valeur, str) else " · ".join(valeur)
        changements.append({"section": segment.section.title(), "avant": avant, "apres": apres, "pourquoi": pourquoi})

    resultat = Resultat(str(chemin_pdf), changements, alertes, adaptation.mots_cles, adaptation.conseil)
    with closing(stockage.connecter()) as c:
        stockage.inserer(c, "cv_adaptes", {"offre_id": offre_id, "chemin_pdf": resultat.chemin_pdf, "changements": changements,
                                           "alertes": alertes, "conseil": adaptation.conseil, "date": stockage.maintenant()})
    return resultat
