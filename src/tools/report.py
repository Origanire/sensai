## @file report.py
# @brief Living stream report: updated section by section by the model.

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
    "resume": "Résumé",
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


## @brief Ask the model which section to update after an event.
#
# The model receives the event and the current contents of each section,
# and must answer only with a JSON {"section": ..., "content": ...},
# where "content" is the full text of the section after the update.
#
# @param event_description The stream event, as free text.
# @param report Current report (dictionary section -> content).
# @param client Ollama client used for chat.
# @return Dict {"section": ..., "content": ...}, or None on error.
def generate_update(event_description, report, client):
    current = "\n\n".join(
        f'- "{key}" ({SECTION_TITLES[key]}) :\n{report.get(key, DEFAULT_SECTIONS[key])}'
        for key in DEFAULT_SECTIONS
    )

    prompt = f"""Tu maintiens le compte-rendu d'un stream de jeu vidéo, découpé en sections.
Un nouvel événement vient de se produire. Choisis LA section la plus concernée et réécris-la.

Sections disponibles et leur contenu actuel :
{current}

Événement : {event_description}

Réponds UNIQUEMENT avec un JSON de la forme :
{{"section": "<une des clés : {', '.join(DEFAULT_SECTIONS)}>", "content": "<nouveau contenu de la section>"}}

Le champ "content" doit être le texte COMPLET de la section après modification
(contenu actuel conservé et mis à jour), pas seulement ce qui est ajouté.
Aucun texte avant ou après le JSON."""

    messages = [{"role": "user", "content": prompt}]
    response = client.chat(messages)
    if response is None:
        return None

    # Strip a possible Markdown code block (```json ... ```) around the JSON
    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[len("json"):].strip()

    try:
        update = json.loads(text)
    except json.JSONDecodeError:
        print("[Erreur] Le modèle n'a pas renvoyé un JSON valide.")
        return None

    if not isinstance(update, dict) or update.get("section") not in DEFAULT_SECTIONS:
        print(f"[Erreur] Section invalide renvoyée par le modèle (attendu : {', '.join(DEFAULT_SECTIONS)}).")
        return None

    if not isinstance(update.get("content"), str):
        print("[Erreur] Le champ \"content\" est manquant ou n'est pas un texte.")
        return None

    return {"section": update["section"], "content": update["content"]}


## @brief Apply an update to a single section of the report.
#
# @param report Current report (dictionary section -> content).
# @param update Dict {"section": ..., "content": ...}, or None.
# @return The modified report (unchanged if update is None).
def apply_update(report, update):
    if update is None:
        return report
    report[update["section"]] = update["content"]
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
# @return The updated report.
def update_report_from_event(event_description, client, path="stream_report.json"):
    report = init_report(path)
    update = generate_update(event_description, report, client)
    report = apply_update(report, update)
    save_report(report, path)
    return report
