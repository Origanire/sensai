## @file report.py
# @brief Living stream report (M4): updated section by section by the
# model, through small JSON edits applied by the code.

import json
import os
from datetime import datetime


## @brief Sections of the report and their default contents.
DEFAULT_SECTIONS = {
    "resume": "Aucun résumé pour le moment.",
    "jeu_actuel": "Aucun jeu en cours pour le moment.",
    "moments_forts": "Aucun moment fort pour le moment.",
    "stats": "Aucune statistique pour le moment."
}

## @brief Markdown titles displayed for each section.
SECTION_TITLES = {
    "resume": "Déroulé",
    "jeu_actuel": "Jeu actuel",
    "moments_forts": "Moments forts",
    "stats": "Statistiques"
}


## @brief Create the report file if it does not exist yet.
#
# @param path Path of the report's JSON file.
# @return The report dictionary loaded from the file.
def init_report(path="stream_report.json"):
    if not os.path.exists(path):
        save_report(dict(DEFAULT_SECTIONS), path)
    return load_report(path)


## @brief Load the report from its JSON file.
#
# @param path Path of the report's JSON file.
# @return Dictionary section -> content.
def load_report(path="stream_report.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


## @brief Save the report to its JSON file.
#
# @param report Dictionary section -> content.
# @param path Path of the report's JSON file.
def save_report(report, path="stream_report.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


## @brief Turn the report into readable Markdown text.
#
# @param report Dictionary section -> content.
# @return The report in Markdown format.
def render_report(report):
    lines = ["# Compte-rendu de stream", ""]
    for key, title in SECTION_TITLES.items():
        lines.append(f"## {title}")
        lines.append(report.get(key, DEFAULT_SECTIONS[key]))
        lines.append("")
    return "\n".join(lines)


## @brief Number of edits kept in the report's journal.
JOURNAL_SIZE = 50

## @brief Kind of event -> (section, action) of the edit applied by the code.
EVENT_TYPES = {
    "changement_de_jeu": ("jeu_actuel", "replace"),
    "moment_fort": ("moments_forts", "append"),
    "chiffre": ("stats", "append"),
    "autre": ("resume", "append"),
}

## @brief JSON schema of the model's answer: Ollama constrains the
# generation to it, so the answer is always parseable.
EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": list(EVENT_TYPES)},
        "content": {"type": "string"},
    },
    "required": ["type", "content"],
}


## @brief Ask the model how a stream event changes the report.
#
# The model never rewrites the report. It only classifies the event into
# one of EVENT_TYPES and rephrases it in one line, as a JSON constrained by
# EDIT_SCHEMA. The code maps the type to a section and an action ("append"
# a line, or "replace" the current game): a 3B model picks a type
# reliably, but mixes up sections and actions when asked for them directly.
#
# @param event_description The stream event, as free text.
# @param report Current report (dictionary section -> content).
# @param client Ollama client used for chat.
# @return Dict {"section", "action", "content"}, or None on error.
def generate_update(event_description, report, client):
    prompt = f"""Tu tiens le compte-rendu d'un stream de jeu vidéo.
Classe l'événement dans UN type et reformule-le en une ligne courte.

Types :
- "changement_de_jeu" : le streamer commence ou change de jeu. content = le nom du jeu seul.
- "moment_fort" : un exploit, une victoire, un boss battu, un échec ou une mort marquante.
- "chiffre" : un nombre de viewers, d'abonnés, de dons, un record chiffré.
- "autre" : tout le reste (annonce, invité, pause...).

Exemples :
- "on lance Hades 2" -> {{"type": "changement_de_jeu", "content": "Hades 2"}}
- "on a enfin tué Malenia !" -> {{"type": "moment_fort", "content": "Malenia battue"}}
- "on vient de passer les 300 viewers" -> {{"type": "chiffre", "content": "300 viewers atteints"}}
- "pause de 10 minutes" -> {{"type": "autre", "content": "Pause de 10 minutes"}}

Jeu actuel : {report.get("jeu_actuel", DEFAULT_SECTIONS["jeu_actuel"])}

Événement : {event_description}

N'ajoute aucune information absente de l'événement."""

    answer = client.chat_json([{"role": "user", "content": prompt}], EDIT_SCHEMA)
    if answer is None:
        return None

    if answer.get("type") not in EVENT_TYPES:
        print(f"[Erreur] Type d'événement invalide renvoyé par le modèle (attendu : {', '.join(EVENT_TYPES)}).")
        return None
    content = answer.get("content")
    if not isinstance(content, str) or not content.strip():
        print("[Erreur] Le champ \"content\" est manquant ou vide.")
        return None

    section, action = EVENT_TYPES[answer["type"]]
    return {"section": section, "action": action, "content": content.strip()}


## @brief Apply an edit to a single section of the report.
#
# "append" adds the content as a new line (a timestamped bullet for the
# highlights), replacing the default placeholder if the section was still
# empty; "replace" swaps the whole section. Every applied edit is logged
# in the report's "_journal", so a wrong edit can be traced.
#
# @param report Current report (dictionary section -> content).
# @param update Dict {"section", "action", "content"}, or None.
# @param timestamp Time of the event, in seconds; now if None.
# @return The modified report (unchanged if update is None).
def apply_update(report, update, timestamp=None):
    if update is None:
        return report

    section = update["section"]
    content = update["content"]
    moment = datetime.fromtimestamp(timestamp) if timestamp else datetime.now()

    if update.get("action", "replace") == "append":
        if section == "moments_forts" and not content.startswith("- "):
            content = f"- {moment.strftime('%Hh%M')} : {content.lstrip('- ')}"
        elif not content.startswith("- "):
            content = f"- {content}"
        current = report.get(section, DEFAULT_SECTIONS[section])
        if current == DEFAULT_SECTIONS[section]:
            report[section] = content
        else:
            report[section] = current + "\n" + content
    else:
        report[section] = content

    journal = report.setdefault("_journal", [])
    journal.append({
        "time": moment.strftime("%Y-%m-%d %H:%M:%S"),
        "section": section,
        "action": update.get("action", "replace"),
        "content": update["content"],
    })
    del journal[:-JOURNAL_SIZE]
    return report


## @brief Append a timestamped highlight to the report.
#
# The text is written as-is into the "moments_forts" section, without
# going through the model: it comes from a human (!moment command),
# so there is nothing to rephrase and no section to guess.
#
# @param description Description of the moment, as typed in the chat.
# @param timestamp Timestamp of the moment, in seconds.
# @param path Path of the report's JSON file.
# @return The added line, e.g. "- 22h15 : victoire contre Messmer".
def add_moment(description, timestamp, path="stream_report.json"):
    report = init_report(path)
    line = f"- {datetime.fromtimestamp(timestamp).strftime('%Hh%M')} : {description}"

    # The default text is replaced by the first moment, not appended to
    current = report.get("moments_forts", DEFAULT_SECTIONS["moments_forts"])
    if current == DEFAULT_SECTIONS["moments_forts"]:
        report["moments_forts"] = line
    else:
        report["moments_forts"] = current + "\n" + line

    save_report(report, path)
    return line


## @brief Update the report from a stream event.
#
# Loads (or initializes) the report, asks the model for the update,
# applies it to the relevant section, then saves the file.
#
# @param event_description The stream event, as free text.
# @param client Ollama client used for chat.
# @param path Path of the report's JSON file.
# @return A (report, applied edit) pair; the edit is None when the model
#         failed, and the report is then left unchanged.
def update_report_from_event(event_description, client, path="stream_report.json"):
    report = init_report(path)
    update = generate_update(event_description, report, client)
    if update is None:
        return report, None
    report = apply_update(report, update)
    save_report(report, path)
    return report, update


## @brief Overwrite a section with text computed by the code.
#
# Used for the statistics written at the end of the stream: figures come
# from counters, not from the model, so there is nothing to generate.
#
# @param section Key of the section.
# @param content New content of the section.
# @param path Path of the report's JSON file.
def set_section(section, content, path="stream_report.json"):
    report = init_report(path)
    report[section] = content
    save_report(report, path)
