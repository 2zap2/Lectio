from __future__ import annotations

from pathlib import Path
import unittest
import pytest

_FIXTURE = Path(__file__).resolve().parents[1] / "Avanceret skema - Lectio - TEC.html"

from lectio_sync.html_parser import parse_lectio_advanced_schedule_html


@pytest.mark.skipif(not _FIXTURE.exists(), reason="Local Lectio fixture not present")
class HtmlParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html_path = _FIXTURE

    def test_parses_fixture_without_window_filter(self) -> None:
        events = parse_lectio_advanced_schedule_html(
            self.html_path,
            "Europe/Copenhagen",
            sync_days_past=None,
            sync_days_future=None,
            debug=False,
        )
        self.assertGreater(len(events), 0)

    def test_cancelled_dropped_by_default(self) -> None:
        events = parse_lectio_advanced_schedule_html(
            self.html_path,
            "Europe/Copenhagen",
            sync_days_past=None,
            sync_days_future=None,
            emit_cancelled_events=False,
            debug=False,
        )
        self.assertTrue(all(e.status == "CONFIRMED" for e in events))

    def test_cancelled_can_be_emitted(self) -> None:
        events = parse_lectio_advanced_schedule_html(
            self.html_path,
            "Europe/Copenhagen",
            sync_days_past=None,
            sync_days_future=None,
            emit_cancelled_events=True,
            debug=False,
        )
        self.assertTrue(any(e.status == "CANCELLED" for e in events))


if __name__ == "__main__":
    unittest.main()
