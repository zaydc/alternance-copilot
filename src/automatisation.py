"""Tâche automatique en arrière-plan : collecte quotidienne, notation quelques jours par semaine.

Lancée chaque matin par le Planificateur de tâches Windows (voir scripts/planifier_tache.ps1), sans fenêtre
ni notification : le résultat s'affiche dans la barre latérale de l'application et dans data/logs.
    .venv\\Scripts\\pythonw.exe -m src.automatisation
Option : --noter (force la notation)
"""

import logging
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from src import collecte, notation, stockage
from src.llm_client import ErreurLLM
from src.profil import DOSSIER_DATA, profil_en_cache

# La collecte est gratuite (API) : tous les jours. La notation consomme le quota Claude : lundi, mercredi, vendredi.
JOURS_NOTATION = {0: "lundi", 2: "mercredi", 4: "vendredi"}
# Rattrapage : si le PC était éteint un jour de notation, on note dès que la dernière notation a plus de 3 jours
RATTRAPAGE_JOURS = 3

CHEMIN_JOURNAL = DOSSIER_DATA / "logs" / "automatisation.log"
NOM_TACHE = "Alternance Copilot - collecte"  # même nom que dans scripts/planifier_tache.ps1
journal = logging.getLogger("automatisation")


def tache_planifiee_active() -> bool:
    resultat = subprocess.run(["schtasks", "/Query", "/TN", NOM_TACHE], capture_output=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    return resultat.returncode == 0


def notation_prevue(derniere_notation: str | None, maintenant: datetime, forcer: bool = False) -> bool:
    if forcer or maintenant.astimezone().weekday() in JOURS_NOTATION:
        return True
    if derniere_notation is None:
        return True
    return maintenant - datetime.fromisoformat(derniere_notation) > timedelta(days=RATTRAPAGE_JOURS)


def executer(origine: str = "planifiée", forcer_notation: bool = False, avec_notation: bool = True) -> dict:
    """Collecte, puis notation si c'est un jour prévu. Chaque exécution est historisée (table executions)."""
    bilan = {"origine": origine, "nouvelles_offres": None, "offres_notees": None, "erreur": None}

    try:
        resultat = collecte.collecter()
        with closing(stockage.connecter()) as c:
            bilan["nouvelles_offres"] = stockage.nouvelles_offres_visibles(c, resultat["date"])
        journal.info("Collecte : %s offres, %s nouvelles (hors écoles)", resultat["offres"], bilan["nouvelles_offres"])
    except Exception as erreur:
        bilan["erreur"] = f"Collecte : {erreur}"
        journal.exception("Échec de la collecte")

    with closing(stockage.connecter()) as c:
        prevue = avec_notation and notation_prevue(stockage.derniere_notation(c), datetime.now(timezone.utc), forcer_notation)
    if prevue and profil_en_cache():
        try:
            bilan["offres_notees"] = notation.noter_offres(progression=journal.info)
        except ErreurLLM as erreur:  # ex. limite de session atteinte : on réessaiera au prochain lancement
            bilan["erreur"] = f"Notation reportée : {erreur}"
            journal.warning("Notation reportée : %s", erreur)
    else:
        journal.info("Pas de notation cette fois (prévue le %s)", ", ".join(JOURS_NOTATION.values()))

    with closing(stockage.connecter()) as c:
        stockage.enregistrer_execution(c, bilan)
    return bilan


def main() -> None:
    CHEMIN_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=CHEMIN_JOURNAL, encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # pas une ligne par requête HTTP
    load_dotenv(DOSSIER_DATA.parent / ".env")  # chemin explicite : la tâche planifiée ne garantit pas le dossier courant
    journal.info("---- Démarrage (%s)", " ".join(sys.argv[1:]) or "sans option")
    bilan = executer(forcer_notation="--noter" in sys.argv)
    journal.info("Terminé : %s", bilan)


if __name__ == "__main__":
    main()
