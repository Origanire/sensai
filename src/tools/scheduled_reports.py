# Ce module recherche régulièrement des sujets sur Internet et enregistre les résumés en Markdown, sans bloquer le terminal.

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

# Ces valeurs sont utilisées quand les réglages de veille sont absents.
DEFAULT_SETTINGS = {
    "topics": [],
    "interval_minutes": 60,
    "folder": "reports/",
}

# Ce signal demande à la boucle de veille de s’arrêter.
_stop_event = threading.Event()
# Cette variable contient la tâche de veille, ou None si elle n’a pas été lancée.
_thread = None
# Cet état permet d’afficher ce que fait la veille.
_state = {
    "topics": [],
    "interval_minutes": None,
    "next_run": None,
    "current_topic": None,
    "last_report": None,
    "last_error": None,
}


# Cette erreur indique qu’un rapport n’a pas pu être produit.
class ReportError(Exception):
    pass


# Cette classe appelle le modèle sans afficher sa réponse, pour ne pas perturber la saisie dans le terminal.
class _SilentClient:
    # On conserve le client Ollama à utiliser.
    def __init__(self, client):
        # Ce client permet d’appeler Ollama.
        self.client = client

    # Cette méthode renvoie la réponse du modèle sans l’afficher.
    def chat(self, messages):
        return self.client.chat_silent(messages)


# Cette fonction charge les réglages de veille et complète les valeurs manquantes.
def load_settings(config):
    section = (config or {}).get("scheduled_reports") or {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in section.items() if v is not None})
    settings["topics"] = [str(t) for t in settings["topics"]]
    return settings


# Cette fonction transforme un sujet en nom utilisable dans un fichier.
def slugify(topic):
    ascii_text = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:50].strip("-") or "topic"


# Cette fonction recherche un sujet et demande une synthèse au modèle. Le code ajoute lui-même la date et les sources.
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

    # On garde au maximum cinq puces, même si le modèle en écrit davantage.
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


# Cette fonction sauvegarde le rapport avec une date dans son nom, sans écraser un rapport existant.
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


# Cette boucle produit les rapports à intervalles réguliers. Une erreur sur un sujet n’empêche pas de traiter les suivants.
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


# Cette fonction lance la veille en arrière-plan avec son propre client Ollama.
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


# Cette fonction demande l’arrêt de la veille et attend brièvement. Le rapport en cours peut se terminer avant l’arrêt.
def stop_scheduled_reports(timeout=2):
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout)
    return not is_running()


# Cette fonction vérifie si la veille fonctionne encore.
def is_running():
    return _thread is not None and _thread.is_alive()


# Cette fonction prépare un texte lisible décrivant l’état de la veille.
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
