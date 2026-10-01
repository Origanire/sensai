import time

from src.core.ollama_client import OllamaClient, load_config
from src.core.prompts import load_prompt
from src.tools.twitch_chat import connect, messages
from src.core.memory import (
    init_memory,
    load_facts,
    load_history,
    find_viewer_id,
    load_stats,
    load_summary,
    add_activity,
    remember_viewer,
    save_fact,
    save_message,
    save_summary,
)

AGENT_CONFIG = "config/chat_agent.yaml"
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


def track_activity(activity, viewer_id, seen_at):
    session = activity.get(viewer_id)
    if session is None:
        session = {"first": seen_at, "last": seen_at, "messages": 0}
        activity[viewer_id] = session

    session["last"] = max(session["last"], seen_at)
    session["messages"] += 1
    return session


def flush_activity(db_connection, activity):
    for viewer_id, session in activity.items():
        add_activity(
            db_connection,
            viewer_id,
            session["first"],
            session["last"],
            session["messages"],
        )
    activity.clear()


def message_time(message):
    sent_at = message.get("sent_at")
    if sent_at and sent_at.isdigit():
        return int(sent_at) // 1000
    return int(time.time())


def format_duration(seconds):
    hours, rest = divmod(int(seconds), 3600)
    minutes = rest // 60
    if hours:
        return f"{hours}h{minutes:02d}"
    return f"{minutes}min"


def parse_command(text, prefix):
    if not text.startswith(prefix):
        return None

    name, _, arguments = text[len(prefix):].partition(" ")
    if not name:
        return None
    return name.lower(), arguments.strip()


def remember_about(db_connection, viewers, arguments):
    target, _, fact = arguments.partition(" ")
    target = target.lstrip("@")
    fact = fact.strip()
    if not target or not fact:
        return None

    viewer_id = find_viewer_id(db_connection, target)
    if viewer_id is None:
        return None

    save_fact(db_connection, viewer_id, fact)
    if viewer_id in viewers:
        viewers[viewer_id].facts.append(fact)
    return target


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
    agent_config = load_config(AGENT_CONFIG)

    channel = agent_config["channel"]
    trigger = agent_config["trigger"]
    command_prefix = agent_config["command_prefix"]
    remember_command = agent_config["remember_command"]
    fact_saved_message = agent_config["fact_saved_message"]
    viewer_not_found_message = agent_config["viewer_not_found_message"]
    token_budget = agent_config["history_token_budget"]

    context_template = load_prompt("viewer_context")
    summary_rules = load_prompt("summarize")

    client = OllamaClient(config)
    db_connection = init_memory()
    sock = connect(channel)
    viewers = {}
    activity = {}

    print(f"Listening on #{channel}, trigger \"{trigger}\". Ctrl+C to quit.\n")

    try:
        for message in messages(sock):
            viewer_id = message["user_id"]
            if viewer_id not in activity:
                remember_viewer(
                    db_connection,
                    viewer_id,
                    message["author"],
                    message["display_name"],
                )
            session = track_activity(
                activity, viewer_id, message_time(message)
            )

            command = parse_command(message["text"], command_prefix)
            if command is not None:
                name, arguments = command
                if name == remember_command and message["is_moderator"]:
                    author = message["display_name"]
                    target = remember_about(db_connection, viewers, arguments)
                    if target is None:
                        print(f"Sensai : @{author} {viewer_not_found_message}")
                    else:
                        print(f"Sensai : @{author} {fact_saved_message}")
                continue

            question = match_trigger(message["text"], trigger)
            if question is None:
                continue

            if viewer_id not in viewers:
                viewers[viewer_id] = load_viewer(
                    db_connection, viewer_id, message["display_name"]
                )
            state = viewers[viewer_id]

            print(f"{state.display_name} : {question}")
            total = load_stats(db_connection, viewer_id)
            print(
                f"[viewer] {total['visits']} past visits, "
                f"{session['messages']} messages tonight, "
                f"{format_duration(session['last'] - session['first'])} active"
            )

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
        flush_activity(db_connection, activity)
        sock.close()
        db_connection.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
