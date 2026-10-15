## @file chat_agent.py
# @brief Twitch chat agent: replies to viewers who mention Sensai, relying
# on their history and profile, and forwards !search to the Internet agent.
#
# Each mention goes through: input guardrails -> router -> one of three
# agents (conversation with memory, channel documents, Internet) -> output
# guardrails -> chat. With --local, the chat is simulated in the terminal.

import argparse
import os
import re
import sys
import textwrap
import time

from dotenv import load_dotenv

from src.core.ollama_client import OllamaClient, load_config
from src.core.prompts import load_prompt
from src.core.bot_settings import load_bot_settings, bot_persona
from src.core.bot_runtime import acquire_bot_lock, emit
from src.tools.twitch_chat import (
    MAX_MESSAGE_LENGTH,
    connect,
    messages,
    send_message,
)
from src.tools.report import add_moment, set_section, update_report_from_event
from src.tools.web_search import (
    SEARCH_UNAVAILABLE,
    ask_internet,
    get_quick_fact,
    load_internet_settings,
)
from src.tools.obs import load_obs_settings, obs_reachable, update_text_source
from src.tools.burst import BurstDetector
from src.agents.router import route
from src.core.guardrails import load_guardrails
from src.core.search import NO_DOCUMENT, ask_documents, load_rag_settings
from src.core.storage import init_db
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
## @brief Prompt shown in --local mode.
LOCAL_PROMPT = "chat> "


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
    def __init__(self, sock, channel, writable, cooldown=0):
        ## @brief Socket of the chat connection.
        self.sock = sock
        ## @brief Name of the channel.
        self.channel = channel
        ## @brief True if messages can be sent to the chat.
        self.writable = writable
        self.cooldown = cooldown
        self.last_post_at = None
        self.request_started = None

    def can_reply(self):
        return self.last_post_at is None or time.monotonic() - self.last_post_at >= self.cooldown

    ## @brief Send a reply to the chat only, without printing it.
    #
    # A sending error is printed and never interrupts the agent.
    #
    # @param text Reply to send.
    def post(self, text):
        if not self.writable or self.sock is None:
            return False
        if not self.can_reply():
            emit("cooldown")
            return False
        try:
            send_message(self.sock, self.channel, text)
            self.last_post_at = time.monotonic()
            elapsed = self.last_post_at - self.request_started if self.request_started is not None else None
            emit("reply", latency=round(elapsed, 3) if elapsed is not None else None)
            return True
        except OSError as error:
            emit("warning", message="Échec de l'envoi d'une réponse à Twitch.")
            print(f"[chat] envoi impossible : {error}")
            return False

    ## @brief Print a reply in the terminal and send it to the chat.
    #
    # @param text Reply to display.
    def say(self, text):
        print(f"Sensai : {text}")
        self.post(text)


## @brief Simulated chat read from the terminal (--local mode).
#
# Each line is "pseudo: message"; a line without "pseudo:" is sent as the
# streamer. The streamer (the channel's name) has the moderator rights.
# Produces the same dictionaries as twitch_chat.messages(), so the whole
# agent can be tested and demonstrated without Twitch.
#
# @param channel Name of the channel, which is also the streamer's login.
# @return Iterator over the simulated messages.
def local_messages(channel):
    print("Mode local : écris « pseudo: message » (sans pseudo = le streamer). "
          "Ctrl+D pour quitter.")
    while True:
        try:
            line = input(LOCAL_PROMPT).strip()
        except EOFError:
            return
        if not line:
            continue

        author, separator, text = line.partition(":")
        if not separator or " " in author.strip() or not author.strip():
            author, text = channel, line
        author, text = author.strip().lstrip("@"), text.strip()
        login = author.lower()
        yield {
            "author": login,
            "text": text,
            "user_id": f"local-{login}",
            "display_name": author,
            "is_moderator": login == channel.lower(),
            "sent_at": str(int(time.time() * 1000)),
        }


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
# The persona, profile and summary are recomputed at every call into a
# fresh "system" message: they are never added to the history, which would
# otherwise be polluted and persisted with them.
#
# @param state Viewer state.
# @param template Template loaded from prompts/viewer_context.txt.
# @param persona Instructions loaded from prompts/persona.txt.
# @return A message list ready for Ollama.
def build_prompt(state, template, persona=""):
    system = persona
    if state.facts or state.summary:
        facts = "\n".join(f"- {fact}" for fact in state.facts) or NOTHING
        system += "\n\n" + template.format(facts=facts, summary=state.summary or NOTHING)
    if not system.strip():
        return state.history
    return [{"role": "system", "content": system.strip()}] + state.history


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
    if len(source) > limit - 20:
        return textwrap.shorten("La source trouvée a une adresse trop longue pour le chat.", limit, placeholder="...")
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
# @param guardrails Guardrails applied to the question and the answers.
def search_and_share(question, author, client, chat, internet_settings, obs_settings,
                     guardrails):
    verdict = guardrails.check_input(question)
    if not verdict.allowed:
        print(f"[guardrail] !search refusé ({verdict.category})")
        chat.say(f"@{author} {verdict.message}")
        return
    question = verdict.text

    print(f"[search] {author} : {question}")
    result = guardrails.check_output(
        ask_internet(question, client, internet_settings["max_results"])
    ).text

    prefix = f"@{author} "
    chat.say(prefix + format_search_reply(result, MAX_MESSAGE_LENGTH - len(prefix)))

    if result == SEARCH_UNAVAILABLE or not obs_settings["enabled"]:
        return
    if not obs_reachable(obs_settings["host"], obs_settings["port"]):
        print(f"[OBS] injoignable sur {obs_settings['host']}:{obs_settings['port']}, "
              f"overlay non mis à jour.")
        return

    fact = guardrails.check_output(get_quick_fact(question, client)).text
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


## @brief Conversation agent: reply with the viewer's memory, streamed.
#
# The question is only kept in the history for the call: the exchange is
# recorded afterwards by record(), once the reply has gone through the
# output guardrails.
#
# @param client Ollama client.
# @param state Viewer state.
# @param question Viewer's message, without the mention.
# @param template Context template.
# @param persona Persona instructions.
# @return The model's reply, or None on failure.
def answer(client, state, question, template, persona=""):
    state.history.append({"role": "user", "content": question})
    print(f"Sensai : @{state.display_name} ", end="", flush=True)
    try:
        reply = client.chat(build_prompt(state, template, persona))
    finally:
        state.history.pop()
    print()
    return reply


## @brief Add an exchange to a viewer's history, in memory and on disk.
#
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @param state Viewer state, modified in place.
# @param question Viewer's message (personal data already masked).
# @param reply Sensai's reply (already cleaned).
def record(db_connection, viewer_id, state, question, reply):
    state.history.append({"role": "user", "content": question})
    state.history.append({"role": "assistant", "content": reply})
    save_message(db_connection, viewer_id, "user", question)
    save_message(db_connection, viewer_id, "assistant", reply)


## @brief Orchestrate the reply to a mention (A2 + EV2).
#
# input guardrails -> router -> specialized agent -> output guardrails.
# A refused message gets the rule's short answer and never reaches the
# model. When the documents agent finds nothing relevant, the
# conversation agent answers instead.
#
# @param ctx Dictionary of the agent's shared objects (client, databases,
#            guardrails, settings, counters).
# @param viewer_id Twitch identifier of the viewer.
# @param state Viewer state.
# @param question Viewer's message, without the mention.
# @return The reply posted, or None if nothing was posted.
def respond(ctx, viewer_id, state, question):
    stats = ctx["stats"]
    ctx["last_route"] = None
    verdict = ctx["guardrails"].check_input(question)
    if not verdict.allowed:
        stats["blocked"] += 1
        print(f"[guardrail] message refusé ({verdict.category})")
        print(f"Sensai : @{state.display_name} {verdict.message}")
        return verdict.message
    if verdict.redacted:
        print(f"[guardrail] données masquées en entrée : {', '.join(verdict.redacted)}")
    question = verdict.text

    choice = route(question, ctx["client"])
    print(f"[router] -> {choice}")

    reply = None
    if choice == "docs":
        reply = ask_documents(question, ctx["client"], ctx["chunks"], ctx["rag"])
        if reply == NO_DOCUMENT:
            print("[router] rien dans les documents, l'agent conversation prend le relais")
            choice, reply = "chat", None
        else:
            print(f"Sensai : @{state.display_name} {reply}")
    elif choice == "web":
        emit("research", stage="started")
        reply = ask_internet(question, ctx["client"], ctx["internet"]["max_results"], persona=ctx["persona"])
        reply = format_search_reply(reply, MAX_MESSAGE_LENGTH - len(state.display_name) - 2)
        emit("research", stage="unavailable" if reply == SEARCH_UNAVAILABLE else "completed")
        print(f"Sensai : @{state.display_name} {reply}")

    if choice == "chat":
        reply = answer(ctx["client"], state, question, ctx["template"], ctx["persona"])
    if reply is None:
        return None

    stats["routes"][choice] += 1
    ctx["last_route"] = choice
    cleaned = ctx["guardrails"].check_output(reply)
    if cleaned.redacted:
        print(f"[guardrail] réponse nettoyée : {', '.join(cleaned.redacted)}")
    record(ctx["db"], viewer_id, state, question, cleaned.text)
    return cleaned.text


## @brief Write the session's figures in the stream report's stats section.
#
# Figures come from counters, not from the model: nothing to invent.
#
# @param activity Live sessions of the viewers.
# @param stats Counters of the agent (routes, blocked messages...).
def write_session_stats(activity, stats):
    if not activity:
        return
    messages_count = sum(session["messages"] for session in activity.values())
    routes = stats["routes"]
    set_section("stats", "\n".join([
        f"- {len(activity)} chatteurs, {messages_count} messages dans le chat",
        f"- {sum(routes.values())} réponses de Sensai "
        f"(conversation {routes['chat']}, documents {routes['docs']}, web {routes['web']})",
        f"- {stats['searches']} recherches !search, {stats['events']} événements notés",
        f"- {stats['blocked']} messages bloqués par les garde-fous",
    ]))


## @brief Entry point of the chat agent.
#
# Loops over chat messages: tracks everyone's activity, logs chat bursts
# as highlights, runs commands, and replies to those who mention Sensai.
# No content is recorded for messages not addressed to it.
#
# The bot account is read from TWITCH_BOT_USERNAME and TWITCH_OAUTH_TOKEN
# (environment or .env); without them, the agent reads the chat
# anonymously and its replies only appear in the terminal. With --local,
# no connection is made: the chat is typed in the terminal.
def run_agent():
    parser = argparse.ArgumentParser(description="Agent chat Twitch de Sensai.")
    parser.add_argument("--local", action="store_true",
                        help="simuler le chat dans le terminal, sans Twitch")
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    agent_config = load_bot_settings()
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
    event_command = agent_config.get("event_command", "event")
    event_usage_message = agent_config.get("event_usage_message", "usage : !event <description>")
    moment_cooldown = agent_config["moment_cooldown"]
    burst_description = agent_config["burst_description"]
    token_budget = agent_config["history_token_budget"]

    summary_rules = load_prompt("summarize")

    client = OllamaClient(config)
    problem = client.check_model()
    if problem:
        print(f"[Attention] {problem}")
    guardrails = load_guardrails()
    db_connection = init_memory()
    ctx = {
        "client": client,
        "db": db_connection,
        "chunks": init_db(),
        "guardrails": guardrails,
        "rag": load_rag_settings(config),
        "internet": internet_settings,
        "template": load_prompt("viewer_context"),
        "persona": bot_persona(load_prompt("persona"), agent_config),
        "stats": {"blocked": 0, "searches": 0, "events": 0,
                  "routes": {"chat": 0, "docs": 0, "web": 0}},
    }

    if args.local:
        sock = None
        chat = ChatOutput(None, channel, writable=False)
        incoming = local_messages(channel)
        print(f"Chat simulé de #{channel}, trigger \"{trigger}\".\n")
    else:
        bot_username = os.environ.get("TWITCH_BOT_USERNAME")
        bot_token = os.environ.get("TWITCH_OAUTH_TOKEN")
        sock = connect(channel, bot_username, bot_token)
        chat = ChatOutput(sock, channel, writable=bool(bot_username and bot_token),
                          cooldown=agent_config["reply_cooldown"])
        incoming = messages(sock, on_ready=lambda: emit("connected", channel=channel))
        mode = f"as {bot_username}" if chat.writable else "anonymously (read-only)"
        print(f"Listening on #{channel} {mode}, trigger \"{trigger}\". Ctrl+C to quit.\n")

    viewers = {}
    activity = {}
    last_search = None
    last_moment = {}
    burst = BurstDetector(
        window=agent_config["burst_window"],
        audience_window=agent_config["burst_audience_window"],
        ratio=agent_config["burst_ratio"],
        min_messages=agent_config["burst_min_messages"],
        cooldown=agent_config["burst_cooldown"],
    )

    try:
        for message in incoming:
            # Never reply to our own account, including in local replay tools.
            if message["author"].lower() == (os.environ.get("TWITCH_BOT_USERNAME") or "").lower():
                continue
            emit("message", viewer=message["user_id"])
            # Atomic dashboard writes allow safe live updates between messages.
            try:
                current = load_bot_settings()
                trigger = current["trigger"]
                chat.cooldown = current["reply_cooldown"]
                ctx["persona"] = bot_persona(load_prompt("persona"), current)
                agent_config = current
            except (OSError, ValueError):
                emit("warning", message="Réglages illisibles ; derniers réglages conservés.")
            chat.request_started = time.monotonic()
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

            detected = burst.add(viewer_id, sent_at)
            if detected is not None:
                count, threshold, audience = detected
                line = add_moment(
                    burst_description.format(count=count, window=burst.window),
                    sent_at,
                )
                print(
                    f"[burst] {count} messages >= {threshold} "
                    f"({audience} active chatters) -> {line}"
                )

            command = parse_command(message["text"], command_prefix)
            question = match_trigger(message["text"], trigger)
            if question is None and not agent_config["mentions_only"] and command is None:
                question = message["text"]
            if (command is not None or question is not None) and not chat.can_reply():
                emit("cooldown")
                continue
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
                    elif name == moment_command:
                        previous = last_moment.get(viewer_id)
                        if not arguments:
                            chat.say(f"@{author} {moment_usage_message}")
                        elif previous is not None and sent_at - previous < moment_cooldown:
                            print(f"[moment] {author} ignored (cooldown)")
                        else:
                            last_moment[viewer_id] = sent_at
                            line = add_moment(f"{arguments} ({author})", sent_at)
                            print(f"[moment] {line}")
                            chat.say(f"@{author} {moment_saved_message}")
                    elif name == event_command and message["is_moderator"]:
                        # The model picks the section; the code applies the edit
                        if not arguments:
                            chat.say(f"@{author} {event_usage_message}")
                        else:
                            _, update = update_report_from_event(arguments, client)
                            if update is None:
                                print("[event] événement non compris, compte-rendu inchangé")
                            else:
                                ctx["stats"]["events"] += 1
                                print(f"[event] {update['section']} ({update['action']}) "
                                      f"<- {update['content']}")
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
                            ctx["stats"]["searches"] += 1
                            search_and_share(
                                arguments, author, client, chat,
                                internet_settings, obs_settings, guardrails,
                            )
                except Exception as error:
                    emit("warning", message="Une commande n'a pas pu être exécutée.")
                    print(f"[command] {name} a échoué : {error}")
                continue

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

            reply = respond(ctx, viewer_id, state, question)
            emit("activity", blocked=ctx["stats"]["blocked"], routes=ctx["stats"]["routes"])
            if reply is None:
                emit("warning", message="Le modèle n'a pas produit de réponse.")
                continue
            chat.post(f"@{state.display_name} {reply}")

            # Only the conversation agent sends the history: the token count
            # of a documents or web call says nothing about its size
            if ctx.get("last_route") != "chat":
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
        write_session_stats(activity, ctx["stats"])
        flush_activity(db_connection, activity)
        if sock is not None:
            sock.close()
        db_connection.close()
        ctx["chunks"].close()


def main():
    if "--local" in sys.argv:
        run_agent()
        return
    with acquire_bot_lock():
        emit("starting")
        try:
            run_agent()
        except Exception:
            emit("error", message="Le bot s'est interrompu. Vérifie Twitch, Ollama et les réglages.")
            raise
        finally:
            emit("stopped")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
