"""Point d'accès unique au LLM.

Le reste du projet n'importe jamais le Claude Agent SDK directement : pour passer à une clé API
(ou à un autre fournisseur), seul ce fichier change.
"""

import asyncio

from claude_agent_sdk import ClaudeAgentOptions, ResultError, ResultMessage, query
from pydantic import BaseModel

# « sonnet » plutôt qu'« opus » : largement suffisant pour de l'extraction et de la notation,
# et consomme moins les limites de l'abonnement Pro (partagées avec claude.ai)
MODELE = "sonnet"

# Outils en lecture seule qu'on accepte de donner à Claude (recherche d'informations sur une entreprise)
OUTILS_WEB = ["WebSearch", "WebFetch"]


class ErreurLLM(RuntimeError):
    pass


async def _generer_json(prompt: str, systeme: str, schema: type[BaseModel], outils: list[str]) -> BaseModel:
    options = ClaudeAgentOptions(
        model=MODELE,
        system_prompt=systeme,
        # Moindre privilège : « tools » fixe les outils DISPONIBLES (liste vide = aucun : ni fichiers, ni shell).
        # « allowed_tools » ne fait qu'autoriser sans confirmation ceux de la liste : il ne restreint rien.
        tools=outils,
        allowed_tools=outils,
        output_format={"type": "json_schema", "schema": schema.model_json_schema()},
    )
    resultat = None
    # On consomme le flux jusqu'au bout : un « return » au milieu laisserait le générateur du SDK ouvert
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                resultat = message
    except ResultError as erreur:
        # Ex. : « You've hit your session limit · resets 3:20pm » (limites Pro partagées avec claude.ai)
        raise ErreurLLM(f"Claude a renvoyé une erreur : {erreur.result or erreur.errors}") from erreur
    if resultat is None:
        raise ErreurLLM("La conversation s'est terminée sans résultat")
    if resultat.is_error or resultat.structured_output is None:
        raise ErreurLLM(f"Pas de réponse structurée ({resultat.subtype}) : {resultat.result}")
    # Double sécurité : Pydantic revalide la sortie (types, champs obligatoires)
    return schema.model_validate(resultat.structured_output)


def generer_json[M: BaseModel](prompt: str, systeme: str, schema: type[M], outils: list[str] | None = None) -> M:
    """Demande à Claude une réponse conforme au modèle Pydantic `schema` et la renvoie validée.

    `outils` : outils intégrés mis à disposition (par défaut aucun), ex. OUTILS_WEB.
    """
    return asyncio.run(_generer_json(prompt, systeme, schema, outils or []))
