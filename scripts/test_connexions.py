"""Vérifie que les deux accès du projet fonctionnent : Claude (abonnement Pro) et l'API La bonne alternance.

Lancement (depuis la racine du projet) :
    .venv\\Scripts\\python.exe scripts\\test_connexions.py
"""

import asyncio
import os
import sys

import httpx
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query
from dotenv import load_dotenv

API_LBA = "https://api.apprentissage.beta.gouv.fr/api"
CODE_POSTAL = "91270"  # Vigneux-sur-Seine
RAYON_KM = 20


async def tester_claude() -> None:
    # tools vide : aucun outil disponible, l'agent ne peut que répondre (moindre privilège)
    options = ClaudeAgentOptions(tools=[], max_turns=1)
    reponse = ""
    async for message in query(prompt="Réponds uniquement par le mot OK.", options=options):
        if isinstance(message, AssistantMessage):
            reponse += "".join(bloc.text for bloc in message.content if isinstance(bloc, TextBlock))
        elif isinstance(message, ResultMessage) and message.is_error:
            raise RuntimeError(f"Erreur renvoyée par Claude : {message.result}")
    print(f"  Réponse de Claude : {reponse.strip()!r}")


def tester_la_bonne_alternance() -> None:
    entetes = {"Authorization": f"Bearer {os.environ['LBA_API_TOKEN']}"}
    with httpx.Client(base_url=API_LBA, headers=entetes, timeout=30) as client:
        # 1. Code postal -> coordonnées GPS du centre de la commune
        reponse = client.get("/geographie/v1/commune/search", params={"code": CODE_POSTAL})
        reponse.raise_for_status()
        commune = reponse.json()[0]
        longitude, latitude = commune["localisation"]["centre"]["coordinates"]
        print(f"  Commune : {commune['nom']} ({latitude:.4f}, {longitude:.4f})")

        # 2. Offres d'alternance autour de ce point
        reponse = client.get(
            "/job/v1/search",
            params={"latitude": latitude, "longitude": longitude, "radius": RAYON_KM},
        )
        reponse.raise_for_status()
        resultats = reponse.json()

    offres = resultats["jobs"]
    print(f"  {len(offres)} offres et {len(resultats['recruiters'])} entreprises dans un rayon de {RAYON_KM} km")
    for offre in offres[:3]:
        lieu = offre["workplace"]["location"].get("address", "?")
        print(f"   - {offre['offer']['title']} | {offre['workplace']['name']} | {lieu}")
    for alerte in resultats["warnings"]:
        print(f"  Avertissement API : {alerte['message']}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # accents corrects dans la console Windows
    load_dotenv()

    ok = True
    for nom, test in [
        ("Claude", lambda: asyncio.run(tester_claude())),
        ("La bonne alternance", tester_la_bonne_alternance),
    ]:
        print(f"[{nom}]")
        try:
            test()
            print("  ✅ OK")
        except Exception as erreur:
            ok = False
            print(f"  ❌ Échec : {type(erreur).__name__}: {erreur}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
