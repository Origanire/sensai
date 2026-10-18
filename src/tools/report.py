# Ce module met à jour le compte-rendu du live avec de petites modifications proposées par le modèle et appliquées par le code.

import json
import os
from datetime import datetime


# Ces sections constituent le rapport initial.
DEFAULT_SECTIONS = {
    "resume": "Aucun résumé pour le moment.",
    "jeu_actuel": "Aucun jeu en cours pour le moment.",
    "moments_forts": "Aucun moment fort pour le moment.",
    "stats": "Aucune statistique pour le moment."
}

# Ces titres servent à afficher les sections en Markdown.
SECTION_TITLES = {
    "resume": "Déroulé",
    "jeu_actuel": "Jeu actuel",
    "moments_forts": "Moments forts",
    "stats": "Statistiques"
}


# Cette fonction crée le rapport s’il manque, puis le charge.
def init_report(path="stream_report.json"):
    if not os.path.exists(path):
        save_report(dict(DEFAULT_SECTIONS), path)
    return load_report(path)


# Cette fonction lit les sections du rapport depuis son fichier JSON.
def load_report(path="stream_report.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Cette fonction sauvegarde les sections du rapport en JSON.
def save_report(report, path="stream_report.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


# Cette fonction transforme le rapport en texte Markdown lisible.
def render_report(report):
    lines = ["# Compte-rendu de stream", ""]
    for key, title in SECTION_TITLES.items():
        lines.append(f"## {title}")
        lines.append(report.get(key, DEFAULT_SECTIONS[key]))
        lines.append("")
    return "\n".join(lines)


# Ce nombre limite les modifications conservées dans le journal du rapport.
JOURNAL_SIZE = 50

# Cette correspondance indique la section et l’action adaptées à chaque type d’événement.
EVENT_TYPES = {
    "changement_de_jeu": ("jeu_actuel", "replace"),
    "moment_fort": ("moments_forts", "append"),
    "chiffre": ("stats", "append"),
    "autre": ("resume", "append"),
}

# Ce schéma impose la structure JSON attendue pour la réponse du modèle.
EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": list(EVENT_TYPES)},
        "content": {"type": "string"},
    },
    "required": ["type", "content"],
}


# Cette fonction demande au modèle de classer et reformuler un événement. Le code choisit ensuite la modification à appliquer.
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


# Cette fonction ajoute ou remplace du texte dans une seule section du rapport.
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


# Cette fonction ajoute un moment fort avec sa date, sans faire reformuler le texte par le modèle.
def add_moment(description, timestamp, path="stream_report.json"):
    report = init_report(path)
    line = f"- {datetime.fromtimestamp(timestamp).strftime('%Hh%M')} : {description}"

    # Le premier moment fort remplace le texte par défaut.
    current = report.get("moments_forts", DEFAULT_SECTIONS["moments_forts"])
    if current == DEFAULT_SECTIONS["moments_forts"]:
        report["moments_forts"] = line
    else:
        report["moments_forts"] = current + "\n" + line

    save_report(report, path)
    return line


# Cette fonction charge le rapport, prépare la modification liée à un événement, puis l’applique et sauvegarde le résultat.
def update_report_from_event(event_description, client, path="stream_report.json"):
    report = init_report(path)
    update = generate_update(event_description, report, client)
    if update is None:
        return report, None
    report = apply_update(report, update)
    save_report(report, path)
    return report, update


# Cette fonction remplace une section avec un texte calculé par le code, notamment les statistiques de fin de live.
def set_section(section, content, path="stream_report.json"):
    report = init_report(path)
    report[section] = content
    save_report(report, path)
