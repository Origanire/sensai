# Ces tests vérifient les exports des conversations et des rapports.

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.core import export

MESSAGES = [
    {"role": "user", "content": "salut <script>alert(1)</script>"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "get_stream_report", "arguments": {}}}]},
    {"role": "tool", "content": "Jeu : Celeste", "tool_name": "get_stream_report"},
    {"role": "assistant", "content": "On joue à Celeste « ce soir » 🎮"},
]


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(export, "EXPORT_DIR", Path(self.folder.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)

    def exported(self, extension):
        return next(Path(self.folder.name).glob(f"*.{extension}"))

    def test_tool_calls_are_readable(self):
        sections = export.conversation_sections(MESSAGES)
        self.assertIn("get_stream_report", sections[1][1])
        self.assertEqual(sections[2][0], "Outil (get_stream_report)")

    def test_json_keeps_the_raw_messages(self):
        self.assertIn("successful", export.export_json(MESSAGES))
        data = json.loads(self.exported("json").read_text(encoding="utf-8"))
        self.assertEqual(data["content"], MESSAGES)

    def test_markdown_and_pdf_are_written(self):
        export.export_md(MESSAGES)
        export.export_pdf(MESSAGES)
        self.assertIn("Celeste", self.exported("md").read_text(encoding="utf-8"))
        self.assertTrue(self.exported("pdf").read_bytes().startswith(b"%PDF"))

    def test_html_escapes_content(self):
        export.write_html("t", export.conversation_sections(MESSAGES), "Chat")
        page = self.exported("html").read_text(encoding="utf-8")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_unknown_format(self):
        self.assertIn("Unknown", export.export_sections("docx", "t", [], "x", []))


if __name__ == "__main__":
    unittest.main()
