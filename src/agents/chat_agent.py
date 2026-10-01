from src.core.ollama_client import OllamaClient, load_config
from src.core.prompts import load_prompt
from src.tools.twitch_chat import connect, messages
from src.core.memory import (
    init_memory,
    load_facts,
    load_history,
    load_summary,
    remember_viewer,
    save_fact,
    save_message,
    save_summary,
)

KEEP_RECENT_MESSAGES = 4
NOTHING = "(none)"


class ViewerState:
    def __init__(self, history, facts, summary, display_name):
        self.history = history
        self.facts = facts
        self.summary = summary
        self.display_name = display_name


def load_viewer(db_connection, viewer_id, display_name):
    return ViewerState(
        history=load_history(db_connection, viewer_id),
        facts=load_facts(db_connection, viewer_id),
        summary=load_summary(db_connection, viewer_id),
        display_name=display_name,
    )


def match_trigger(text, trigger):
    lowered = text.lower()
    position = lowered.find(trigger.lower())
    if position == -1:
        return None
    cleaned = text[:position] + text[position + len(trigger):]
    return " ".join(cleaned.split())


def parse_remember_command(question, commands):
    for command in commands:
        if question.lower().startswith(command.lower()):
            fact = question[len(command):].strip()
            if fact:
                return fact
    return None


def build_prompt(state, template):
    if not state.facts and not state.summary:
        return state.history

    facts = "\n".join(f"- {fact}" for fact in state.facts) or NOTHING
    system = template.format(facts=facts, summary=state.summary or NOTHING)
    return [{"role": "system", "content": system}] + state.history


def summarize(client, rules, previous_summary, old_messages):
    lines = []
    for message in old_messages:
        speaker = "Viewer" if message["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {message['content']}")

    request = ""
    if previous_summary:
        request += f"Previous summary:\n{previous_summary}\n\n"
    request += "Exchanges to summarize:\n" + "\n".join(lines)

    summary = client.chat_silent(
        [
            {"role": "system", "content": rules},
            {"role": "user", "content": request},
        ],
        temperature=0,
    )
    return summary.strip() if summary else None


def compress(client, rules, db_connection, viewer_id, state):
    if len(state.history) <= KEEP_RECENT_MESSAGES:
        return 0

    old_messages = state.history[:-KEEP_RECENT_MESSAGES]
    summary = summarize(client, rules, state.summary, old_messages)
    if summary is None:
        return 0

    state.summary = summary
    state.history = state.history[-KEEP_RECENT_MESSAGES:]
    save_summary(db_connection, viewer_id, summary, len(old_messages))
    return len(old_messages)


def remember(db_connection, viewer_id, state, fact):
    save_fact(db_connection, viewer_id, fact)
    state.facts.append(fact)


def answer(client, db_connection, viewer_id, state, question, template):
    state.history.append({"role": "user", "content": question})

    print(f"Sensai : @{state.display_name} ", end="", flush=True)
    reply = client.chat(build_prompt(state, template))
    print()

    if reply is None:
        state.history.pop()
        return None

    state.history.append({"role": "assistant", "content": reply})
    save_message(db_connection, viewer_id, "user", question)
    save_message(db_connection, viewer_id, "assistant", reply)
    return reply


def main():
    config = load_config()
    channel = config["twitch_channel"]
    trigger = config["twitch_trigger"]
    remember_commands = config["twitch_remember_commands"]
    ack_message = config["twitch_ack_message"]
    token_budget = config["history_token_budget"]

    context_template = load_prompt("viewer_context")
    summary_rules = load_prompt("summarize")

    client = OllamaClient(config)
    db_connection = init_memory()
    sock = connect(channel)
    viewers = {}

    print(f"Listening on #{channel}, trigger \"{trigger}\". Ctrl+C to quit.\n")

    try:
        for message in messages(sock):
            question = match_trigger(message["text"], trigger)
            if question is None:
                continue

            viewer_id = message["user_id"]
            if viewer_id not in viewers:
                remember_viewer(
                    db_connection,
                    viewer_id,
                    message["author"],
                    message["display_name"],
                )
                viewers[viewer_id] = load_viewer(
                    db_connection, viewer_id, message["display_name"]
                )
            state = viewers[viewer_id]

            print(f"{state.display_name} : {question}")

            fact = parse_remember_command(question, remember_commands)
            if fact is not None:
                remember(db_connection, viewer_id, state, fact)
                print(f"Sensai : @{state.display_name} {ack_message}")
                continue

            reply = answer(
                client, db_connection, viewer_id, state, question, context_template
            )
            if reply is None:
                continue

            used = client.last_prompt_tokens
            print(f"[tokens] {used}/{token_budget}")

            if used is not None and used > token_budget:
                compressed = compress(
                    client, summary_rules, db_connection, viewer_id, state
                )
                if compressed:
                    print(f"[compress] {compressed} messages summarized")
    finally:
        sock.close()
        db_connection.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
