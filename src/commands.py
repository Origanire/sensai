## @file commands.py
# @brief system to handle commands

from src.core.export import export_json, export_md, export_pdf, export_help

def export(format: str, messages: list[str]) -> str:
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

def commands(user_input: str, messages: list[str]) -> str:
    argv = user_input.split()

    match argv[0]:
        case  "/export":
            if argv.__len__() != 2:
                return export_help()
            return export(argv[1], messages)
        case _:
            return "Unknown command."
