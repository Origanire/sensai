## @file tools.py
# @brief Tool calling (T1): the model decides mid-conversation to call a
# tool exposed by an MCP server, the code runs it and hands the result back.

import json

from src.mcp.client import MCPClient, MCPError

## @brief Maximum number of tool rounds for one user message: a small model
# can loop on the same call, this caps the cost.
DEFAULT_MAX_STEPS = 4
## @brief Length of a tool result shown in the terminal.
PREVIEW_LENGTH = 200
## @brief Maximum length of a tool result given to the model, in characters.
MAX_RESULT_LENGTH = 4000

## @brief Instructions sent with the tools: without them, llama3.2 calls a
# tool even to answer "hello".
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


## @brief Every tool of every configured MCP server, behind one interface.
class ToolRegistry:
    ## @brief Connect to the MCP servers of the configuration.
    #
    # A server that fails to start is skipped with a message: the assistant
    # keeps working with the others.
    #
    # @param settings "mcp" section of config.yaml.
    def __init__(self, settings):
        ## @brief Open connections, by server name.
        self.servers = {}
        ## @brief Tool definitions, by tool name: (server name, MCP definition).
        self.tools = {}
        ## @brief Maximum number of tool rounds per message.
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

    ## @brief Tool definitions in the format expected by Ollama.
    #
    # @return List of {"type": "function", "function": {...}} dicts.
    def ollama_tools(self):
        return [{
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            },
        } for _, tool in self.tools.values()]

    ## @brief Tell whether a tool may change something.
    #
    # Relies on the MCP "readOnlyHint" annotation: a tool that does not
    # declare itself read-only is treated as a write, to be safe.
    #
    # @param name Name of the tool.
    # @return True if a confirmation is needed before running it.
    def needs_confirmation(self, name):
        _, tool = self.tools[name]
        return not (tool.get("annotations") or {}).get("readOnlyHint", False)

    ## @brief Run a tool on its server.
    #
    # Never raises: a failure is returned as text, so the model can read it
    # and tell the user, or try something else.
    #
    # @param name Name of the tool.
    # @param arguments Arguments chosen by the model.
    # @return Text result.
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

    ## @brief Describe the available tools, for display.
    #
    # @return One line per tool, with its server and whether it writes.
    def describe(self):
        if not self.tools:
            return "Aucun outil MCP disponible."
        lines = []
        for name, (server, tool) in self.tools.items():
            mode = "écriture, confirmation" if self.needs_confirmation(name) else "lecture"
            lines.append(f"- {name} [{server}, {mode}]")
        return "\n".join(lines)

    ## @brief Stop every server.
    def close(self):
        for client in self.servers.values():
            client.close()


## @brief Ask the user to approve a tool call (human in the loop).
#
# @param name Name of the tool.
# @param arguments Arguments chosen by the model.
# @return True if the user typed "o" / "oui" / "y".
def ask_confirmation(name, arguments):
    shown = json.dumps(arguments, ensure_ascii=False)
    try:
        answer = input(f"[MCP] Sensai veut exécuter {name}({shown}). Autoriser ? [o/N] ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in ("o", "oui", "y", "yes")


## @brief Tell whether a text answer is in fact a tool call written as JSON.
#
# @param content Text answer of the model.
# @return True for a JSON object with a "name" and "parameters"/"arguments".
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


## @brief Answer a conversation, letting the model call tools as needed.
#
# Loop: the model answers or asks for tools; each call is run (after a
# confirmation for tools that write) and its result appended as a "tool"
# message; the model is called again with the results, until it answers
# in text or max_steps rounds have passed. The assistant's tool requests
# and the results are appended to messages: they stay in the history.
#
# @param client OllamaClient.
# @param messages Conversation, modified in place.
# @param registry ToolRegistry.
# @param confirm Function (name, arguments) -> bool, asked before a write.
# @return The final text answer, or None if the model failed.
def chat_with_tools(client, messages, registry, confirm=ask_confirmation):
    tools = registry.ollama_tools()
    request = [{"role": "system", "content": TOOLS_SYSTEM_PROMPT}] + messages

    for _ in range(registry.max_steps):
        content, calls = client.chat_with_tools(request, tools)
        if content is None and not calls:
            return None
        if not calls and looks_like_tool_call(content):
            # The model wrote a tool call as text (often for a tool that does
            # not exist): ask again without tools to get a real answer
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

    # Too many rounds: one last call without tools forces a text answer
    content, _ = client.chat_with_tools(request, tools=None)
    return content


## @brief Start the MCP servers of the configuration, if enabled.
#
# @param config Configuration dictionary loaded from config.yaml.
# @return A ToolRegistry, or None if MCP is disabled or no server started.
def load_registry(config):
    settings = (config or {}).get("mcp") or {}
    if not settings.get("enabled", False):
        return None
    registry = ToolRegistry(settings)
    if not registry.tools:
        registry.close()
        return None
    return registry
