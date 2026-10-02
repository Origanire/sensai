## @file commands.py
# @brief Handling of slash commands typed in the CLI.

from src.core.export import export_json, export_md, export_pdf, export_help
from src.core.ollama_client import load_config
from src.tools.scheduled_reports import (
    load_settings,
    reports_status,
    start_scheduled_reports,
    stop_scheduled_reports,
)

## @brief Usage of the /reports command.
REPORTS_HELP = "Usage : /reports start | stop | status"

## @brief Route an export request to the requested format.
#
# @param format Export format: "md"/"markdown", "pdf", "json" or "help".
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Confirmation, help or error message to display.
def export(format: str, messages: list[dict[str, str]]) -> str:
    if not messages:
        return "Nothing to export, the conversation is empty."
    match format:
        case "pdf":
            return export_pdf(messages)
        case "md" | "markdown":
            return export_md(messages)
        case "json":
            return export_json(messages)
        case "help" | "-h" | "--help":
            return export_help()
        case _:
            return "Unknown format for exporting."

## @brief Start, stop or describe the scheduled web reports.
#
# Topics, interval and folder are read from config.yaml at each start, so
# a change in the config applies at the next /reports start.
#
# @param action "start", "stop" or "status".
# @return Message to display.
def reports(action: str) -> str:
    match action:
        case "start":
            settings = load_settings(load_config())
            if not settings["topics"]:
                return "Aucun sujet configuré (scheduled_reports.topics dans config.yaml)."
            if not start_scheduled_reports(
                settings["topics"], settings["interval_minutes"], settings["folder"]
            ):
                return "Les rapports automatiques tournent déjà."
            return (f"Rapports automatiques lancés : {len(settings['topics'])} sujet(s), "
                    f"toutes les {settings['interval_minutes']} min, dans {settings['folder']}")
        case "stop":
            if stop_scheduled_reports():
                return "Rapports automatiques arrêtés."
            return "Arrêt demandé : la boucle s'arrête après le rapport en cours."
        case "status":
            return reports_status()
        case _:
            return REPORTS_HELP

## @brief Handle a slash command typed by the user.
#
# @param user_input Raw user input (e.g. "/export md").
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Message to display in response to the command.
def commands(user_input: str, messages: list[dict[str, str]]) -> str:
    argv = user_input.split()

    match argv[0]:
        case  "/export":
            if argv.__len__() != 2:
                return export_help()
            return export(argv[1], messages)
        case "/reports":
            if argv.__len__() != 2:
                return REPORTS_HELP
            return reports(argv[1])
        case _:
            return "Unknown command."
