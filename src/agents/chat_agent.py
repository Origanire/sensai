from src.core.memory import init_memory, load_history, save_message
from src.core.ollama_client import OllamaClient, load_config
from src.tools.twitch_chat import connect, messages


def match_trigger(text, trigger):
    lowered = text.lower()
    position = lowered.find(trigger.lower())
    if position == -1:
        return None
    cleaned = text[:position] + text[position + len(trigger):]
    return " ".join(cleaned.split())


if __name__ == "__main__":
    config = load_config()
    channel = config["twitch_channel"]
    trigger = config["twitch_trigger"]

    client = OllamaClient(config)
    db_connection = init_memory()
    sock = connect(channel)
    histories = {}

    print(f"En écoute sur #{channel}, déclencheur « {trigger} ». Ctrl+C pour quitter.\n")

    try:
        for message in messages(sock):
            question = match_trigger(message["text"], trigger)
            if question is None:
                continue

            author = message["author"]
            if author not in histories:
                histories[author] = load_history(db_connection, author)
            history = histories[author]

            history.append({"role": "user", "content": question})

            print(f"{author} : {question}")
            print(f"Sensai : @{author} ", end="", flush=True)
            answer = client.chat(history)
            print()

            if answer is None:
                history.pop()
                continue

            history.append({"role": "assistant", "content": answer})
            save_message(db_connection, author, "user", question)
            save_message(db_connection, author, "assistant", answer)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        db_connection.close()
