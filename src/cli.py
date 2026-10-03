## @file cli.py
# @brief Sensai CLI chatbot: interactive conversation loop with Ollama.
#
# The streamer's own assistant: chat with the model (which may call MCP
# tools), plus slash commands for the knowledge base, the stream report,
# exports and scheduled reports. See /help.

import argparse
import os

from src.commands import commands
from src.core.export import DEFAULT_SHARE_PORT
from src.core.guardrails import load_guardrails
from src.core.ollama_client import CONFIG_ENV, OllamaClient, load_config
from src.core.search import load_rag_settings
from src.core.storage import init_db
from src.mcp.tools import chat_with_tools, load_registry
from src.tools.scheduled_reports import stop_scheduled_reports


## @brief Read the command-line options.
#
# @return Parsed arguments: config, model, no_tools.
def parse_args():
    parser = argparse.ArgumentParser(description="Sensai, assistant IA local (Ollama).")
    parser.add_argument("--config", help="fichier de configuration (défaut : config.yaml)")
    parser.add_argument("--model", help="modèle Ollama à utiliser, prioritaire sur la config")
    parser.add_argument("--no-tools", action="store_true",
                        help="ne pas démarrer les serveurs MCP (réponses plus rapides)")
    return parser.parse_args()


## @brief Entry point of the Sensai CLI chatbot.
#
# Interactive read loop: reads user input, sends the full conversation
# history to the model via Ollama and streams the response. The history
# is kept in memory for the whole session; slash commands are handled
# locally and never sent to the model.
def main():
    args = parse_args()
    # Set for the whole process, so the modules (and the MCP servers, which
    # inherit the environment) read the same file and model
    if args.config:
        os.environ[CONFIG_ENV] = args.config
    if args.model:
        os.environ["SENSAI_MODEL"] = args.model

    try:
        config = load_config()
    except FileNotFoundError as error:
        print(f"[Erreur] Configuration introuvable : {error.filename}")
        return

    client = OllamaClient(config)
    problem = client.check_model()
    if problem:
        print(f"[Attention] {problem}")

    guardrails = load_guardrails()
    registry = None if args.no_tools else load_registry(config)
    ctx = {
        "client": client,
        "chunks": init_db(),
        "rag": load_rag_settings(config),
        "registry": registry,
        "share_port": (config.get("share") or {}).get("port", DEFAULT_SHARE_PORT),
    }
    messages: list[dict] = []

    tools = f", {len(registry.tools)} outils MCP" if registry else ""
    print(f"Sensai CLI — modèle {client.model}{tools}. "
          f"Tape /help pour les commandes, 'exit' pour quitter.\n")

    try:
        while True:
            try:
                user_input = input("Toi : ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nÀ bientôt !")
                break

            if not user_input:
                print("[Info] Message vide, réessaie.\n")
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                print("À bientôt !")
                break

            # Slash commands are answered locally, never sent to the model
            if user_input.startswith("/"):
                output = commands(user_input, messages, ctx)
                if output:
                    print(output)
                print()
                continue

            verdict = guardrails.check_input(user_input)
            if not verdict.allowed:
                print(f"[Guardrail] {verdict.message} ({verdict.category})\n")
                continue
            if verdict.redacted:
                print(f"[Guardrail] masqué avant envoi au modèle : {', '.join(verdict.redacted)}")

            messages.append({"role": "user", "content": verdict.text})
            history_size = len(messages)

            print("Sensai : ", end="", flush=True)
            if registry is not None:
                response = chat_with_tools(client, messages, registry)
            else:
                response = client.chat(messages)

            if response is None:
                # Drop the question and any tool exchange left unanswered
                del messages[history_size - 1:]
                print("[Info] Réessaie ou vérifie qu'Ollama est lancé.\n")
                continue

            cleaned = guardrails.check_output(response)
            if cleaned.redacted:
                print(f"[Guardrail] la réponse contenait : {', '.join(cleaned.redacted)} "
                      f"(masqué dans l'historique et les exports)")
            messages.append({"role": "assistant", "content": cleaned.text})
            print()
    finally:
        # Lets a report being written finish instead of cutting the file
        stop_scheduled_reports()
        if registry is not None:
            registry.close()


if __name__ == "__main__":
    main()
