# Ce module exécute les outils demandés par le modèle et lui transmet leurs résultats pour continuer la conversation.

import json

from src.mcp.client import MCPClient, MCPError

# Cette limite évite que le modèle demande des outils en boucle pour un seul message.
DEFAULT_MAX_STEPS = 4
# Cette valeur limite le résultat d’un outil affiché dans le terminal.
PREVIEW_LENGTH = 200
# Cette valeur limite la taille du résultat transmis au modèle.
MAX_RESULT_LENGTH = 4000

# Ces consignes évitent d’appeler un outil pour une simple conversation.
TOOLS_SYSTEM_PROMPT = """Tu es Sensai, l'assistant d'un streamer Twitch. Tu as accès à des outils.

Quel outil pour quelle demande :
- question sur la chaîne (planning, setup PC, matériel, règles du chat, jeu en
  cours, abonnements, Discord) : search_channel_docs
- question sur un viewer précis : get_viewer_profile
- compte-rendu du stream : get_stream_report pour le lire, add_stream_event
  pour y noter un événement
- fichiers : list_allowed_directories d'abord, puis des chemins absolus
- salutation, calcul, culture générale, conversation : AUCUN outil, réponds
  directement.

Après un appel d'outil, réponds en t'appuyant uniquement sur son résultat.
Si l'outil renvoie une erreur ou ne trouve rien, dis-le simplement : n'invente
jamais une information. Réponds en français, de façon concise."""


# Cette classe rassemble les outils de tous les serveurs MCP derrière une même interface.
class ToolRegistry:
    # On connecte les serveurs configurés et on ignore ceux qui échouent, pour garder les autres outils disponibles.
    def __init__(self, settings):
        # Ces connexions sont regroupées par nom de serveur.
        self.servers = {}
        # Ces définitions associent chaque outil à son serveur.
        self.tools = {}
        # Cette valeur limite le nombre de tours d’outils par message.
        self.max_steps = settings.get("max_steps", DEFAULT_MAX_STEPS)

        for name, server in (settings.get("servers") or {}).items():
            try:
                client = MCPClient(name, server["command"], server.get("args"), server.get("env"))
                definitions = client.list_tools()
            except (MCPError, KeyError) as error:
                print(f"[MCP] serveur « {name} » ignoré : {error}")
                continue

            allowed = server.get("allowed_tools")
            self.servers[name] = client
            for tool in definitions:
                if allowed is not None and tool["name"] not in allowed:
                    continue
                if tool["name"] in self.tools:
                    print(f"[MCP] outil « {tool['name']} » de « {name} » ignoré : nom déjà pris")
                    continue
                self.tools[tool["name"]] = (name, tool)

    # Cette méthode décrit les outils dans le format attendu par Ollama.
    def ollama_tools(self):
        return [{
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            },
        } for _, tool in self.tools.values()]

    # Cette méthode vérifie si l’outil peut modifier des données. Sans indication de lecture seule, une confirmation est nécessaire.
    def needs_confirmation(self, name):
        _, tool = self.tools[name]
        return not (tool.get("annotations") or {}).get("readOnlyHint", False)

    # Cette méthode exécute l’outil sur son serveur et transforme les échecs en texte lisible par le modèle.
    def call(self, name, arguments):
        if name not in self.tools:
            return f"Erreur : l'outil « {name} » n'existe pas. Outils disponibles : {', '.join(self.tools)}."
        server, _ = self.tools[name]
        try:
            text, is_error = self.servers[server].call_tool(name, arguments)
        except MCPError as error:
            return f"Erreur : {error}"
        text = text[:MAX_RESULT_LENGTH]
        return f"Erreur : {text}" if is_error else text

    # Cette méthode liste les outils disponibles et indique ceux qui écrivent des données.
    def describe(self):
        if not self.tools:
            return "Aucun outil MCP disponible."
        lines = []
        for name, (server, tool) in self.tools.items():
            mode = "écriture, confirmation" if self.needs_confirmation(name) else "lecture"
            lines.append(f"- {name} [{server}, {mode}]")
        return "\n".join(lines)

    # Cette méthode arrête tous les serveurs MCP.
    def close(self):
        for client in self.servers.values():
            client.close()


# Cette fonction demande à l’utilisateur de confirmer l’appel d’un outil.
def ask_confirmation(name, arguments):
    shown = json.dumps(arguments, ensure_ascii=False)
    try:
        answer = input(f"[MCP] Sensai veut exécuter {name}({shown}). Autoriser ? [o/N] ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in ("o", "oui", "y", "yes")


# Cette fonction détecte un appel d’outil écrit par erreur comme une réponse JSON ordinaire.
def looks_like_tool_call(content):
    text = (content or "").strip().strip("`").removeprefix("json").strip()
    if not (text.startswith("{") and text.endswith("}")):
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and "name" in data \
        and ("parameters" in data or "arguments" in data)


# Cette fonction alterne les réponses du modèle et les appels d’outils, avec confirmation pour les actions qui écrivent.
def chat_with_tools(client, messages, registry, confirm=ask_confirmation):
    tools = registry.ollama_tools()
    request = [{"role": "system", "content": TOOLS_SYSTEM_PROMPT}] + messages

    for _ in range(registry.max_steps):
        content, calls = client.chat_with_tools(request, tools)
        if content is None and not calls:
            return None
        if not calls and looks_like_tool_call(content):
            # Si le modèle écrit un appel d’outil comme du texte, on lui redemande une réponse sans outils.
            print("\n[MCP] appel d'outil écrit en texte, nouvelle réponse sans outil.")
            print("Sensai : ", end="", flush=True)
            content, _ = client.chat_with_tools(request, tools=None)
            return content
        if not calls:
            return content

        assistant = {"role": "assistant", "content": content or "",
                     "tool_calls": [{"function": call} for call in calls]}
        messages.append(assistant)
        request.append(assistant)

        for call in calls:
            name, arguments = call["name"], call["arguments"]
            print(f"[MCP] appel : {name}({json.dumps(arguments, ensure_ascii=False)})")
            if name in registry.tools and registry.needs_confirmation(name) \
                    and not confirm(name, arguments):
                result = "L'utilisateur a refusé cet appel d'outil. Ne le refais pas."
            else:
                result = registry.call(name, arguments)
            preview = " ".join(result.split())[:PREVIEW_LENGTH]
            print(f"[MCP] résultat : {preview}")

            tool_message = {"role": "tool", "content": result, "tool_name": name}
            messages.append(tool_message)
            request.append(tool_message)

        print("Sensai : ", end="", flush=True)

    # Après trop d’appels, on demande une dernière réponse sans outils pour terminer.
    content, _ = client.chat_with_tools(request, tools=None)
    return content


# Cette fonction lance les serveurs MCP si l’option est activée et renvoie les outils disponibles.
def load_registry(config):
    settings = (config or {}).get("mcp") or {}
    if not settings.get("enabled", False):
        return None
    registry = ToolRegistry(settings)
    if not registry.tools:
        registry.close()
        return None
    return registry
