## @file cli.py
# @brief Sensai CLI chatbot: interactive conversation loop with Ollama.

from src.core.ollama_client import OllamaClient
from src.commands import commands
from src.tools.scheduled_reports import stop_scheduled_reports

## @brief Entry point of the Sensai CLI chatbot.
#
# Interactive read loop: reads user input, sends the full conversation
# history to the model via Ollama and streams the response. The history
# is kept in memory for the whole session.
def main():
    client = OllamaClient()
    messages: list[dict[str, str]] = []

    print("Sensai CLI — tape 'exit' ou 'quit' pour quitter.\n")

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

        # Slash Commands
        if user_input.startswith("/"):
            system_message = commands(user_input, messages)
            print(system_message)

            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "system", "content": system_message})
            continue # Continue is here to avoid sending commands to the model

        messages.append({"role": "user", "content": user_input})

        print("Sensai : ", end="", flush=True)
        response = client.chat(messages)

        if response is None:
            messages.pop()
            print("[Info] Réessaie ou vérifie qu'Ollama est lancé.\n")
            continue

        messages.append({"role": "assistant", "content": response})

    # Lets a report being written finish instead of cutting the file
    stop_scheduled_reports()


if __name__ == "__main__":
    main()
