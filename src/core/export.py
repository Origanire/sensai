# Ce module exporte les conversations et rapports, puis peut les partager par une page HTTP sans authentification.

import html
import json
import socket
import threading
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fpdf import FPDF

# Les exports sont enregistrés dans ce dossier du projet, quel que soit le dossier de lancement.
EXPORT_DIR = Path(__file__).resolve().parents[2] / "exports"
# Cette police permet d’afficher les accents et les caractères spéciaux dans les PDF.
PDF_FONTS = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)
# Ces noms rendent les rôles de conversation lisibles dans les exports.
ROLE_NAMES = {
    "user": "Toi",
    "assistant": "Sensai",
    "system": "Système",
    "tool": "Outil",
}
# Ce port est utilisé pour le partage si aucun autre n’est configuré.
DEFAULT_SHARE_PORT = 8765

# Cette variable contient le serveur de partage en cours, ou None.
_server = None


# Cette fonction explique les formats disponibles et l’utilisation de /export.
def export_help() -> str:
    message = "Export function usage :\n" \
    "/export [format]         exporte la conversation\n" \
    "/export [format] report  exporte le compte-rendu du stream\n" \
    "format : md (markdown), pdf (adobe pdf), json (javascript object notation), html\n" \
    "/share [report]          publie la conversation (ou le compte-rendu) par un lien\n"
    return message


# Cette fonction prépare un nom de fichier daté dans le dossier des exports.
def export_path(stem, extension):
    EXPORT_DIR.mkdir(exist_ok=True)
    name = datetime.now().strftime(f"{stem}_%Y-%m-%d_%H-%M-%S.{extension}")
    return EXPORT_DIR / name


# Cette fonction transforme la conversation en sections pour réutiliser les mêmes exports que pour les rapports.
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


# Cette fonction écrit les sections du document dans un fichier Markdown.
def write_md(title, sections, stem):
    path = export_path(stem, "md")
    text = f"# {title}\n\n_Exporté le {datetime.now().strftime('%d/%m/%Y %H:%M')}_\n\n"
    text += "".join(f"## {heading}\n{body}\n\n" for heading, body in sections)
    path.write_text(text, encoding="utf-8")
    return path


# Cette fonction crée le PDF avec une police compatible si possible. Les caractères non pris en charge sont remplacés pour éviter un échec.
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


# Cette fonction crée une page HTML autonome et protège les textes pour qu’un message ne puisse pas exécuter du code.
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


# Cette fonction choisit le format d’export et renvoie le résultat de l’opération.
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


# Cette fonction exporte la conversation en Markdown et indique le fichier créé.
def export_md(messages):
    return export_sections("md", "Sensai CLI Chat conversation", conversation_sections(messages),
                           "SensaiChat", messages)


# Cette fonction exporte la conversation en PDF et indique le fichier créé.
def export_pdf(messages):
    return export_sections("pdf", "Sensai CLI Chat conversation", conversation_sections(messages),
                           "SensaiChat", messages)


# Cette fonction exporte les échanges en JSON, dans le format utilisé par le modèle.
def export_json(messages):
    return export_sections("json", "Sensai CLI Chat conversation", conversation_sections(messages),
                           "SensaiChat", messages)


# Cette fonction retrouve l’adresse locale de la machine sans envoyer de paquet, ou utilise localhost si nécessaire.
def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 80))
            return probe.getsockname()[0]
    except OSError:
        return "localhost"


# Cette classe sert les fichiers exportés sans encombrer le terminal de messages.
class QuietHandler(SimpleHTTPRequestHandler):
    # On masque le journal des requêtes pour ne pas interrompre l’affichage du chat.
    def log_message(self, format, *args):
        pass

    # On interdit l’affichage du dossier pour ne pas exposer la liste des exports.
    def list_directory(self, path):
        self.send_error(404)
        return None


# Cette fonction lance le partage HTTP en lecture seule. Les fichiers sont accessibles aux personnes qui connaissent le lien et peuvent joindre la machine.
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


# Cette fonction exporte le document en HTML et renvoie son lien de partage.
def share(title, sections, stem, port=DEFAULT_SHARE_PORT):
    path = write_html(title, sections, stem)
    base = start_share_server(port)
    if base is None:
        return f"Page créée ({path}) mais le serveur de partage n'a pas pu démarrer."
    return (f"Lien de partage : {base}/{path.name}\n"
            f"(accessible sans compte depuis le réseau local ; "
            f"pour Internet : cloudflared tunnel --url http://localhost:{port})")
