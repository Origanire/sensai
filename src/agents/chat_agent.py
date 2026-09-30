from src.core.ollama_client import load_config


def match_trigger(text, trigger):
    lowered = text.lower()
    position = lowered.find(trigger.lower())
    if position == -1:
        return None
    cleaned = text[:position] + text[position + len(trigger):]
    return " ".join(cleaned.split())


if __name__ == "__main__":
    trigger = load_config()["twitch_trigger"]

    tests = [
        "@sensai c'est quoi ce jeu ?",
        "hey @sensai ça va ?",
        "@SENSAI salut",
        "@sensai",
        "salut tout le monde",
        "sensai est cool",
    ]

    for text in tests:
        print(f"{text!r:32} -> {match_trigger(text, trigger)!r}")
