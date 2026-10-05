import json

import pytest

from src.core import export as export_module
from src.core.export import build_markdown_string, export_md, export_json, export_pdf, write_export_file
from src.commands import commands

MESSAGES = [
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": "hi there"},
]

@pytest.fixture
def export_dir(tmp_path, monkeypatch):
    """Redirect exports away from the real exports/ folder."""
    monkeypatch.setattr(export_module, "EXPORT_DIR", tmp_path)
    return tmp_path

def test_build_markdown_renders_one_section_per_message():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]

    result = build_markdown_string(messages)

    assert "## user\nhello" in result
    assert "## assistant\nhi there" in result

def test_build_markdown_starts_with_titled_header():
    messages = [{"role": "user", "content": "hello"}]

    result = build_markdown_string(messages)

    assert result.startswith("# Sensai CLI Chat conversation export ")

def test_build_markdown_keeps_content_verbatim():
    messages = [{"role": "user", "content": "line1\nline2"}]

    result = build_markdown_string(messages)

    assert "## user\nline1\nline2\n\n" in result

def test_build_markdown_empty_history_is_header_only():
    result = build_markdown_string([])

    assert result.startswith("# Sensai CLI Chat conversation export ")
    assert "## " not in result


def test_write_export_file_creates_file_with_text_content(export_dir):
    path = write_export_file("hello", ".md")

    assert path.exists()
    assert path.read_text(encoding="utf-8") == "hello"

def test_write_export_file_writes_binary_content_unchanged(export_dir):
    content = b"\x89PNG\r\n\x1a\nfake binary"

    path = write_export_file(content, ".pdf")

    assert path.read_bytes() == content

def test_write_export_file_appends_counter_on_collision(export_dir):
    first = write_export_file("first", ".md")
    second = write_export_file("second", ".md")

    assert first.read_text(encoding="utf-8") == "first"
    assert second.stem.endswith("_1")
    assert second.read_text(encoding="utf-8") == "second"

def test_export_md_writes_file_with_sections(export_dir):
    export_md(MESSAGES)

    files = list(export_dir.glob("*.md"))
    assert len(files) == 1
    assert "## user\nhello" in files[0].read_text(encoding="utf-8")

def test_export_json_round_trips_messages(export_dir):
    export_json(MESSAGES)

    files = list(export_dir.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8")) == MESSAGES

def test_export_pdf_starts_with_magic_bytes(export_dir):
    export_pdf(MESSAGES)

    files = list(export_dir.glob("*.pdf"))
    assert len(files) == 1
    assert files[0].read_bytes()[:5] == b"%PDF-"

def test_commands_rejects_empty_conversation():
    assert commands("/export md", []) == "Nothing to export, the conversation is empty."

def test_commands_rejects_unknown_format():
    assert commands("/export csv", MESSAGES) == "Unknown format for exporting."

def test_commands_shows_help_without_format():
    result = commands("/export", MESSAGES)

    assert "Export function usage" in result

def test_commands_rejects_unknown_command():
    assert commands("/hi", MESSAGES) == "Unknown command."
