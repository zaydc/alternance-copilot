"""Point d'accès unique au LLM.

Le reste du projet n'importe jamais le Claude Agent SDK directement : pour passer à une clé API
(ou à un autre fournisseur), seul ce fichier change.
"""

import asyncio
import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultError,
    ResultMessage,
    StreamEvent,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)
from pydantic import BaseModel

# « sonnet » plutôt qu'« opus » : largement suffisant pour de l'extraction et de la notation,
# et consomme moins les limites de l'abonnement Pro (partagées avec claude.ai)
MODELE = "sonnet"
# Effort par défaut : « medium » consomme nettement moins que le « high » du SDK, pour une qualité équivalente
# sur nos tâches guidées par un schéma. Les appels simples (notation, raccourcissement) passent en « low ».
EFFORT = "medium"
# Consommation du dernier appel, utile pour mesurer le coût d'une fonctionnalité
DERNIER_USAGE: dict = {}

# Outils en lecture seule qu'on accepte de donner à Claude (recherche d'informations sur une entreprise)
OUTILS_WEB = ["WebSearch", "WebFetch"]

# Dossier de travail des conversations : l'historique des sessions est rangé à part de celui du projet
DOSSIER_SESSIONS = Path(__file__).resolve().parent.parent / "data" / "sessions"
NOM_SERVEUR_OUTILS = "copilot"


class ErreurLLM(RuntimeError):
    pass


async def _generer_json(prompt: str, systeme: str, schema: type[BaseModel], outils: list[str],
                        modele: str, effort: str) -> BaseModel:
    options = ClaudeAgentOptions(
        model=modele,
        effort=effort,
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
    DERNIER_USAGE.clear()
    DERNIER_USAGE.update({"modele": modele, "effort": effort, "duree_s": round(resultat.duration_ms / 1000, 1),
                          **{c: resultat.usage.get(c, 0) for c in ("input_tokens", "output_tokens",
                             "cache_read_input_tokens", "cache_creation_input_tokens")}})
    if resultat.is_error or resultat.structured_output is None:
        raise ErreurLLM(f"Pas de réponse structurée ({resultat.subtype}) : {resultat.result}")
    # Double sécurité : Pydantic revalide la sortie (types, champs obligatoires)
    return schema.model_validate(resultat.structured_output)


def generer_json[M: BaseModel](prompt: str, systeme: str, schema: type[M], outils: list[str] | None = None,
                               modele: str = MODELE, effort: str = EFFORT) -> M:
    """Demande à Claude une réponse conforme au modèle Pydantic `schema` et la renvoie validée.

    `outils` : outils intégrés mis à disposition (par défaut aucun), ex. OUTILS_WEB.
    `effort` : profondeur de réflexion, donc coût en tokens (« low », « medium », « high »).
    """
    return asyncio.run(_generer_json(prompt, systeme, schema, outils or [], modele, effort))


# ---------------------------------------------------------------- Conversation avec outils personnalisés

@dataclass
class OutilPerso:
    """Outil écrit en Python, décrit sans dépendre du SDK."""
    nom: str
    description: str
    parametres: dict[str, type]  # ex. {"offre_id": str} ; {} si aucun paramètre
    fonction: Callable[..., str]  # appelée avec les paramètres nommés, renvoie du texte


def _vers_outil_sdk(outil: OutilPerso):
    @tool(outil.nom, outil.description, outil.parametres)
    async def executer(arguments: dict) -> dict:
        try:
            # Les fonctions font des accès SQLite / HTTP bloquants : on les sort de la boucle asyncio
            texte = await asyncio.to_thread(outil.fonction, **arguments)
        except Exception as erreur:  # l'agent voit l'erreur et peut s'adapter, au lieu de tout interrompre
            return {"content": [{"type": "text", "text": f"Erreur : {erreur}"}], "is_error": True}
        return {"content": [{"type": "text", "text": texte}]}

    return executer


async def _discuter(message: str, systeme: str, outils: list[OutilPerso], session: str | None, emettre) -> None:
    serveur = create_sdk_mcp_server(NOM_SERVEUR_OUTILS, tools=[_vers_outil_sdk(o) for o in outils])
    noms_outils = OUTILS_WEB + [f"mcp__{NOM_SERVEUR_OUTILS}__{o.nom}" for o in outils]
    DOSSIER_SESSIONS.mkdir(parents=True, exist_ok=True)
    options = ClaudeAgentOptions(
        model=MODELE,
        system_prompt=systeme,
        tools=OUTILS_WEB,  # outils intégrés disponibles : web en lecture seule, rien d'autre
        mcp_servers={NOM_SERVEUR_OUTILS: serveur},
        allowed_tools=noms_outils,
        resume=session,  # reprend l'historique de la conversation
        include_partial_messages=True,  # texte envoyé au fil de l'eau
        max_turns=12,
        cwd=DOSSIER_SESSIONS,
    )
    try:
        async for evenement in query(prompt=message, options=options):
            if isinstance(evenement, StreamEvent):
                delta = evenement.event.get("delta", {})
                if evenement.event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                    emettre(("texte", delta["text"]))
            elif isinstance(evenement, AssistantMessage):
                for bloc in evenement.content:
                    if isinstance(bloc, ToolUseBlock):
                        emettre(("outil", bloc.name.removeprefix(f"mcp__{NOM_SERVEUR_OUTILS}__")))
            elif isinstance(evenement, ResultMessage):
                if evenement.is_error:
                    raise ErreurLLM(f"Claude a renvoyé une erreur : {evenement.result}")
                emettre(("session", evenement.session_id))
    except ResultError as erreur:
        raise ErreurLLM(f"Claude a renvoyé une erreur : {erreur.result or erreur.errors}") from erreur


def discuter(message: str, systeme: str, outils: list[OutilPerso], session: str | None = None) -> Iterator[tuple[str, str]]:
    """Envoie un message à l'agent et produit ses événements au fil de l'eau :
    ("texte", morceau de réponse), ("outil", nom de l'outil appelé), ("session", id à passer au tour suivant).

    Générateur synchrone (utilisable par Streamlit) : la boucle asyncio tourne dans un fil d'exécution séparé.
    """
    file: queue.Queue = queue.Queue()
    fin = object()

    def travail() -> None:
        try:
            asyncio.run(_discuter(message, systeme, outils, session, file.put))
        except Exception as erreur:
            file.put(("erreur", erreur))
        finally:
            file.put(fin)

    threading.Thread(target=travail, daemon=True).start()
    while (evenement := file.get()) is not fin:
        if evenement[0] == "erreur":
            erreur = evenement[1]
            raise erreur if isinstance(erreur, ErreurLLM) else ErreurLLM(str(erreur))
        yield evenement
