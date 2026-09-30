from src.core.ollama_client import load_config
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

    sock = connect(channel)
    print(f"En écoute sur #{channel}, déclencheur « {trigger} ». Ctrl+C pour quitter.\n")

    try:
        for message in messages(sock):
            question = match_trigger(message["text"], trigger)
            if question is None:
                continue
            print(f"{message['author']} appelle Sensai : {question!r}")
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
