## @file chat_agent.py
# @brief Twitch chat agent: replies to viewers who mention Sensai, relying
# on their history and profile, and forwards !search to the Internet agent.

import os
import re
import textwrap
import time

from dotenv import load_dotenv

from src.core.ollama_client import OllamaClient, load_config
from src.core.prompts import load_prompt
from src.tools.twitch_chat import (
    MAX_MESSAGE_LENGTH,
    connect,
    messages,
    send_message,
)
from src.tools.report import add_moment
from src.tools.web_search import (
    SEARCH_UNAVAILABLE,
    ask_internet,
    get_quick_fact,
    load_internet_settings,
)
from src.tools.obs import load_obs_settings, obs_reachable, update_text_source
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

## @brief Configuration file specific to this agent.
AGENT_CONFIG = "config/chat_agent.yaml"
## @brief Number of messages kept as-is during a compression;
# anything older goes into the summary.
KEEP_RECENT_MESSAGES = 4
## @brief Value shown in the prompt when a section is empty.
NOTHING = "(none)"
## @brief Web addresses in a text, without the punctuation that may follow.
URL_PATTERN = re.compile(r"https?://[^\s)\]>]+")


## @brief Output of Sensai's replies.
#
# Every reply is printed in the terminal. When the agent is logged in with
# a bot account, it is also sent to the Twitch chat; anonymous, the agent
# stays read-only, as before.
class ChatOutput:
    ## @brief Build the output.
    #
    # @param sock Socket opened by connect().
    # @param channel Name of the channel, without the "#".
    # @param writable True if the socket is logged in with a bot account.
    def __init__(self, sock, channel, writable):
        ## @brief Socket of the chat connection.
        self.sock = sock
        ## @brief Name of the channel.
        self.channel = channel
        ## @brief True if messages can be sent to the chat.
        self.writable = writable

    ## @brief Send a reply to the chat only, without printing it.
    #
    # A sending error is printed and never interrupts the agent.
    #
    # @param text Reply to send.
    def post(self, text):
        if not self.writable:
            return
        try:
            send_message(self.sock, self.channel, text)
        except OSError as error:
            print(f"[chat] envoi impossible : {error}")

    ## @brief Print a reply in the terminal and send it to the chat.
    #
    # @param text Reply to display.
    def say(self, text):
        print(f"Sensai : {text}")
        self.post(text)


## @brief In-memory state of a viewer during the session.
class ViewerState:
    ## @brief Build the viewer's state.
    #
    # @param history Active messages, in "role"/"content" format.
    # @param facts Known facts about this viewer.
    # @param summary Summary of older exchanges, or None.
    # @param display_name Name as displayed in the chat.
    def __init__(self, history, facts, summary, display_name):
        ## @brief Active messages, sent as-is to the model.
        self.history = history
        ## @brief Known facts about this viewer.
        self.facts = facts
        ## @brief Summary of older exchanges, or None.
        self.summary = summary
        ## @brief Name as displayed in the chat.
        self.display_name = display_name


## @brief Load from the database everything Sensai knows about a viewer.
#
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @param display_name Name as displayed in the chat.
# @return A ViewerState instance.
def load_viewer(db_connection, viewer_id, display_name):
    return ViewerState(
        history=load_history(db_connection, viewer_id),
        facts=load_facts(db_connection, viewer_id),
        summary=load_summary(db_connection, viewer_id),
        display_name=display_name,
    )


## @brief Detect whether a message is addressed to Sensai and strip the mention.
#
# @param text Text of the message.
# @param trigger Expected mention, e.g. "@sensai".
# @return Message stripped of the mention, or None if it is not addressed
#         to Sensai. An empty string means a mention without a question.
def match_trigger(text, trigger):
    lowered = text.lower()
    position = lowered.find(trigger.lower())
    if position == -1:
        return None
    cleaned = text[:position] + text[position + len(trigger):]
    return " ".join(cleaned.split())


## @brief Update a viewer's counters for the current session.
#
# Everything stays in memory: no disk writes during the stream.
#
# @param activity Dictionary of live sessions, modified in place.
# @param viewer_id Twitch identifier of the viewer.
# @param seen_at Timestamp of the message, in seconds.
# @return The viewer's session: "first", "last", "messages".
def track_activity(activity, viewer_id, seen_at):
    session = activity.get(viewer_id)
    if session is None:
        session = {"first": seen_at, "last": seen_at, "messages": 0}
        activity[viewer_id] = session

    session["last"] = max(session["last"], seen_at)
    session["messages"] += 1
    return session


## @brief Write the session activity to the database and clear the memory.
#
# Called only once, when the agent shuts down. A brutal kill (kill -9,
# power loss) therefore loses the statistics of the ongoing stream.
#
# @param db_connection Open SQLite connection.
# @param activity Dictionary of sessions, cleared after writing.
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


## @brief Timestamp of a message, in seconds.
#
# Uses the send time provided by Twitch, so the statistics stay accurate
# even if the agent falls behind.
#
# @param message Message produced by the connector.
# @return Timestamp in seconds, local time as fallback.
def message_time(message):
    sent_at = message.get("sent_at")
    if sent_at and sent_at.isdigit():
        return int(sent_at) // 1000
    return int(time.time())


## @brief Format a duration for display.
#
# @param seconds Duration in seconds.
# @return A string like "2h05" or "42min".
def format_duration(seconds):
    hours, rest = divmod(int(seconds), 3600)
    minutes = rest // 60
    if hours:
        return f"{hours}h{minutes:02d}"
    return f"{minutes}min"


## @brief Recognize a prefixed command.
#
# @param text Text of the message.
# @param prefix Command prefix, e.g. "!".
# @return A (lowercase name, arguments) pair, or None if it is not
#         a command.
def parse_command(text, prefix):
    if not text.startswith(prefix):
        return None

    name, _, arguments = text[len(prefix):].partition(" ")
    if not name:
        return None
    return name.lower(), arguments.strip()


## @brief Store a fact about a viewer designated by name.
#
# Reserved for the streamer and moderators; permission checking is done
# by the caller.
#
# @param db_connection Open SQLite connection.
# @param viewers Loaded viewer states, updated if the target viewer is in it.
# @param arguments Command arguments: the target name, then the fact.
# @return Target name if the fact was saved; None if the arguments are
#         incomplete or the viewer has never written.
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


## @brief Compose the prompt sent to the model for a viewer.
#
# The profile and summary are recomputed at every call into a fresh
# "system" message: they are never added to the history, which would
# otherwise be polluted and persisted with them.
#
# @param state Viewer state.
# @param template Template loaded from prompts/viewer_context.txt.
# @return A message list ready for Ollama.
def build_prompt(state, template):
    if not state.facts and not state.summary:
        return state.history

    facts = "\n".join(f"- {fact}" for fact in state.facts) or NOTHING
    system = template.format(facts=facts, summary=state.summary or NOTHING)
    return [{"role": "system", "content": system}] + state.history


## @brief Condense old exchanges into a summary.
#
# @param client Ollama client.
# @param rules Instructions loaded from prompts/summarize.txt.
# @param previous_summary Existing summary, or None.
# @param old_messages Messages to condense.
# @return Summary text, or None if the model failed.
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


## @brief Summarize the oldest messages and remove them from the history.
#
# @param client Ollama client.
# @param rules Summary instructions.
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @param state Viewer state, modified in place.
# @return Number of messages summarized, 0 if nothing was done.
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


## @brief Fit a web answer into a chat message without losing its source.
#
# Cutting the end of a long answer would drop the URLs, usually written
# last. When the answer is too long, its first URL is put back after the
# truncated text.
#
# @param answer Answer from ask_internet().
# @param limit Maximum length, in characters.
# @return Text of at most limit characters.
def format_search_reply(answer, limit):
    text = " ".join(answer.replace("**", "").split())
    if len(text) <= limit:
        return text

    urls = URL_PATTERN.findall(text)
    if not urls:
        return textwrap.shorten(text, limit, placeholder="...")

    source = urls[0].rstrip(".,;:")
    body = textwrap.shorten(text, limit - len(source) - 1, placeholder="...")
    return f"{body} {source}"


## @brief Answer a !search: Chat -> Internet agent -> chat and OBS overlay.
#
# The overlay is updated on each !search rather than on a separate timer:
# a viewer types a question and the answer shows up in the chat then on
# screen, which can be demonstrated live. The short fact for the overlay
# is only computed when OBS answers, since it costs a second web search
# and a model call.
#
# @param question Question typed after !search.
# @param author Display name of the viewer.
# @param client Ollama client.
# @param chat ChatOutput.
# @param internet_settings Settings from load_internet_settings().
# @param obs_settings Settings from load_obs_settings().
def search_and_share(question, author, client, chat, internet_settings, obs_settings):
    print(f"[search] {author} : {question}")
    result = ask_internet(question, client, internet_settings["max_results"])

    prefix = f"@{author} "
    chat.say(prefix + format_search_reply(result, MAX_MESSAGE_LENGTH - len(prefix)))

    if result == SEARCH_UNAVAILABLE or not obs_settings["enabled"]:
        return
    if not obs_reachable(obs_settings["host"], obs_settings["port"]):
        print(f"[OBS] injoignable sur {obs_settings['host']}:{obs_settings['port']}, "
              f"overlay non mis à jour.")
        return

    fact = get_quick_fact(question, client)
    if fact == SEARCH_UNAVAILABLE:
        return
    if update_text_source(
        obs_settings["source_name"],
        fact,
        obs_settings["host"],
        obs_settings["port"],
        obs_settings["password"],
    ):
        print(f"[OBS] {obs_settings['source_name']} <- {fact}")


## @brief Make Sensai reply to a viewer and record the exchange.
#
# If the model fails, the question is removed from the history so no
# unanswered turn is left in it.
#
# @param client Ollama client.
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @param state Viewer state, modified in place.
# @param question Viewer's message, without the mention.
# @param template Context template.
# @return The model's reply, or None on failure.
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


## @brief Entry point of the chat agent.
#
# Loops over chat messages: tracks everyone's activity, runs commands,
# and replies to those who mention Sensai. No content is recorded for
# messages not addressed to it.
#
# The bot account is read from TWITCH_BOT_USERNAME and TWITCH_OAUTH_TOKEN
# (environment or .env); without them, the agent reads the chat
# anonymously and its replies only appear in the terminal.
def main():
    load_dotenv()
    config = load_config()
    agent_config = load_config(AGENT_CONFIG)
    internet_settings = load_internet_settings(config)
    obs_settings = load_obs_settings(config)

    channel = agent_config["channel"]
    trigger = agent_config["trigger"]
    command_prefix = agent_config["command_prefix"]
    remember_command = agent_config["remember_command"]
    fact_saved_message = agent_config["fact_saved_message"]
    viewer_not_found_message = agent_config["viewer_not_found_message"]
    moment_command = agent_config["moment_command"]
    moment_saved_message = agent_config["moment_saved_message"]
    moment_usage_message = agent_config["moment_usage_message"]
    search_command = agent_config["search_command"]
    search_usage_message = agent_config["search_usage_message"]
    token_budget = agent_config["history_token_budget"]

    context_template = load_prompt("viewer_context")
    summary_rules = load_prompt("summarize")

    client = OllamaClient(config)
    db_connection = init_memory()
    bot_username = os.environ.get("TWITCH_BOT_USERNAME")
    bot_token = os.environ.get("TWITCH_OAUTH_TOKEN")
    sock = connect(channel, bot_username, bot_token)
    chat = ChatOutput(sock, channel, writable=bool(bot_username and bot_token))
    viewers = {}
    activity = {}
    last_search = None

    mode = f"as {bot_username}" if chat.writable else "anonymously (read-only)"
    print(f"Listening on #{channel} {mode}, trigger \"{trigger}\". Ctrl+C to quit.\n")

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
            sent_at = message_time(message)
            session = track_activity(activity, viewer_id, sent_at)

            command = parse_command(message["text"], command_prefix)
            if command is not None:
                name, arguments = command
                author = message["display_name"]
                try:
                    if name == remember_command and message["is_moderator"]:
                        target = remember_about(db_connection, viewers, arguments)
                        if target is None:
                            chat.say(f"@{author} {viewer_not_found_message}")
                        else:
                            chat.say(f"@{author} {fact_saved_message}")
                    elif name == moment_command and message["is_moderator"]:
                        if not arguments:
                            chat.say(f"@{author} {moment_usage_message}")
                        else:
                            line = add_moment(arguments, sent_at)
                            print(f"[moment] {line}")
                            chat.say(f"@{author} {moment_saved_message}")
                    elif name == search_command:
                        # Global cooldown: a search blocks the loop for several
                        # seconds, a per-viewer limit would not protect it
                        cooldown = internet_settings["cooldown_seconds"]
                        if not arguments:
                            chat.say(f"@{author} {search_usage_message}")
                        elif last_search is not None and sent_at - last_search < cooldown:
                            print(f"[search] {author} ignoré (cooldown)")
                        else:
                            last_search = sent_at
                            search_and_share(
                                arguments, author, client, chat,
                                internet_settings, obs_settings,
                            )
                except Exception as error:
                    print(f"[command] {name} a échoué : {error}")
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
            chat.post(f"@{state.display_name} {reply}")

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
