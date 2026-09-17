"""Notation des offres par Claude au regard du profil candidat.

Claude note les critères qualitatifs (technique, niveau, rythme) ; la distance et le score global
pondéré sont calculés en Python : c'est déterministe, gratuit et réglable.

Lancement (depuis la racine du projet) :
    .venv\\Scripts\\python.exe -m src.notation
"""

import json
import sys
from collections.abc import Callable
from contextlib import closing

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src import stockage
from src.llm_client import generer_json
from src.profil import charger_profil

TAILLE_LOT = 10
LONGUEUR_MAX_DESCRIPTION = 4000  # limite la taille du prompt (quota Pro)
PONDERATIONS = {"technique": 0.55, "niveau": 0.20, "distance": 0.15, "rythme": 0.10}


class NoteOffre(BaseModel):
    offre_id: str
    score_technique: int = Field(ge=0, le=100, description="Adéquation missions / stack avec les compétences du profil")
    score_niveau: int = Field(ge=0, le=100, description="Adéquation du diplôme préparé avec le niveau demandé")
    score_rythme: int = Field(ge=0, le=100, description="Compatibilité du rythme ; 50 si l'offre ne le précise pas")
    justification: str = Field(description="2 à 3 phrases, en s'adressant au candidat")
    points_forts: list[str] = Field(description="Éléments du profil qui correspondent à l'offre")
    points_vigilance: list[str] = Field(description="Écarts, exigences non couvertes, informations manquantes")


class NotesLot(BaseModel):
    notes: list[NoteOffre]


SYSTEME = """Tu es un conseiller en recrutement spécialisé dans l'alternance en informatique.
Tu évalues chaque offre au regard du profil d'un candidat, de façon honnête et exigeante :
une offre hors du métier du candidat (RH, communication, commercial...) doit avoir un score technique bas,
même si elle contient les mots « data » ou « SI ».
Pour le niveau, fie-toi d'abord à la description : elle prime sur le champ « Niveau de diplôme visé ».
Tutoie toujours le candidat.
Note chaque offre fournie, une seule fois, en reprenant exactement son identifiant."""


def score_distance(distance_km: float) -> int:
    """100 jusqu'à 5 km, puis -3 points par km (25 à 30 km, limite de la zone)."""
    return max(0, min(100, round(100 - (distance_km - 5) * 3)))


def score_global(note: dict) -> int:
    return round(sum(note[f"score_{critere}"] * poids for critere, poids in PONDERATIONS.items()))


def formater_offre(offre) -> str:
    description = offre["description"][:LONGUEUR_MAX_DESCRIPTION]
    return (
        f"### Offre {offre['id']}\n"
        f"Titre : {offre['titre']}\n"
        f"Entreprise : {offre['entreprise'] or 'non communiquée'}\n"
        f"Niveau de diplôme visé : {offre['niveau_diplome'] or 'non précisé'}\n"
        f"Contrat : {', '.join(json.loads(offre['types_contrat']))}, {offre['duree_mois'] or '?'} mois\n"
        f"Description :\n{description}"
    )


def noter_lot(profil_json: str, offres: list) -> list[NoteOffre]:
    prompt = (
        f"## Profil du candidat\n{profil_json}\n\n"
        f"## Offres à noter ({len(offres)})\n\n" + "\n\n".join(map(formater_offre, offres))
    )
    notes = generer_json(prompt, SYSTEME, NotesLot).notes
    ids_attendus = {offre["id"] for offre in offres}
    # On ignore un identifiant inventé ; une offre oubliée sera simplement notée au prochain lancement
    return [note for note in notes if note.offre_id in ids_attendus]


def noter_offres(progression: Callable[[str], None] = print) -> int:
    """Note les offres pas encore en cache. `progression` reçoit les messages d'avancement. Renvoie le nombre de notes."""
    profil, hash_cv = charger_profil()
    profil_json = profil.model_dump_json(indent=1)
    total = 0

    with closing(stockage.connecter()) as connexion:
        offres = stockage.offres_a_noter(connexion, hash_cv)
        distances = {offre["id"]: offre["distance_km"] for offre in offres}
        progression(f"{len(offres)} offres à noter (les autres sont déjà en cache)")

        for debut in range(0, len(offres), TAILLE_LOT):
            lot = offres[debut : debut + TAILLE_LOT]
            progression(f"Lot {debut // TAILLE_LOT + 1} : {len(lot)} offres en cours de notation...")
            notations = []
            for note in noter_lot(profil_json, lot):
                notation = note.model_dump()
                notation["score_distance"] = score_distance(distances[note.offre_id])
                notation |= {"profil_hash": hash_cv, "score": score_global(notation), "date": stockage.maintenant()}
                notations.append(notation)
            # Enregistrement après chaque lot : si un lot échoue, les précédents restent en cache
            stockage.enregistrer_notations(connexion, notations)
            total += len(notations)
    return total


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    noter_offres()
    _, hash_cv = charger_profil()
    print("\nClassement :")
    with closing(stockage.connecter()) as connexion:
        for ligne in stockage.classement(connexion, hash_cv):
            print(
                f"  {ligne['score']:3d}  (tech {ligne['score_technique']:3d} | niv {ligne['score_niveau']:3d} "
                f"| dist {ligne['score_distance']:3d} | rythme {ligne['score_rythme']:3d})  "
                f"{ligne['titre'][:55]} — {ligne['distance_km']} km"
            )


if __name__ == "__main__":
    main()
