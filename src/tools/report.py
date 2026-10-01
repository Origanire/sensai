## @file report.py
# @brief Compte-rendu de stream vivant : mise à jour section par section via le modèle.

import json
import os
from datetime import datetime


## @brief Sections du compte-rendu et leur contenu par défaut.
DEFAULT_SECTIONS = {
    "resume": "Aucun résumé pour le moment.",
    "jeu_actuel": "Aucun jeu en cours pour le moment.",
    "moments_forts": "Aucun moment fort pour le moment.",
    "stats": "Aucune statistique pour le moment."
}

## @brief Titres Markdown affichés pour chaque section.
SECTION_TITLES = {
    "resume": "Résumé",
    "jeu_actuel": "Jeu actuel",
    "moments_forts": "Moments forts",
    "stats": "Statistiques"
}


## @brief Crée le fichier du compte-rendu s'il n'existe pas encore.
#
# @param path Chemin du fichier JSON du compte-rendu.
# @return Dictionnaire du compte-rendu chargé depuis le fichier.
def init_report(path="stream_report.json"):
    if not os.path.exists(path):
        save_report(dict(DEFAULT_SECTIONS), path)
    return load_report(path)


## @brief Charge le compte-rendu depuis le fichier JSON.
#
# @param path Chemin du fichier JSON du compte-rendu.
# @return Dictionnaire section -> contenu.
def load_report(path="stream_report.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


## @brief Sauvegarde le compte-rendu dans le fichier JSON.
#
# @param report Dictionnaire section -> contenu.
# @param path Chemin du fichier JSON du compte-rendu.
def save_report(report, path="stream_report.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


## @brief Transforme le compte-rendu en texte Markdown lisible.
#
# @param report Dictionnaire section -> contenu.
# @return Compte-rendu au format Markdown.
def render_report(report):
    lines = ["# Compte-rendu de stream", ""]
    for key, title in SECTION_TITLES.items():
        lines.append(f"## {title}")
        lines.append(report.get(key, DEFAULT_SECTIONS[key]))
        lines.append("")
    return "\n".join(lines)


## @brief Demande au modèle quelle section modifier suite à un événement.
#
# Le modèle reçoit l'événement et le contenu actuel de chaque section, et
# doit répondre uniquement avec un JSON {"section": ..., "content": ...},
# où "content" est le texte complet de la section après modification.
#
# @param event_description Événement du stream en texte libre.
# @param report Compte-rendu actuel (dictionnaire section -> contenu).
# @param client Client Ollama utilisé pour le chat.
# @return Dict {"section": ..., "content": ...}, ou None en cas d'erreur.
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

    # Retire un éventuel bloc de code Markdown (```json ... ```) autour du JSON
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


## @brief Applique une mise à jour à une seule section du compte-rendu.
#
# @param report Compte-rendu actuel (dictionnaire section -> contenu).
# @param update Dict {"section": ..., "content": ...}, ou None.
# @return Compte-rendu modifié (inchangé si update est None).
def apply_update(report, update):
    if update is None:
        return report
    report[update["section"]] = update["content"]
    return report


## @brief Ajoute un moment fort horodaté au compte-rendu.
#
# Le texte est écrit tel quel dans la section "moments_forts", sans passer
# par le modèle : il vient d'un humain (commande !moment), il n'y a donc
# rien à reformuler ni de section à deviner.
#
# @param description Description du moment, telle que tapée dans le chat.
# @param timestamp Horodatage du moment, en secondes.
# @param path Chemin du fichier JSON du compte-rendu.
# @return Ligne ajoutée, par exemple "- 22h15 : victoire contre Messmer".
def add_moment(description, timestamp, path="stream_report.json"):
    report = init_report(path)
    line = f"- {datetime.fromtimestamp(timestamp).strftime('%Hh%M')} : {description}"

    # Le texte par défaut est remplacé par le premier moment, pas complété
    current = report.get("moments_forts", DEFAULT_SECTIONS["moments_forts"])
    if current == DEFAULT_SECTIONS["moments_forts"]:
        report["moments_forts"] = line
    else:
        report["moments_forts"] = current + "\n" + line

    save_report(report, path)
    return line


## @brief Met à jour le compte-rendu à partir d'un événement du stream.
#
# Charge (ou initialise) le compte-rendu, demande la mise à jour au modèle,
# l'applique à la section concernée puis sauvegarde le fichier.
#
# @param event_description Événement du stream en texte libre.
# @param client Client Ollama utilisé pour le chat.
# @param path Chemin du fichier JSON du compte-rendu.
# @return Compte-rendu mis à jour.
def update_report_from_event(event_description, client, path="stream_report.json"):
    report = init_report(path)
    update = generate_update(event_description, report, client)
    report = apply_update(report, update)
    save_report(report, path)
    return report
