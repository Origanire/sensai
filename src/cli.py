from src.core.ollama_client import OllamaClient


def main():
    client = OllamaClient()
    messages = []

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

        messages.append({"role": "user", "content": user_input})

        print("Sensai : ", end="", flush=True)
        response = client.chat(messages)

        if response is None:
            messages.pop()
            print("[Info] Réessaie ou vérifie qu'Ollama est lancé.\n")
            continue

        messages.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
