## @file export.py
# @brief Export a conversation to various formats: Markdown, PDF and JSON.

from datetime import datetime
from pathlib import Path
from json import dumps

## @brief Export folder, anchored to the repository root regardless of the
# directory the CLI is launched from.
EXPORT_DIR = Path(__file__).resolve().parents[2] / "exports"

## @brief Help for the /export command.
#
# @return Help text describing usage and available formats.
def export_help() -> str:
    message = "Export function usage :\n" \
    "/export [format]\n" \
    "format : md (markdown), pdf (adobe pdf), json (javascript object notation)\n"
    return message

## @brief Export the conversation to PDF (not implemented).
#
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Message stating the function is not yet implemented.
def export_pdf(messages: list[dict[str, str]]) -> str:
    return "'export_pdf()' not yet implemented."

## @brief Export the conversation to a Markdown file.
#
# The file is created in the exports/ folder at the repository root, under
# a timestamped name to keep successive exports distinct.
#
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Confirmation message showing the path of the created file.
def export_md(messages: list[dict[str, str]]) -> str:
    now: datetime = datetime.now()
    export_datetime: str = now.strftime("%d/%m/%Y %H:%M")

    export_filename: Path = (
        EXPORT_DIR / now.strftime("SensaiChat_%Y-%m-%d_%H-%M")
    ).with_suffix(".md")

    export_string: str = f"# Sensai CLI Chat conversation export {export_datetime}\n"

    for message in messages:
        role = message["role"]
        content = message["content"]
        export_string += f"## {role}\n{content}\n\n"

    EXPORT_DIR.mkdir(exist_ok=True)
    with open(export_filename, "w", encoding="utf-8") as file:
        file.write(export_string)

    return f"Markdown chat export successful at '{export_filename}'."

## @brief Export the conversation to a JSON file.
#
# The conversation history is serialized as-is: a JSON array of
# "role"/"content" dicts. The file is created in the exports/ folder at
# the repository root, under a timestamped name to keep successive
# exports distinct.
#
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Confirmation message showing the path of the created file.
def export_json(messages: list[dict[str, str]]) -> str:
    now: datetime = datetime.now()

    export_filename: Path = (
        EXPORT_DIR / now.strftime("SensaiChat_%Y-%m-%d_%H-%M")
    ).with_suffix(".json")

    export_content = dumps(messages, indent=2, ensure_ascii=False)

    EXPORT_DIR.mkdir(exist_ok=True)
    with open(export_filename, "w", encoding="utf-8") as file:
        file.write(export_content)

    return f"JSON chat export successful at '{export_filename}'."
