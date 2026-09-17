"""Extraction du profil candidat depuis le CV (PDF) par Claude, en JSON validé.

Lancement (depuis la racine du projet) :
    .venv\\Scripts\\python.exe -m src.profil
"""

import hashlib
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pypdf import PdfReader

from src.llm_client import generer_json

DOSSIER_DATA = Path(__file__).resolve().parent.parent / "data"
CHEMIN_CV = DOSSIER_DATA / "cv.pdf"
CHEMIN_PROFIL = DOSSIER_DATA / "profil.json"


class Experience(BaseModel):
    poste: str
    entreprise: str
    periode: str
    realisations: list[str] = Field(description="Réalisations concrètes, avec les chiffres du CV")


class Projet(BaseModel):
    nom: str
    contexte: str = Field(description="Ex. : projet universitaire en équipe, projet personnel")
    technologies: list[str]
    resultat: str = Field(description="Résultat mesurable si le CV en donne un")


class Profil(BaseModel):
    titre_recherche: str = Field(description="Poste recherché, ex. : Développeur full stack (alternance)")
    formation: str
    niveau_diplome: int = Field(ge=3, le=7, description="Niveau européen visé : 5 = Bac+2, 6 = Bac+3, 7 = Bac+5")
    rythme_alternance: str | None
    competences: dict[str, list[str]] = Field(description="Compétences techniques regroupées par catégorie")
    experiences: list[Experience]
    projets: list[Projet]
    langues: list[str]
    points_forts: list[str] = Field(description="Arguments différenciants à mettre en avant dans une candidature")


SYSTEME = """Tu extrais le profil d'un candidat à partir du texte brut de son CV.
Le texte vient d'un PDF en deux colonnes : l'ordre des lignes peut être mélangé,
rattache chaque puce à la bonne expérience ou au bon projet.
N'invente rien : n'utilise que ce qui figure dans le CV.
N'inclus aucune donnée de contact (nom, email, téléphone, liens)."""


def lire_cv(chemin: Path = CHEMIN_CV) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(chemin).pages)


def empreinte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:16]


def charger_profil(chemin_cv: Path = CHEMIN_CV) -> tuple[Profil, str]:
    """Renvoie (profil, empreinte du CV). N'appelle Claude que si le CV a changé depuis la dernière extraction."""
    texte = lire_cv(chemin_cv)
    hash_cv = empreinte(texte)

    if CHEMIN_PROFIL.exists():
        sauvegarde = json.loads(CHEMIN_PROFIL.read_text(encoding="utf-8"))
        if sauvegarde["hash_cv"] == hash_cv:
            return Profil.model_validate(sauvegarde["profil"]), hash_cv

    profil = generer_json(f"Voici le texte du CV :\n\n{texte}", SYSTEME, Profil)
    sauvegarde = {"hash_cv": hash_cv, "profil": profil.model_dump()}
    CHEMIN_PROFIL.write_text(json.dumps(sauvegarde, ensure_ascii=False, indent=2), encoding="utf-8")
    return profil, hash_cv


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    profil, hash_cv = charger_profil()
    print(f"Profil (CV {hash_cv}) :")
    print(profil.model_dump_json(indent=2))
