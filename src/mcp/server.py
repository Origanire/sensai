# Ce module expose la mémoire, les documents et les rapports de Sensai sous forme d’outils MCP.

import json
import sys

from src.core.memory import (
    find_viewer_id,
    init_memory,
    load_facts,
    load_stats,
    load_summary,
    save_fact,
)
from src.core.ollama_client import OllamaClient, load_config
from src.core.search import load_rag_settings, search
from src.core.storage import DOCUMENTS, init_db
from src.tools.report import init_report, render_report, update_report_from_event

# Cette valeur indique la version du protocole MCP utilisée par le serveur.
PROTOCOL_VERSION = "2025-06-18"
# Ces codes identifient les erreurs JSON-RPC.
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

# Ces définitions décrivent les outils MCP et indiquent ceux qui ne modifient pas les données.
TOOLS = [
    {
        "name": "get_viewer_profile",
        "description": "Renvoie ce que Sensai sait d'un viewer du chat Twitch : faits "
                       "enregistrés, résumé des échanges passés, nombre de visites.",
        "inputSchema": {
            "type": "object",
            "properties": {"login": {"type": "string", "description": "Pseudo Twitch du viewer"}},
            "required": ["login"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "remember_viewer_fact",
        "description": "Enregistre durablement un fait sur un viewer (ex : « déteste les spoilers »).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "login": {"type": "string", "description": "Pseudo Twitch du viewer"},
                "fact": {"type": "string", "description": "Fait à retenir"},
            },
            "required": ["login", "fact"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "search_channel_docs",
        "description": "Cherche dans la base de connaissances de la chaîne (FAQ, planning, "
                       "setup PC, règles du chat) les passages qui répondent à une question.",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_stream_report",
        "description": "Renvoie le compte-rendu du stream en cours : jeu actuel, moments forts, stats.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "add_stream_event",
        "description": "Ajoute un événement au compte-rendu du stream en cours "
                       "(changement de jeu, boss battu, record de viewers...).",
        "inputSchema": {
            "type": "object",
            "properties": {"description": {"type": "string", "description": "L'événement"}},
            "required": ["description"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
]


# Cette classe exécute les outils avec une base et un client partagés.
class SensaiTools:
    # On ouvre la base et le client Ollama nécessaires aux outils.
    def __init__(self):
        config = load_config()
        # Ce client prépare les vecteurs et les modifications du rapport.
        self.client = OllamaClient(config)
        # Ces réglages servent à la recherche documentaire.
        self.rag = load_rag_settings(config)
        # Cette connexion donne accès à la mémoire des viewers.
        self.memory = init_memory()
        # Cette connexion donne accès aux passages des documents.
        self.chunks = init_db()

    # Cette méthode choisit l’outil demandé et vérifie ses arguments avant de l’exécuter.
    def call(self, name, arguments):
        match name:
            case "get_viewer_profile":
                return self.viewer_profile(arguments["login"])
            case "remember_viewer_fact":
                return self.remember(arguments["login"], arguments["fact"])
            case "search_channel_docs":
                return self.search_docs(arguments["question"])
            case "get_stream_report":
                return render_report(init_report())
            case "add_stream_event":
                report, update = update_report_from_event(arguments["description"], self.client)
                if update is None:
                    return "Le modèle n'a pas pu interpréter l'événement, compte-rendu inchangé."
                return (f"Section « {update['section']} » mise à jour ({update['action']}) : "
                        f"{update['content']}")
            case _:
                raise ValueError(f"outil inconnu : {name}")

    # Cette méthode retrouve et décrit le profil d’un viewer à partir de son pseudo.
    def viewer_profile(self, login):
        login = login.lstrip("@")
        viewer_id = find_viewer_id(self.memory, login)
        if viewer_id is None:
            return f"Aucun viewer « {login} » connu : il n'a jamais écrit dans le chat."

        facts = load_facts(self.memory, viewer_id)
        summary = load_summary(self.memory, viewer_id)
        stats = load_stats(self.memory, viewer_id) or {}
        lines = [f"Viewer : {login}",
                 f"Visites : {stats.get('visits', 0)}, messages : {stats.get('message_count', 0)}"]
        lines.append("Faits : " + ("; ".join(facts) if facts else "aucun"))
        lines.append("Résumé des échanges : " + (summary or "aucun"))
        return "\n".join(lines)

    # Cette méthode enregistre un fait sur le viewer demandé.
    def remember(self, login, fact):
        login = login.lstrip("@")
        viewer_id = find_viewer_id(self.memory, login)
        if viewer_id is None:
            return f"Impossible : « {login} » n'a jamais écrit dans le chat."
        save_fact(self.memory, viewer_id, fact.strip())
        return f"Fait enregistré pour {login} : {fact.strip()}"

    # Cette méthode renvoie les passages pertinents de la base pour que le modèle puisse construire sa réponse.
    def search_docs(self, question):
        results = search(question, self.client, self.chunks, self.rag["top_k"],
                         DOCUMENTS, self.rag["min_score"])
        if not results:
            return "Aucun passage pertinent dans la base de connaissances."
        return "\n\n".join(
            f"[{i}] {chunk['source']} (score {score:.2f})\n{chunk['text']}"
            for i, (score, chunk) in enumerate(results, 1)
        )


# Cette fonction écrit un message JSON-RPC sur la sortie réservée au protocole.
def send(out, message):
    out.write(json.dumps(message, ensure_ascii=False) + "\n")
    out.flush()


# Cette fonction traite une requête JSON-RPC et renvoie son résultat.
def handle(tools, message):
    method = message.get("method")
    params = message.get("params") or {}
    match method:
        case "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "sensai", "version": "1.0"},
            }
        case "ping":
            return {}
        case "tools/list":
            return {"tools": TOOLS}
        case "tools/call":
            try:
                text = tools().call(params.get("name"), params.get("arguments") or {})
                return {"content": [{"type": "text", "text": text}], "isError": False}
            except (KeyError, ValueError) as error:
                # Une erreur d’outil est renvoyée au modèle pour qu’il puisse la comprendre et corriger sa demande.
                return {"content": [{"type": "text", "text": f"Erreur : {error}"}], "isError": True}
        case _:
            raise LookupError(method)


# Cette fonction traite les requêtes reçues sur l’entrée standard jusqu’à sa fermeture.
def main():
    out = sys.stdout
    sys.stdout = sys.stderr
    instance = None

    def tools():
        nonlocal instance
        if instance is None:
            instance = SensaiTools()
        return instance

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in message:
            continue  # Cette notification n’attend pas de réponse.

        try:
            send(out, {"jsonrpc": "2.0", "id": message["id"], "result": handle(tools, message)})
        except LookupError:
            send(out, {"jsonrpc": "2.0", "id": message["id"], "error": {
                "code": METHOD_NOT_FOUND, "message": f"méthode inconnue : {message.get('method')}"}})
        except Exception as error:
            send(out, {"jsonrpc": "2.0", "id": message["id"], "error": {
                "code": INVALID_PARAMS, "message": str(error)}})


if __name__ == "__main__":
    main()
