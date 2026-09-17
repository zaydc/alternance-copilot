"""Point d'accès unique au LLM.

Le reste du projet n'importe jamais le Claude Agent SDK directement : pour passer à une clé API
(ou à un autre fournisseur), seul ce fichier change.
"""

import asyncio

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from pydantic import BaseModel

# « sonnet » plutôt qu'« opus » : largement suffisant pour de l'extraction et de la notation,
# et consomme moins les limites de l'abonnement Pro (partagées avec claude.ai)
MODELE = "sonnet"


class ErreurLLM(RuntimeError):
    pass


async def _generer_json(prompt: str, systeme: str, schema: type[BaseModel]) -> BaseModel:
    options = ClaudeAgentOptions(
        model=MODELE,
        system_prompt=systeme,
        allowed_tools=[],  # moindre privilège : aucun outil (fichiers, shell, web...)
        output_format={"type": "json_schema", "schema": schema.model_json_schema()},
    )
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            if message.is_error or message.structured_output is None:
                raise ErreurLLM(f"Pas de réponse structurée ({message.subtype}) : {message.result}")
            # Double sécurité : Pydantic revalide la sortie (types, champs obligatoires)
            return schema.model_validate(message.structured_output)
    raise ErreurLLM("La conversation s'est terminée sans résultat")


def generer_json[M: BaseModel](prompt: str, systeme: str, schema: type[M]) -> M:
    """Demande à Claude une réponse conforme au modèle Pydantic `schema` et la renvoie validée."""
    return asyncio.run(_generer_json(prompt, systeme, schema))
