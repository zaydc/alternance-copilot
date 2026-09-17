"""Relances des candidatures restées sans réponse.

Détection automatique (J+7 après l'envoi, puis J+7 après la première relance, 2 relances maximum),
rédaction par Claude, envoi validé par l'utilisateur.
"""

from pydantic import BaseModel, Field

from src import stockage
from src.llm_client import generer_json

SYSTEME = """Tu rédiges la relance d'une candidature d'alternance restée sans réponse.
- En français, en vouvoyant, 50 à 90 mots, ton cordial et direct, sans reproche ni formule creuse.
- Rappelle brièvement la candidature initiale (date, poste ou démarche) et redis en une phrase la valeur apportée.
- Ajoute un élément nouveau si possible (disponibilité immédiate, rythme 1 semaine / 1 semaine, lien vers le portfolio).
- Termine par une question simple : un créneau de 15 minutes cette semaine ou la semaine prochaine.
- S'il s'agit de la seconde relance, dis-le avec tact : c'est le dernier message.
Ne mets ni signature ni coordonnées."""


class Relance(BaseModel):
    objet: str = Field(description="Objet : « Re : » suivi de l'objet initial s'il existe, sinon un objet court")
    corps: str = Field(description="Corps de la relance, 50 à 90 mots, sans signature")


def rediger_relance(connexion, candidature) -> int:
    """Rédige la relance de cette candidature, l'enregistre (non envoyée) et renvoie son id."""
    email_initial = stockage.email_par_id(connexion, candidature["email_id"])
    contexte = (
        f"Candidature : {candidature['nom']} (canal : {candidature['canal']})\n"
        f"Envoyée le : {candidature['date_envoi'][:10]}\n"
        f"Relance n° {candidature['nb_relances'] + 1} sur {stockage.MAX_RELANCES}\n"
    )
    if email_initial:
        contexte += (
            f"Activité de l'entreprise : {email_initial['ce_que_fait']}\n\n"
            f"## Message initial\nObjet : {email_initial['objet']}\n\n{email_initial['corps']}"
        )
    relance = generer_json(contexte, SYSTEME, Relance)  # aucun outil : tout le contexte est fourni
    return stockage.inserer(
        connexion,
        "relances",
        {"candidature_id": candidature["id"], **relance.model_dump(), "date_redaction": stockage.maintenant()},
    )
