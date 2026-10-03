## @file export.py
# @brief Export a conversation or the stream report (X3): Markdown, JSON,
# PDF and HTML, plus a no-auth share link served over HTTP.

import html
import json
import socket
import threading
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fpdf import FPDF

## @brief Export folder, anchored to the repository root regardless of the
# directory the CLI is launched from.
EXPORT_DIR = Path(__file__).resolve().parents[2] / "exports"
## @brief Unicode font used for the PDF when available (accents, quotes...).
PDF_FONTS = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)
## @brief Display names of the roles of a conversation.
ROLE_NAMES = {
    "user": "Toi",
    "assistant": "Sensai",
    "system": "Système",
    "tool": "Outil",
}
## @brief Port of the share server when config.yaml does not give one.
DEFAULT_SHARE_PORT = 8765

## @brief Running share server, or None.
_server = None


## @brief Help for the /export command.
#
# @return Help text describing usage and available formats.
def export_help() -> str:
    message = "Export function usage :\n" \
    "/export [format]         exporte la conversation\n" \
    "/export [format] report  exporte le compte-rendu du stream\n" \
    "format : md (markdown), pdf (adobe pdf), json (javascript object notation), html\n" \
    "/share [report]          publie la conversation (ou le compte-rendu) par un lien\n"
    return message


## @brief Build the path of a new export file.
#
# @param stem Start of the file name ("SensaiChat", "StreamReport").
# @param extension File extension, without the dot.
# @return Timestamped path inside EXPORT_DIR (the folder is created).
def export_path(stem, extension):
    EXPORT_DIR.mkdir(exist_ok=True)
    name = datetime.now().strftime(f"{stem}_%Y-%m-%d_%H-%M-%S.{extension}")
    return EXPORT_DIR / name


## @brief Turn a conversation into titled sections.
#
# Every exporter works on the same (title, body) list: a conversation and
# the stream report are exported by the same code.
#
# @param messages Conversation history (list of "role"/"content" dicts).
# @return List of (title, body) pairs, one per message.
def conversation_sections(messages):
    sections = []
    for message in messages:
        role = ROLE_NAMES.get(message["role"], message["role"])
        if message.get("tool_name"):
            role = f"{role} ({message['tool_name']})"
        body = message.get("content") or ""
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            arguments = json.dumps(function.get("arguments", {}), ensure_ascii=False)
            body += f"\nAppel d'outil : {function.get('name')}({arguments})"
        sections.append((role, body.strip()))
    return sections


## @brief Write titled sections to a Markdown file.
#
# @param title Title of the document.
# @param sections List of (title, body) pairs.
# @param stem Start of the file name.
# @return Path of the created file.
def write_md(title, sections, stem):
    path = export_path(stem, "md")
    text = f"# {title}\n\n_Exporté le {datetime.now().strftime('%d/%m/%Y %H:%M')}_\n\n"
    text += "".join(f"## {heading}\n{body}\n\n" for heading, body in sections)
    path.write_text(text, encoding="utf-8")
    return path


## @brief Write titled sections to a PDF file.
#
# A Unicode TrueType font is used when one is installed; otherwise the
# built-in Helvetica only knows Latin-1, so other characters (emojis,
# typographic quotes) are replaced instead of crashing the export.
#
# @param title Title of the document.
# @param sections List of (title, body) pairs.
# @param stem Start of the file name.
# @return Path of the created file.
def write_pdf(title, sections, stem):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    font = next((f for f in PDF_FONTS if f.exists()), None)
    if font is not None:
        pdf.add_font("Body", "", str(font))
        family = "Body"

        def clean(text):
            return text
    else:
        family = "Helvetica"

        def clean(text):
            return text.encode("latin-1", "replace").decode("latin-1")

    pdf.set_font(family, size=16)
    pdf.multi_cell(0, 10, clean(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(family, size=9)
    pdf.multi_cell(0, 6, clean(f"Exporté le {datetime.now().strftime('%d/%m/%Y %H:%M')}"),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    for heading, body in sections:
        pdf.set_font(family, size=12)
        pdf.set_text_color(90, 60, 160)
        pdf.multi_cell(0, 7, clean(heading), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font(family, size=10)
        pdf.multi_cell(0, 5, clean(body or ""), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    path = export_path(stem, "pdf")
    pdf.output(str(path))
    return path


## @brief Write titled sections to a standalone HTML page.
#
# Every text is escaped: a message containing "<script>" is displayed, not
# run, by whoever opens the shared link.
#
# @param title Title of the document.
# @param sections List of (title, body) pairs.
# @param stem Start of the file name.
# @return Path of the created file.
def write_html(title, sections, stem):
    blocks = "\n".join(
        f'<section><h2>{html.escape(heading)}</h2><p>{html.escape(body or "")}</p></section>'
        for heading, body in sections
    )
    date = datetime.now().strftime("%d/%m/%Y %H:%M")
    page = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ --bg: #f7f7fb; --card: #fff; --text: #1d1b26; --muted: #6b6880; --accent: #6441a5; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #15141b; --card: #1f1d28; --text: #ecebf3; --muted: #a09cb4; --accent: #a98be0; }}
}}
body {{ margin: 0; background: var(--bg); color: var(--text);
       font: 16px/1.55 system-ui, sans-serif; }}
main {{ max-width: 760px; margin: 0 auto; padding: 24px 16px; }}
h1 {{ margin: 0 0 4px; }}
.date {{ color: var(--muted); margin-bottom: 24px; }}
section {{ background: var(--card); border-radius: 10px; padding: 12px 16px; margin: 12px 0; }}
h2 {{ font-size: 14px; color: var(--accent); margin: 0 0 6px; text-transform: uppercase; }}
p {{ margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }}
</style></head>
<body><main><h1>{html.escape(title)}</h1><div class="date">Exporté le {date}</div>
{blocks}
</main></body></html>
"""
    path = export_path(stem, "html")
    path.write_text(page, encoding="utf-8")
    return path


## @brief Export titled sections to one format.
#
# @param format "md"/"markdown", "pdf", "json" or "html".
# @param title Title of the document.
# @param sections List of (title, body) pairs.
# @param stem Start of the file name.
# @param raw Data written as-is by the JSON export.
# @return Confirmation or error message.
def export_sections(format, title, sections, stem, raw):
    match format:
        case "md" | "markdown":
            path = write_md(title, sections, stem)
        case "pdf":
            path = write_pdf(title, sections, stem)
        case "html":
            path = write_html(title, sections, stem)
        case "json":
            path = export_path(stem, "json")
            data = {
                "title": title,
                "exported_at": datetime.now().isoformat(timespec="seconds"),
                "content": raw,
            }
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        case _:
            return "Unknown format for exporting."
    return f"Export successful at '{path}'."


## @brief Export the conversation to Markdown.
#
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Confirmation message showing the path of the created file.
def export_md(messages):
    return export_sections("md", "Sensai CLI Chat conversation", conversation_sections(messages),
                           "SensaiChat", messages)


## @brief Export the conversation to PDF.
#
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Confirmation message showing the path of the created file.
def export_pdf(messages):
    return export_sections("pdf", "Sensai CLI Chat conversation", conversation_sections(messages),
                           "SensaiChat", messages)


## @brief Export the conversation to JSON, as sent to the model.
#
# @param messages Conversation history (list of "role"/"content" dicts).
# @return Confirmation message showing the path of the created file.
def export_json(messages):
    return export_sections("json", "Sensai CLI Chat conversation", conversation_sections(messages),
                           "SensaiChat", messages)


## @brief Address of this machine on the local network.
#
# No packet is sent: connecting a UDP socket only picks the outgoing
# interface, whose address is then read.
#
# @return IP address, or "localhost" if there is no network.
def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 80))
            return probe.getsockname()[0]
    except OSError:
        return "localhost"


## @brief Request handler that serves the exports folder, quietly.
class QuietHandler(SimpleHTTPRequestHandler):
    ## @brief Hide the request log, which would land in the middle of the chat.
    def log_message(self, format, *args):
        pass

    ## @brief Never list the folder: only someone with the link sees a page.
    def list_directory(self, path):
        self.send_error(404)
        return None


## @brief Start the share server if it is not running yet.
#
# A plain read-only HTTP server on the exports folder, in a daemon thread:
# no account, no auth, anyone who has the link (and can reach this machine)
# can open the page. Directory listing is disabled and file names are
# timestamped, so pages are not guessable by browsing.
#
# @param port Port to listen on.
# @return Base URL of the server, or None if the port is taken.
def start_share_server(port=DEFAULT_SHARE_PORT):
    global _server
    if _server is None:
        EXPORT_DIR.mkdir(exist_ok=True)
        handler = partial(QuietHandler, directory=str(EXPORT_DIR))
        try:
            _server = ThreadingHTTPServer(("0.0.0.0", port), handler)
        except OSError as error:
            print(f"[Share] port {port} indisponible : {error}")
            return None
        threading.Thread(target=_server.serve_forever, name="share-server", daemon=True).start()
    return f"http://{local_ip()}:{_server.server_address[1]}"


## @brief Publish a document as an HTML page and return its link.
#
# @param title Title of the page.
# @param sections List of (title, body) pairs.
# @param stem Start of the file name.
# @param port Port of the share server.
# @return Message with the link, or an error message.
def share(title, sections, stem, port=DEFAULT_SHARE_PORT):
    path = write_html(title, sections, stem)
    base = start_share_server(port)
    if base is None:
        return f"Page créée ({path}) mais le serveur de partage n'a pas pu démarrer."
    return (f"Lien de partage : {base}/{path.name}\n"
            f"(accessible sans compte depuis le réseau local ; "
            f"pour Internet : cloudflared tunnel --url http://localhost:{port})")
