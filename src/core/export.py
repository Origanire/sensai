## @file export.py
# @brief Export a conversation to various formats: Markdown, PDF and JSON.

from datetime import datetime
from pathlib import Path
from json import dumps
import markdown
from fpdf import FPDF

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

## @brief Write serialized content to a timestamped file in exports/.
#
# Creates the exports/ folder if needed, then writes the content to a
# file named after the current date and time, with the given extension.
# If the name is already taken, a counter is appended (e.g. "_1").
# Text content is written as UTF-8; binary content (e.g. PDF) is
# written as-is.
#
# @param content Serialized conversation, as text or bytes.
# @param extension File extension, with the leading dot (e.g. ".md").
# @return Path of the created file.
def write_export_file(content: str | bytes | bytearray, extension: str) -> Path:
    now: datetime = datetime.now()
    timestamp: str = now.strftime("SensaiChat_%Y-%m-%d_%H-%M")

    EXPORT_DIR.mkdir(exist_ok=True)

    export_filename: Path = (EXPORT_DIR / timestamp).with_suffix(extension)
    counter: int = 1
    while export_filename.exists():
        export_filename = (EXPORT_DIR / f"{timestamp}_{counter}").with_suffix(extension)
        counter += 1

    if isinstance(content, (bytes, bytearray)):
        with open(export_filename, "wb") as file:
            file.write(content)
    else:
        with open(export_filename, "w", encoding="utf-8") as file:
            file.write(content)

    return export_filename


## @brief Build the Markdown text shared by the Markdown and PDF exports.
#
# The text starts with a title containing the export date, followed by
# one section per message: the role as a heading, the content below it.
#
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Markdown text of the conversation.
def build_markdown_string(messages: list[dict[str, str]]) -> str:
    now: datetime = datetime.now()
    export_datetime: str = now.strftime("%d/%m/%Y %H:%M")
    export_string: str = f"# Sensai CLI Chat conversation export {export_datetime}\n"

    for message in messages:
        role = message["role"]
        content = message["content"]
        export_string += f"## {role}\n{content}\n\n"

    return export_string

## @brief Export the conversation to a PDF file.
#
# The same Markdown source as export_md is built, converted to HTML by
# the markdown package, then rendered into pages by fpdf2. The file is
# created in the exports/ folder at the repository root, under a
# timestamped name to keep successive exports distinct.
#
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Confirmation message showing the path of the created file.
def export_pdf(messages: list[dict[str, str]]) -> str:
    export_string = build_markdown_string(messages)
    export_html = markdown.markdown(export_string)

    pdf = FPDF()
    pdf.add_page()
    pdf.write_html(export_html)

    export_filename = write_export_file(pdf.output(), ".pdf")
    return f"PDF chat export successful at '{export_filename}'."

## @brief Export the conversation to a Markdown file.
#
# The file is created in the exports/ folder at the repository root, under
# a timestamped name to keep successive exports distinct.
#
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Confirmation message showing the path of the created file.
def export_md(messages: list[dict[str, str]]) -> str:
    export_string = build_markdown_string(messages)
    export_filename = write_export_file(export_string, ".md")
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
    export_content = dumps(messages, indent=2, ensure_ascii=False)
    export_filename = write_export_file(export_content, ".json")
    return f"JSON chat export successful at '{export_filename}'."
