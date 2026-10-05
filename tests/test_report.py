## @file test_report.py
# @brief Unit tests of the living stream report (M4).

import tempfile
import unittest
from pathlib import Path

from src.tools.report import (
    DEFAULT_SECTIONS,
    apply_update,
    generate_update,
    load_report,
    update_report_from_event,
)
from tests.fakes import FakeClient


class GenerateUpdateTest(unittest.TestCase):
    def test_event_type_is_mapped_to_section_and_action(self):
        client = FakeClient(json_answers=[{"type": "changement_de_jeu", "content": "Hades 2"}])
        update = generate_update("on lance Hades 2", dict(DEFAULT_SECTIONS), client)
        self.assertEqual(update, {"section": "jeu_actuel", "action": "replace",
                                  "content": "Hades 2"})

    def test_unknown_type_or_empty_content_is_rejected(self):
        client = FakeClient(json_answers=[{"type": "pirate", "content": "x"},
                                          {"type": "moment_fort", "content": "  "}])
        self.assertIsNone(generate_update("x", dict(DEFAULT_SECTIONS), client))
        self.assertIsNone(generate_update("x", dict(DEFAULT_SECTIONS), client))

    def test_model_failure_gives_none(self):
        self.assertIsNone(generate_update("x", dict(DEFAULT_SECTIONS), FakeClient()))


class ApplyUpdateTest(unittest.TestCase):
    def test_append_replaces_placeholder_then_adds_lines(self):
        report = dict(DEFAULT_SECTIONS)
        apply_update(report, {"section": "stats", "action": "append", "content": "100 viewers"})
        apply_update(report, {"section": "stats", "action": "append", "content": "5 subs"})
        self.assertEqual(report["stats"], "- 100 viewers\n- 5 subs")

    def test_highlights_get_a_timestamp(self):
        report = dict(DEFAULT_SECTIONS)
        apply_update(report, {"section": "moments_forts", "action": "append",
                              "content": "boss battu"}, timestamp=0)
        self.assertRegex(report["moments_forts"], r"^- \d\dh\d\d : boss battu$")

    def test_only_the_target_section_changes_and_edit_is_journaled(self):
        report = dict(DEFAULT_SECTIONS)
        before = dict(report)
        apply_update(report, {"section": "jeu_actuel", "action": "replace", "content": "Celeste"})
        for key in DEFAULT_SECTIONS:
            if key != "jeu_actuel":
                self.assertEqual(report[key], before[key])
        self.assertEqual(report["_journal"][-1]["section"], "jeu_actuel")

    def test_none_update_changes_nothing(self):
        report = dict(DEFAULT_SECTIONS)
        self.assertEqual(apply_update(report, None), DEFAULT_SECTIONS)


class UpdateFromEventTest(unittest.TestCase):
    def test_report_file_is_updated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "report.json")
            client = FakeClient(json_answers=[{"type": "moment_fort", "content": "Malenia battue"}])
            _, update = update_report_from_event("on a battu Malenia", client, path)
            self.assertEqual(update["section"], "moments_forts")
            self.assertIn("Malenia battue", load_report(path)["moments_forts"])

    def test_report_is_unchanged_when_the_model_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "report.json")
            report, update = update_report_from_event("x", FakeClient(), path)
            self.assertIsNone(update)
            self.assertEqual(report, DEFAULT_SECTIONS)


if __name__ == "__main__":
    unittest.main()
