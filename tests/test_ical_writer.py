from __future__ import annotations

from datetime import date, datetime
import tempfile
import unittest
from pathlib import Path

from dateutil import tz

from lectio_sync.event_model import LectioEvent
from lectio_sync.ical_writer import build_icalendar, write_icalendar


class ICalWriterTests(unittest.TestCase):
    def test_writes_status_cancelled(self) -> None:
        event = LectioEvent(
            uid="uid-1@lectio.dk",
            title="Cancelled Class",
            start=datetime(2026, 2, 2, 9, 0, 0, tzinfo=tz.gettz("Europe/Copenhagen")),
            end=datetime(2026, 2, 2, 10, 0, 0, tzinfo=tz.gettz("Europe/Copenhagen")),
            all_day_date=None,
            location="2.29",
            description="Aflyst!",
            status="CANCELLED",
        )

        ics = build_icalendar([event])
        self.assertIn("STATUS:CANCELLED", ics)

    def test_escapes_and_folds_description(self) -> None:
        long_text = "Line 1, with comma; and semicolon\\ and newline\n" + ("x" * 120)
        event = LectioEvent(
            uid="uid-2@lectio.dk",
            title="Test",
            start=None,
            end=None,
            all_day_date=date(2026, 2, 6),
            location="",
            description=long_text,
        )

        ics = build_icalendar([event])
        self.assertIn("DESCRIPTION:Line 1\\, with comma\\; and semicolon\\\\ and newline\\n", ics)
        self.assertIn("\r\n ", ics)

    def test_all_day_dtend_is_exclusive(self) -> None:
        """RFC5545: all-day DTEND must be the day AFTER DTSTART (exclusive)."""
        event = LectioEvent(
            uid="uid-allday@lectio.dk",
            title="All Day Event",
            start=None,
            end=None,
            all_day_date=date(2026, 2, 26),
            location="",
            description="",
        )

        ics = build_icalendar([event])
        self.assertIn("DTSTART;VALUE=DATE:20260226", ics)
        self.assertIn("DTEND;VALUE=DATE:20260227", ics)

    def test_cal_name_written_as_x_wr_calname(self) -> None:
        ics = build_icalendar([], cal_name="lectio opgaver")
        self.assertIn("X-WR-CALNAME:lectio opgaver", ics)

    def test_cal_name_absent_when_not_set(self) -> None:
        ics = build_icalendar([])
        self.assertNotIn("X-WR-CALNAME", ics)

    def test_crlf_line_endings(self) -> None:
        """RFC 5545 §3.1: every line must be terminated by CRLF (\\r\\n)."""
        event = LectioEvent(
            uid="uid-crlf@lectio.dk",
            title="Test",
            start=datetime(2026, 3, 3, 9, 0, 0, tzinfo=tz.gettz("Europe/Copenhagen")),
            end=datetime(2026, 3, 3, 10, 0, 0, tzinfo=tz.gettz("Europe/Copenhagen")),
            all_day_date=None,
            location="1.07",
            description="Some description",
        )
        ics = build_icalendar([event])
        # Every line break must be \r\n — no bare \n should remain.
        self.assertIn("\r\n", ics)
        for i, ch in enumerate(ics):
            if ch == "\n":
                self.assertGreater(i, 0, "ICS output starts with bare \\n")
                self.assertEqual(
                    ics[i - 1], "\r",
                    "Found bare \\n (LF without preceding \\r) in ICS output",
                )

    def test_write_icalendar_preserves_crlf(self) -> None:
        """write_icalendar() must write binary \\r\\n so git/OS cannot silently strip \\r."""
        event = LectioEvent(
            uid="uid-write-crlf@lectio.dk",
            title="Write Test",
            start=datetime(2026, 3, 3, 8, 15, 0, tzinfo=tz.gettz("Europe/Copenhagen")),
            end=datetime(2026, 3, 3, 9, 15, 0, tzinfo=tz.gettz("Europe/Copenhagen")),
            all_day_date=None,
            location="2.03",
            description="",
        )
        with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as tf:
            tmp = Path(tf.name)
        try:
            write_icalendar([event], tmp)
            raw = tmp.read_bytes()
            self.assertIn(b"\r\n", raw, "ICS file written without CRLF line endings")
            # No bare LF (0x0a not preceded by 0x0d)
            for i, byte in enumerate(raw):
                if byte == 0x0A:
                    self.assertGreater(i, 0, "ICS file starts with bare LF byte")
                    self.assertEqual(
                        raw[i - 1], 0x0D,
                        f"Bare LF at byte offset {i} in written ICS file",
                    )
        finally:
            tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
