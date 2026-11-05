from __future__ import annotations

import unittest
from datetime import date

from lectio_sync.cli import _filter_events
from lectio_sync.event_model import LectioEvent


def _all_day_event(title: str) -> LectioEvent:
    return LectioEvent(
        uid=f"{title}@test",
        title=title,
        start=None,
        end=None,
        all_day_date=date(2026, 8, 2),
        location="",
        description="",
    )


class FilterEventsTests(unittest.TestCase):
    def test_excludes_all_day_events_referencing_2g_in_either_case(self) -> None:
        events = [
            _all_day_event("2.g: Activity"),
            _all_day_event("2.G: Activity"),
            _all_day_event("3.g: Activity"),
        ]

        filtered = _filter_events(events)

        self.assertEqual([event.title for event in filtered], ["3.g: Activity"])


if __name__ == "__main__":
    unittest.main()
