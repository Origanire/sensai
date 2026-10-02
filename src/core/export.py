## @file commands.py
# @brief system to handle commands

def export_help() -> str:
    message = "Export function usage :\n" \
    "/export [format]\n" \
    "format : md (markdown), pdf (adobe pdf), json (javascript object notation)\n"
    return message

def export_pdf(messages: list[str]) -> str:
    return "'export_pdf()' not yet implemented."

def export_md(messages: list[str]) -> str:
    return "'export_md()' not yet implemented."

def export_json(messages: list[str]) -> str:
    return "'export_json()' not yet implemented."
