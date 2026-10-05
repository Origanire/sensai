## @file commands.py
# @brief Handling of slash commands typed in the CLI.

from src.core.export import (
    conversation_sections,
    export_help,
    export_sections,
    share,
)
from src.core.ingestion import ingest_folder
from src.core.ollama_client import load_config
from src.core.search import format_sources, rag_chat
from src.core.storage import DOCUMENTS, STREAMS, count_chunks, list_sources, save_chunks
from src.tools.report import SECTION_TITLES, init_report, render_report, update_report_from_event
from src.tools.scheduled_reports import (
    load_settings,
    reports_status,
    start_scheduled_reports,
    stop_scheduled_reports,
)
from src.tools.strategy import end_stream, generate_strategy_recommendations

## @brief Usage of the /reports command.
REPORTS_HELP = "Usage : /reports start | stop | status"

## @brief Help of the CLI, shown by /help.
HELP = """Commandes :
  /help                     cette aide
  /ingest [dossier]         indexe les documents (txt, md, pdf, docx) pour le RAG
  /docs                     liste les documents indexés
  /ask <question>           répond à partir des documents, avec les sources
  /event <description>      note un événement dans le compte-rendu du stream
  /report                   affiche le compte-rendu du stream en cours
  /stream end               archive le compte-rendu et l'indexe pour /strategy
  /strategy                 conseils pour le prochain stream, tirés des streams passés
  /tools                    liste les outils MCP disponibles
  /export <format> [report] exporte la conversation ou le compte-rendu (md, json, pdf, html)
  /share [report]           publie la conversation ou le compte-rendu par un lien
  /reports start|stop|status rapports de veille web automatiques
  exit                      quitter"""


## @brief Title, sections and raw data of the document to export.
#
# @param target "report" for the stream report, anything else for the
#               conversation.
# @param messages Conversation history.
# @return A (title, sections, file stem, raw data) tuple.
def document(target, messages):
    if target == "report":
        report = init_report()
        sections = [(title, report.get(key, "")) for key, title in SECTION_TITLES.items()]
        return "Compte-rendu de stream", sections, "StreamReport", report
    return "Sensai CLI Chat conversation", conversation_sections(messages), "SensaiChat", messages


## @brief Route an export request to the requested format.
#
# @param argv Arguments of /export (format, then optionally "report").
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Confirmation, help or error message to display.
def export(argv, messages):
    if not argv or argv[0] in ("help", "-h", "--help"):
        return export_help()
    target = argv[1] if len(argv) > 1 else "conversation"
    if target != "report" and not messages:
        return "Nothing to export, the conversation is empty."
    title, sections, stem, raw = document(target, messages)
    return export_sections(argv[0], title, sections, stem, raw)


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


## @brief Index a folder of documents into the "documents" collection.
#
# @param folder Folder to ingest.
# @param ctx CLI context (client, chunks database).
# @return Summary of what was indexed.
def ingest(folder, ctx):
    try:
        results = ingest_folder(folder, ctx["client"], ctx["rag"]["chunk_size"],
                                ctx["rag"]["overlap"])
    except FileNotFoundError:
        return f"Dossier introuvable : {folder}"
    for filename, chunks in results.items():
        save_chunks(ctx["chunks"], filename, chunks, DOCUMENTS)
    return (f"{len(results)} document(s) indexé(s) depuis {folder}, "
            f"{count_chunks(ctx['chunks'], DOCUMENTS)} passages au total.")


## @brief Answer a question from the documents, then list the sources.
#
# The answer is streamed by rag_chat(); only the sources are returned.
#
# @param question Question typed after /ask.
# @param ctx CLI context.
# @return Sources with their similarity score.
def ask(question, ctx):
    print("Sensai : ", end="", flush=True)
    answer, results = rag_chat(question, ctx["client"], ctx["chunks"], ctx["rag"]["top_k"],
                               ctx["rag"]["min_score"])
    if answer is None:
        return "[Info] Pas de réponse du modèle."
    if not results:
        return f"(aucun passage au-dessus du seuil {ctx['rag']['min_score']})"
    return "Sources :\n" + format_sources(results)


## @brief Handle a slash command typed by the user.
#
# @param user_input Raw user input (e.g. "/export md").
# @param messages Conversation history (list of "role"/"content" dicts).
# @param ctx CLI context: client, chunks database, RAG settings, MCP
#            registry, share port.
# @return Message to display in response to the command.
def commands(user_input, messages, ctx):
    argv = user_input.split()
    rest = user_input.partition(" ")[2].strip()

    match argv[0]:
        case "/help":
            return HELP
        case "/export":
            return export(argv[1:], messages)
        case "/share":
            target = argv[1] if len(argv) > 1 else "conversation"
            if target != "report" and not messages:
                return "Rien à partager, la conversation est vide."
            title, sections, stem, _ = document(target, messages)
            return share(title, sections, stem, ctx["share_port"])
        case "/reports":
            if len(argv) != 2:
                return REPORTS_HELP
            return reports(argv[1])
        case "/ingest":
            return ingest(rest or ctx["rag"]["folder"], ctx)
        case "/docs":
            sources = list_sources(ctx["chunks"], DOCUMENTS)
            if not sources:
                return "Aucun document indexé : utilise /ingest."
            return "\n".join(f"- {source} ({count} passages)" for source, count in sources)
        case "/ask":
            if not rest:
                return "Usage : /ask <question>"
            return ask(rest, ctx)
        case "/event":
            if not rest:
                return "Usage : /event <description>"
            _, update = update_report_from_event(rest, ctx["client"])
            if update is None:
                return "Événement non compris, compte-rendu inchangé."
            return f"Section « {update['section']} » ({update['action']}) : {update['content']}"
        case "/report":
            return render_report(init_report())
        case "/stream":
            if argv[1:] != ["end"]:
                return "Usage : /stream end"
            path = end_stream(ctx["client"], ctx["chunks"])
            if path is None:
                return "Aucun compte-rendu en cours."
            return (f"Stream archivé dans {path} et indexé "
                    f"({count_chunks(ctx['chunks'], STREAMS)} passages d'historique).")
        case "/strategy":
            if not count_chunks(ctx["chunks"], STREAMS):
                return "Aucun stream archivé : termine d'abord un stream avec /stream end."
            print("Sensai : ", end="", flush=True)
            advice = generate_strategy_recommendations(ctx["client"], ctx["chunks"])
            return "" if advice else "[Info] Pas de réponse du modèle."
        case "/tools":
            if ctx["registry"] is None:
                return "Outils MCP désactivés (mcp.enabled dans config.yaml, ou --no-tools)."
            return ctx["registry"].describe()
        case _:
            return "Commande inconnue. Tape /help."
