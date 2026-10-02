## @file commands.py
# @brief Handling of slash commands typed in the CLI.

from src.core.export import export_json, export_md, export_pdf, export_help

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
        case _:
            return "Unknown command."
