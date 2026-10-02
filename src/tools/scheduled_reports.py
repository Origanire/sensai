## @file scheduled_reports.py
# @brief Internet agent: scheduled web research reports on user-defined topics.
#
# At a regular interval, each topic is searched on the web, then the model
# writes a short synthesis of the results, saved as a Markdown file. The
# loop runs in a daemon thread so the CLI stays usable meanwhile.

import os
import re
import threading
import unicodedata
from datetime import datetime, timedelta

from src.core.ollama_client import OllamaClient
from src.tools.web_search import (
    web_search,
    format_results_for_context,
    generate_search_query,
)

## @brief Settings used when config.yaml has no "scheduled_reports" section.
DEFAULT_SETTINGS = {
    "topics": [],
    "interval_minutes": 60,
    "folder": "reports/",
}

## @brief Flag shared with the loop: set to ask it to stop.
_stop_event = threading.Event()
## @brief Thread running the loop, or None if never started.
_thread = None
## @brief State of the loop, read by reports_status().
_state = {
    "topics": [],
    "interval_minutes": None,
    "next_run": None,
    "current_topic": None,
    "last_report": None,
    "last_error": None,
}


## @brief Raised when a report cannot be produced (no results, model down).
class ReportError(Exception):
    pass


## @brief Ollama client wrapper whose chat() never prints anything.
#
# generate_search_query() calls client.chat(), which streams tokens to
# stdout: from a background thread, they would land in the middle of what
# the user is typing. This wrapper routes the call to chat_silent().
class _SilentClient:
    ## @brief Wrap a client.
    #
    # @param client OllamaClient to wrap.
    def __init__(self, client):
        ## @brief Wrapped OllamaClient.
        self.client = client

    ## @brief Same contract as OllamaClient.chat(), without printing.
    #
    # @param messages Conversation (list of "role"/"content" dicts).
    # @return The model's response, or None on error.
    def chat(self, messages):
        return self.client.chat_silent(messages)


## @brief Read the "scheduled_reports" section of the configuration.
#
# Missing keys (or a missing section) fall back to DEFAULT_SETTINGS, so an
# older config.yaml keeps working.
#
# @param config Configuration dictionary loaded from config.yaml.
# @return Dict with "topics", "interval_minutes" and "folder".
def load_settings(config):
    section = (config or {}).get("scheduled_reports") or {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in section.items() if v is not None})
    settings["topics"] = [str(t) for t in settings["topics"]]
    return settings


## @brief Turn a topic into a string usable in a file name.
#
# @param topic Topic, e.g. "Patch Elden Ring 1.12".
# @return Slug, e.g. "patch-elden-ring-1-12".
def slugify(topic):
    ascii_text = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:50].strip("-") or "topic"


## @brief Search the web on a topic and have the model synthesize it.
#
# The title, date and sources are written by the code, not the model: a
# 3B model regularly invents dates or URLs. The model only writes the key
# points, each one pointing to a numbered search result.
#
# @param topic Topic to research.
# @param client OllamaClient.
# @param max_results Number of web results given to the model.
# @return The report, as Markdown text.
# @exception ReportError If the search returns nothing or the model fails.
def generate_report(topic, client, max_results=5):
    silent = _SilentClient(client)

    query = generate_search_query(topic, silent)
    results = web_search(query, max_results=max_results)
    if not results:
        raise ReportError(f"aucun résultat web pour « {query} » (réseau indisponible ?)")

    numbered = [dict(r, title=f"[{i}] {r['title']}") for i, r in enumerate(results, 1)]
    context = format_results_for_context(numbered)

    prompt = f"""Tu prépares une note de veille pour un streamer Twitch sur le sujet : {topic}

Voici des résultats de recherche web récents, numérotés :

{context}

Rédige entre 3 et 5 points clés qui résument ce que disent ces résultats.

Règles :
- Chaque point s'appuie sur un fait précis tiré des résultats (nom, chiffre,
  date, annonce) et se termine par le numéro de sa source, ex. [2].
- Aucun conseil générique ni information absente des résultats.
- Réponds en français, UNIQUEMENT avec la liste à puces (une ligne par point,
  commençant par "- "), sans titre ni introduction."""

    answer = silent.chat([{"role": "user", "content": prompt}])
    if not answer or not answer.strip():
        raise ReportError("Ollama n'a pas répondu (est-il lancé ?)")

    # The model does not always respect the count: keep the bullets, at most 5
    bullets = [line.strip().lstrip("-*• ").strip() for line in answer.splitlines()
               if line.strip().startswith(("-", "*", "•"))]
    if not bullets:
        raise ReportError("réponse du modèle sans liste de points clés")
    points = "\n".join(f"- {bullet}" for bullet in bullets[:5])

    sources = "\n".join(
        f"{i}. [{r['title']}]({r['url']})" for i, r in enumerate(results, 1)
    )
    date = datetime.now().strftime("%d/%m/%Y à %Hh%M")

    return (
        f"# Rapport de veille : {topic}\n\n"
        f"_Généré le {date} — requête : « {query} »_\n\n"
        f"## Points clés\n\n{points}\n\n"
        f"## Sources\n\n{sources}\n"
    )


## @brief Write a report to a timestamped Markdown file.
#
# Two reports of the same topic within the same minute (very short
# interval) get a numeric suffix instead of overwriting each other.
#
# @param topic Topic of the report.
# @param report_text Markdown text of the report.
# @param folder Destination directory, created if needed.
# @return Path of the written file.
def save_report(topic, report_text, folder="reports/"):
    os.makedirs(folder, exist_ok=True)

    stem = f"report_{slugify(topic)}_{datetime.now().strftime('%Y-%m-%d_%Hh%M')}"
    path = os.path.join(folder, f"{stem}.md")
    suffix = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem}_{suffix}.md")
        suffix += 1

    with open(path, "w", encoding="utf-8") as f:
        f.write(report_text)
    return path


## @brief Generate and save a report for each topic, every interval.
#
# Blocking loop, meant to run in a thread (see start_scheduled_reports).
# A failure on a topic (no network, Ollama down, disk error) is logged and
# the topic is skipped: the next attempt happens at the next interval.
# The first cycle starts immediately.
#
# @param topics List of topics to research.
# @param client OllamaClient.
# @param interval_minutes Time between the start of two cycles, in minutes.
# @param folder Directory where the reports are saved.
def run_scheduled_reports(topics, client, interval_minutes, folder="reports/"):
    interval = timedelta(minutes=interval_minutes)
    _state.update(topics=list(topics), interval_minutes=interval_minutes,
                  last_report=None, last_error=None)

    while not _stop_event.is_set():
        cycle_start = datetime.now()
        _state["next_run"] = cycle_start + interval

        for topic in topics:
            if _stop_event.is_set():
                break
            _state["current_topic"] = topic
            try:
                path = save_report(topic, generate_report(topic, client), folder)
                _state["last_report"] = path
                print(f"\n[Rapports] « {topic} » -> {path}")
            except Exception as error:
                _state["last_error"] = f"{topic} : {error}"
                print(f"\n[Rapports] « {topic} » ignoré ce cycle : {error}")
        _state["current_topic"] = None

        remaining = (_state["next_run"] - datetime.now()).total_seconds()
        _stop_event.wait(max(0, remaining))

    _state["next_run"] = None
    _state["current_topic"] = None


## @brief Launch run_scheduled_reports() in a daemon thread.
#
# The thread gets its own OllamaClient so it never shares per-call state
# (token counters) with the chat.
#
# @param topics List of topics to research.
# @param interval_minutes Time between two cycles, in minutes.
# @param folder Directory where the reports are saved.
# @return False if a loop is already running, True otherwise.
def start_scheduled_reports(topics, interval_minutes, folder="reports/"):
    global _thread
    if is_running():
        return False

    _stop_event.clear()
    _thread = threading.Thread(
        target=run_scheduled_reports,
        args=(topics, OllamaClient(), interval_minutes, folder),
        name="scheduled-reports",
        daemon=True,
    )
    _thread.start()
    return True


## @brief Ask the loop to stop and wait briefly for it.
#
# The thread is never killed: it notices the flag between two topics, or
# right away if it is waiting for the next cycle. A report being written
# is finished first, which can take up to the Ollama timeout.
#
# @param timeout Maximum wait, in seconds.
# @return True if the loop has stopped, False if it is still finishing.
def stop_scheduled_reports(timeout=2):
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout)
    return not is_running()


## @brief Tell whether the loop is running.
#
# @return True if the thread is alive.
def is_running():
    return _thread is not None and _thread.is_alive()


## @brief Describe the state of the loop, for display.
#
# @return Human-readable status text.
def reports_status():
    if not is_running():
        return "Rapports automatiques : inactifs."

    lines = [
        "Rapports automatiques : actifs.",
        f"Sujets : {', '.join(_state['topics'])}",
        f"Intervalle : {_state['interval_minutes']} min",
    ]
    if _stop_event.is_set():
        lines.append("Arrêt demandé, fin du rapport en cours.")
    elif _state["current_topic"] is not None:
        lines.append(f"Cycle en cours : « {_state['current_topic']} »")
    elif _state["next_run"] is not None:
        lines.append(f"Prochain cycle : {_state['next_run'].strftime('%Hh%M:%S')}")
    if _state["last_report"]:
        lines.append(f"Dernier rapport : {_state['last_report']}")
    if _state["last_error"]:
        lines.append(f"Dernière erreur : {_state['last_error']}")
    return "\n".join(lines)
