"""Compétences demandées par une offre mais absentes du CV : on demande à l'utilisateur s'il les a vraiment.

Un CV ne dit pas tout. Plutôt que d'inventer (ou d'ignorer) une compétence, on la fait confirmer,
éventuellement avec une preuve (description de projet, lien GitHub) que Claude examine.
"""

import re
import unicodedata
from contextlib import closing
from typing import Literal

from pydantic import BaseModel, Field

from src import stockage
from src.assistant import detail_offre
from src.llm_client import OUTILS_WEB, generer_json
from src.profil import charger_profil

TAILLE_MAX_FICHIER = 15_000  # caractères d'un fichier de preuve transmis à Claude


class CompetenceRequise(BaseModel):
    nom: str = Field(description="Nom court et usuel de la compétence : « Java », « Spring Boot », « Kubernetes »")
    extrait: str = Field(description="Courte citation de l'offre qui la mentionne")
    importance: Literal["indispensable", "appréciée"]


class AnalyseOffre(BaseModel):
    competences_absentes: list[CompetenceRequise]


class VerdictPreuve(BaseModel):
    convaincant: bool = Field(description="La preuve montre-t-elle une utilisation réelle de la compétence ?")
    resume_cv: str = Field(max_length=90, description="Formulation courte et factuelle pour un CV, ex. « Projet perso : API REST en Java / Spring Boot »")
    remarque: str = Field(description="Explication en 1 à 2 phrases, en tutoyant")


SYSTEME_ANALYSE = """Tu compares une offre d'alternance au profil d'un candidat.
Liste les compétences TECHNIQUES (langages, frameworks, outils, méthodes, domaines techniques) que l'offre demande
ou valorise explicitement et qui n'apparaissent pas dans le profil, même sous un autre nom
(ex. « JS » = JavaScript ; « API REST » est couvert par FastAPI ou Node.js).
Ignore les savoir-être, les diplômes et les langues. Ne liste pas ce que le profil couvre déjà.
Au maximum 8 compétences, les plus importantes d'abord."""

SYSTEME_PREUVE = """Tu vérifies qu'un candidat a réellement utilisé une compétence technique, à partir de ce qu'il fournit :
une description de projet, éventuellement un lien (consulte-le s'il est fourni) ou le contenu d'un fichier.
Sois juste : une description précise et crédible d'un vrai projet suffit, même sans lien.
Ne juge pas le niveau, seulement la réalité de l'usage. Rédige resume_cv de façon factuelle, sans exagérer."""


def cle(nom: str) -> str:
    """« Spring Boot » et « spring-boot » donnent la même clé."""
    sans_accents = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9+#]", "", sans_accents.lower())


def declarations() -> dict[str, dict]:
    with closing(stockage.connecter()) as c:
        return {ligne["cle"]: dict(ligne) for ligne in stockage.competences_declarees(c)}


def competences_confirmees() -> list[dict]:
    return [d for d in declarations().values() if d["statut"] in ("confirmée", "déclarée")]


def analyser_offre(offre_id: str) -> list[dict]:
    """Compétences absentes du profil demandées par l'offre (analyse mise en cache), avec la réponse déjà donnée."""
    profil, hash_cv = charger_profil()
    with closing(stockage.connecter()) as c:
        analyse = stockage.analyse_offre(c, offre_id, hash_cv)
    if analyse is None:
        confirmees = [d["nom"] for d in competences_confirmees()]
        prompt = (f"## Profil du candidat\n{profil.model_dump_json(indent=1)}\n"
                  f"Compétences confirmées en plus du CV : {', '.join(confirmees) or 'aucune'}\n\n"
                  f"## Offre\n{detail_offre(offre_id)}")
        analyse = [c.model_dump() for c in generer_json(prompt, SYSTEME_ANALYSE, AnalyseOffre).competences_absentes]
        with closing(stockage.connecter()) as c:
            stockage.enregistrer_analyse(c, offre_id, hash_cv, analyse)
    deja = declarations()
    return [{**competence, "declaration": deja.get(cle(competence["nom"]))} for competence in analyse]


def declarer_absente(nom: str) -> None:
    with closing(stockage.connecter()) as c:
        stockage.declarer_competence(c, {"cle": cle(nom), "nom": nom, "statut": "absente"})


def confirmer(nom: str, description: str, lien: str = "", contenu_fichier: str = "") -> VerdictPreuve:
    """Fait examiner la preuve par Claude, puis enregistre la compétence (confirmée ou seulement déclarée)."""
    prompt = f"Compétence à vérifier : {nom}\n\nDescription du candidat :\n{description}\n"
    if lien:
        prompt += f"\nLien fourni : {lien}\n"
    if contenu_fichier:
        prompt += f"\nContenu du fichier fourni (extrait) :\n{contenu_fichier[:TAILLE_MAX_FICHIER]}\n"
    verdict = generer_json(prompt, SYSTEME_PREUVE, VerdictPreuve, outils=OUTILS_WEB if lien else None)
    with closing(stockage.connecter()) as c:
        stockage.declarer_competence(c, {
            "cle": cle(nom), "nom": nom, "statut": "confirmée" if verdict.convaincant else "déclarée",
            "description": description, "lien": lien or None, "verdict": verdict.remarque, "resume_cv": verdict.resume_cv,
        })
    return verdict
