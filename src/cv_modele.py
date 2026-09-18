"""Modèle HTML du CV : déballage de l'export Claude Design, rendu PDF et contrôle de mise en page avec Edge.

Le CV est une page HTML à mise en page fixe (A4 de 794 x 1123 px, blocs positionnés en absolu).
On ne modifie jamais le HTML ni le CSS : seulement des textes (voir cv_adapte.py).
"""

import base64
import gzip
import hashlib
import html as html_module
import json
import re
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from src.profil import DOSSIER_DATA

CHEMIN_MODELE = DOSSIER_DATA / "cv_modele.html"
LARGEUR_PAGE, HAUTEUR_PAGE = 794, 1123
EMPLACEMENTS_EDGE = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


class ErreurModele(RuntimeError):
    pass


# ---------------------------------------------------------------- Déballage de l'export Claude Design

def _bloc(html: str, type_bloc: str) -> str | None:
    trouve = re.search(rf'<script type="__bundler/{type_bloc}">(.*?)</script>', html, re.S)
    return trouve.group(1) if trouve else None


def deballer(export_html: str) -> str:
    """Transforme l'export « empaqueté » (données compressées + JavaScript) en page HTML autonome et statique."""
    manifeste_brut, modele_brut = _bloc(export_html, "manifest"), _bloc(export_html, "template")
    if manifeste_brut is None or modele_brut is None:
        raise ErreurModele("Ce fichier n'est pas un export Claude Design (manifeste ou modèle introuvable).")
    manifeste, page = json.loads(manifeste_brut), json.loads(modele_brut)

    for uuid, ressource in manifeste.items():
        if uuid not in page:
            continue
        donnees = ressource["data"]
        if ressource.get("compressed"):
            donnees = base64.b64encode(gzip.decompress(base64.b64decode(donnees))).decode()
        # Polices et photo intégrées en data: URI : la page ne dépend plus d'aucun fichier ni réseau
        page = page.replace(uuid, f"data:{ressource['mime']};base64,{donnees}")

    # Le moteur de Claude Design est conservé : dans le format récent, la page reste invisible
    # tant que l'élément <doc-page> n'est pas défini par ce script.
    page = re.sub(r'<script type="text/x-dc"[^>]*></script>', "", page)
    entete = re.search(r"<helmet>(.*?)</helmet>", page, re.S)
    page = re.sub(r"<helmet>.*?</helmet>", "", page, flags=re.S)
    page = page.replace("<x-dc>", "").replace("</x-dc>", "")
    impression = f"<style>@page {{ size: {LARGEUR_PAGE}px {HAUTEUR_PAGE}px; margin: 0; }} body {{ background: #FDFDFB; }}</style>"
    return page.replace("</head>", (entete.group(1) if entete else "") + impression + "</head>", 1)


def importer_export(chemin_export: Path, destination: Path = CHEMIN_MODELE) -> Path:
    destination.write_text(deballer(chemin_export.read_text(encoding="utf-8")), encoding="utf-8")
    return destination


# ---------------------------------------------------------------- Rendu avec Edge (même moteur que Chrome / Opera)

def chemin_edge() -> Path:
    for chemin in EMPLACEMENTS_EDGE:
        if chemin.exists():
            return chemin
    raise ErreurModele("Microsoft Edge est introuvable : il sert à produire le PDF.")


def _edge(arguments: list[str], dossier: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(chemin_edge()), "--headless", "--disable-gpu", "--no-first-run", "--disable-extensions",
         f"--user-data-dir={dossier / 'profil-edge'}", *arguments],  # profil jetable : n'utilise pas ton navigateur
        capture_output=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW,
    )


def definir_metadonnees(chemin_pdf: Path, titre: str, auteur: str) -> None:
    """Titre et auteur du PDF : c'est le titre qui s'affiche dans l'onglet du lecteur PDF du recruteur.

    Sans ça, Edge inscrit le nom du fichier HTML temporaire (« cv.html ») et un créateur « HeadlessChrome ».
    """
    lecteur = PdfReader(chemin_pdf)
    redacteur = PdfWriter(clone_from=lecteur)
    redacteur.metadata = None  # on repart de zéro : ni nom de fichier temporaire ni navigateur automatisé
    redacteur.add_metadata({"/Title": titre, "/Author": auteur, "/Subject": "Curriculum vitae"})
    with open(chemin_pdf, "wb") as sortie:
        redacteur.write(sortie)


def imprimer_pdf(html: str, destination: Path, titre: str | None = None, auteur: str | None = None) -> Path:
    with tempfile.TemporaryDirectory() as dossier:
        source = Path(dossier) / "cv.html"
        source.write_text(html, encoding="utf-8")
        resultat = _edge(["--no-pdf-header-footer", "--virtual-time-budget=5000",
                          f"--print-to-pdf={destination}", source.as_uri()], Path(dossier))
    if not destination.exists():
        raise ErreurModele(f"Edge n'a pas produit le PDF : {resultat.stderr.decode(errors='replace')[:300]}")
    if titre:
        definir_metadonnees(destination, titre, auteur or "")
    return destination


# Mesure dans le navigateur, une fois les polices chargées. Pour chaque segment (data-cv-id) : sort-il de la page,
# de son bloc à largeur ou hauteur fixe ? Et quels blocs de premier niveau (positionnés en absolu) se chevauchent ?
# Le résultat est écrit dans un attribut du <body>, lu grâce à --dump-dom.
SCRIPT_CONTROLE = """
<script>
document.fonts.ready.then(function () {
  var racine = document.querySelector('section.page') || document.body.firstElementChild;
  var page = racine.getBoundingClientRect();
  var blocs = Array.prototype.filter.call(racine.children, function (b) { return getComputedStyle(b).position === 'absolute'; });
  var segments = [];
  document.querySelectorAll('[data-cv-id]').forEach(function (el) {
    var r = el.getBoundingClientRect(), bloc = el.parentElement;
    while (bloc && bloc !== racine && getComputedStyle(bloc).position !== 'absolute') bloc = bloc.parentElement;
    var cadre = bloc.getBoundingClientRect(), probleme = null;
    if (r.right > page.right + 0.5 || r.bottom > page.bottom + 0.5) probleme = 'sort de la page';
    else if (bloc.style.width && r.right > cadre.right + 0.5) probleme = 'dépasse à droite';
    else if (bloc.style.height && bloc.scrollHeight > bloc.clientHeight + 1) probleme = 'dépasse en bas';
    segments.push({ id: el.getAttribute('data-cv-id'), probleme: probleme, bloc: blocs.indexOf(bloc) });
  });
  var chevauchements = [];
  for (var i = 0; i < blocs.length; i++) for (var j = i + 1; j < blocs.length; j++) {
    var a = blocs[i].getBoundingClientRect(), b = blocs[j].getBoundingClientRect();
    if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1)
      chevauchements.push(i + '-' + j);
  }
  document.body.setAttribute('data-controle', JSON.stringify({ segments: segments, chevauchements: chevauchements }));
});
</script>
"""


def _mesurer(html_marque: str) -> dict:
    with tempfile.TemporaryDirectory() as dossier:
        source = Path(dossier) / "controle.html"
        source.write_text(html_marque.replace("</body>", SCRIPT_CONTROLE + "</body>"), encoding="utf-8")
        resultat = _edge(["--virtual-time-budget=5000", "--dump-dom", source.as_uri()], Path(dossier))
    trouve = re.search(r'data-controle="([^"]*)"', resultat.stdout.decode("utf-8", errors="replace"))
    if not trouve:
        raise ErreurModele("Contrôle de mise en page impossible (Edge n'a pas renvoyé de mesure).")
    return json.loads(html_module.unescape(trouve.group(1)))


_MESURES_REFERENCE: dict[str, dict] = {}


def controler_mise_en_page(html_marque: str, html_reference: str) -> dict[str, str]:
    """{id de segment: problème} pour les segments qui débordent ou dont le bloc chevauche un autre bloc,
    par comparaison avec le CV de référence (dont les chevauchements éventuels sont voulus par le design)."""
    cle = hashlib.sha256(html_reference.encode("utf-8")).hexdigest()
    if cle not in _MESURES_REFERENCE:  # la référence ne change pas d'un essai à l'autre : une seule mesure
        _MESURES_REFERENCE[cle] = _mesurer(html_reference)
    mesure, reference = _mesurer(html_marque), _MESURES_REFERENCE[cle]
    problemes = {s["id"]: s["probleme"] for s in mesure["segments"] if s["probleme"]}
    for paire in set(mesure["chevauchements"]) - set(reference["chevauchements"]):
        blocs = {int(indice) for indice in paire.split("-")}
        for segment in mesure["segments"]:
            if segment["bloc"] in blocs:
                problemes.setdefault(segment["id"], "chevauche un autre bloc")
    return problemes
