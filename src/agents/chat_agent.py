from src.core.ollama_client import OllamaClient, load_config
from src.tools.twitch_chat import connect, messages
from src.core.memory import (
    init_memory,
    load_facts,
    load_history,
    save_fact,
    save_message,
)


def match_trigger(text, trigger):
    lowered = text.lower()
    position = lowered.find(trigger.lower())
    if position == -1:
        return None
    cleaned = text[:position] + text[position + len(trigger):]
    return " ".join(cleaned.split())


def parse_remember_command(question, command):
    if not question.lower().startswith(command.lower()):
        return None
    fact = question[len(command):].strip()
    if fact.lower().startswith("que "):
        fact = fact[4:].strip()
    return fact or None


def build_prompt(facts, history):
    if not facts:
        return history

    known = "\n".join(f"- {fact}" for fact in facts)
    system = (
        "Voici ce que tu sais déjà sur ce viewer :\n"
        f"{known}\n"
        "Utilise ces informations si elles sont pertinentes, "
        "sans les répéter inutilement."
    )
    return [{"role": "system", "content": system}] + history


if __name__ == "__main__":
    config = load_config()
    channel = config["twitch_channel"]
    trigger = config["twitch_trigger"]
    remember_command = config["twitch_remember_command"]
    token_budget = config["history_token_budget"]

    client = OllamaClient(config)
    db_connection = init_memory()
    sock = connect(channel)
    histories = {}
    profiles = {}

    print(f"En écoute sur #{channel}, déclencheur « {trigger} ». Ctrl+C pour quitter.\n")

    try:
        for message in messages(sock):
            question = match_trigger(message["text"], trigger)
            if question is None:
                continue

            author = message["author"]
            if author not in histories:
                histories[author] = load_history(db_connection, author)
                profiles[author] = load_facts(db_connection, author)
            history = histories[author]

            print(f"{author} : {question}")

            fact = parse_remember_command(question, remember_command)
            if fact is not None:
                save_fact(db_connection, author, fact)
                profiles[author].append(fact)
                print(f"Sensai : @{author} c'est noté.")
                continue

            history.append({"role": "user", "content": question})

            print(f"Sensai : @{author} ", end="", flush=True)
            answer = client.chat(build_prompt(profiles[author], history))
            print()

            if answer is None:
                history.pop()
                continue

            used = client.last_prompt_tokens
            print(f"[tokens] {used}/{token_budget}", end="")
            if used is not None and used > token_budget:
                print("  BUDGET DEPASSE")
            else:
                print()

            history.append({"role": "assistant", "content": answer})
            save_message(db_connection, author, "user", question)
            save_message(db_connection, author, "assistant", answer)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        db_connection.close()
