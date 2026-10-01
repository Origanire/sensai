from src.core.ollama_client import OllamaClient, load_config
from src.tools.twitch_chat import connect, messages
from src.core.memory import (
    init_memory,
    load_facts,
    load_history,
    save_fact,
    save_message,
)

KEEP_RECENT_MESSAGES = 4

SUMMARY_RULES = (
    "Tu résumes une conversation entre un assistant de stream et un viewer.\n"
    "Condense les échanges en un paragraphe court.\n"
    "Garde ce qui sera utile pour la suite : ce que le viewer a demandé, "
    "ce qui lui a été répondu, les préférences qu'il a exprimées.\n"
    "Écris à la troisième personne, ne pose aucune question, n'invente rien.\n"
    "Si un résumé précédent est fourni, intègre-le au nouveau."
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


def build_prompt(facts, summary, history):
    blocks = []

    if facts:
        known = "\n".join(f"- {fact}" for fact in facts)
        blocks.append(f"Voici ce que tu sais déjà sur ce viewer :\n{known}")

    if summary:
        blocks.append(f"Résumé des échanges précédents :\n{summary}")

    if not blocks:
        return history

    system = "\n\n".join(blocks) + (
        "\n\nUtilise ces informations si elles sont pertinentes, "
        "sans les répéter inutilement."
    )
    return [{"role": "system", "content": system}] + history


def summarize(client, previous_summary, old_messages):
    lines = []
    for message in old_messages:
        speaker = "Viewer" if message["role"] == "user" else "Assistant"
        lines.append(f"{speaker} : {message['content']}")

    request = ""
    if previous_summary:
        request += f"Résumé précédent :\n{previous_summary}\n\n"
    request += "Échanges à résumer :\n" + "\n".join(lines)

    summary = client.chat_silent(
        [
            {"role": "system", "content": SUMMARY_RULES},
            {"role": "user", "content": request},
        ],
        temperature=0,
    )
    return summary.strip() if summary else None


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
    summaries = {}

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
                summaries[author] = None
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
            answer = client.chat(
                build_prompt(profiles[author], summaries[author], history)
            )
            print()

            if answer is None:
                history.pop()
                continue

            used = client.last_prompt_tokens
            print(f"[tokens] {used}/{token_budget}")

            history.append({"role": "assistant", "content": answer})
            save_message(db_connection, author, "user", question)
            save_message(db_connection, author, "assistant", answer)

            if used is not None and used > token_budget:
                if len(history) > KEEP_RECENT_MESSAGES:
                    old_messages = history[:-KEEP_RECENT_MESSAGES]
                    new_summary = summarize(
                        client, summaries[author], old_messages
                    )
                    if new_summary is not None:
                        summaries[author] = new_summary
                        histories[author] = history[-KEEP_RECENT_MESSAGES:]
                        print(f"[compression] {len(old_messages)} messages résumés")
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        db_connection.close()
