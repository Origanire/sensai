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


class ViewerState:
    def __init__(self, history, facts, summary=None):
        self.history = history
        self.facts = facts
        self.summary = summary


def load_viewer(db_connection, viewer):
    return ViewerState(
        history=load_history(db_connection, viewer),
        facts=load_facts(db_connection, viewer),
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


def build_prompt(state):
    blocks = []

    if state.facts:
        known = "\n".join(f"- {fact}" for fact in state.facts)
        blocks.append(f"Voici ce que tu sais déjà sur ce viewer :\n{known}")

    if state.summary:
        blocks.append(f"Résumé des échanges précédents :\n{state.summary}")

    if not blocks:
        return state.history

    system = "\n\n".join(blocks) + (
        "\n\nUtilise ces informations si elles sont pertinentes, "
        "sans les répéter inutilement."
    )
    return [{"role": "system", "content": system}] + state.history


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


def compress(client, state):
    if len(state.history) <= KEEP_RECENT_MESSAGES:
        return 0

    old_messages = state.history[:-KEEP_RECENT_MESSAGES]
    summary = summarize(client, state.summary, old_messages)
    if summary is None:
        return 0

    state.summary = summary
    state.history = state.history[-KEEP_RECENT_MESSAGES:]
    return len(old_messages)


def remember(db_connection, viewer, state, fact):
    save_fact(db_connection, viewer, fact)
    state.facts.append(fact)


def answer(client, db_connection, viewer, state, question):
    state.history.append({"role": "user", "content": question})

    print(f"Sensai : @{viewer} ", end="", flush=True)
    reply = client.chat(build_prompt(state))
    print()

    if reply is None:
        state.history.pop()
        return None

    state.history.append({"role": "assistant", "content": reply})
    save_message(db_connection, viewer, "user", question)
    save_message(db_connection, viewer, "assistant", reply)
    return reply


def main():
    config = load_config()
    channel = config["twitch_channel"]
    trigger = config["twitch_trigger"]
    remember_command = config["twitch_remember_command"]
    token_budget = config["history_token_budget"]

    client = OllamaClient(config)
    db_connection = init_memory()
    sock = connect(channel)
    viewers = {}

    print(f"En écoute sur #{channel}, déclencheur « {trigger} ». Ctrl+C pour quitter.\n")

    try:
        for message in messages(sock):
            question = match_trigger(message["text"], trigger)
            if question is None:
                continue

            viewer = message["author"]
            if viewer not in viewers:
                viewers[viewer] = load_viewer(db_connection, viewer)
            state = viewers[viewer]

            print(f"{viewer} : {question}")

            fact = parse_remember_command(question, remember_command)
            if fact is not None:
                remember(db_connection, viewer, state, fact)
                print(f"Sensai : @{viewer} c'est noté.")
                continue

            if answer(client, db_connection, viewer, state, question) is None:
                continue

            used = client.last_prompt_tokens
            print(f"[tokens] {used}/{token_budget}")

            if used is not None and used > token_budget:
                compressed = compress(client, state)
                if compressed:
                    print(f"[compression] {compressed} messages résumés")
    finally:
        sock.close()
        db_connection.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
