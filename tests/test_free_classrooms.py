"""Unit tests for the free-classrooms finder."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

from dateutil import tz as dateutil_tz

from lectio_sync.event_model import LectioEvent
from lectio_sync.free_classrooms import (
    CLASSROOM_UNIVERSE,
    MODULE_GRID,
    _extract_rooms,
    _overlaps_module,
    build_busy_map,
    compute_free_room_events,
    generate_free_classrooms_ics,
)

_TZ = "Europe/Copenhagen"
_LOCAL_TZ = dateutil_tz.gettz(_TZ)


def _dt(h: int, m: int, d: date = date(2026, 2, 27)) -> datetime:
    return datetime.combine(d, time(h, m)).replace(tzinfo=_LOCAL_TZ)


def _make_event(
    start: datetime,
    end: datetime,
    room: str = "",
    description: str = "",
    status: str = "CONFIRMED",
) -> LectioEvent:
    return LectioEvent(
        uid=f"test-{start.strftime('%H%M')}-{room}@test",
        title="Test event",
        start=start,
        end=end,
        all_day_date=None,
        location=room,
        description=description,
        status=status,
    )


# ---------------------------------------------------------------------------
# _extract_rooms
# ---------------------------------------------------------------------------

class TestExtractRooms(unittest.TestCase):
    def test_lokale_singular(self) -> None:
        ev = _make_event(_dt(8, 15), _dt(9, 15), room="1.07",
                         description="Matematik\n27/2-2026 08:15 til 09:15\nLokale: 1.07")
        self.assertEqual(_extract_rooms(ev), ["1.07"])

    def test_lokaler_plural(self) -> None:
        ev = _make_event(_dt(8, 15), _dt(9, 15),
                         description="Matematik\n27/2-2026 08:15 til 09:15\nLokaler: 1.07, 2.03")
        rooms = _extract_rooms(ev)
        self.assertIn("1.07", rooms)
        self.assertIn("2.03", rooms)
        self.assertEqual(len(rooms), 2)

    def test_falls_back_to_location(self) -> None:
        ev = _make_event(_dt(8, 15), _dt(9, 15), room="2.03",
                         description="No room line here")
        self.assertEqual(_extract_rooms(ev), ["2.03"])

    def test_no_room_returns_empty(self) -> None:
        ev = _make_event(_dt(8, 15), _dt(9, 15), room="",
                         description="No room line here")
        self.assertEqual(_extract_rooms(ev), [])


# ---------------------------------------------------------------------------
# _overlaps_module
# ---------------------------------------------------------------------------

class TestOverlapsModule(unittest.TestCase):
    def _mod(self, mi: int):
        ms, me = MODULE_GRID[mi]
        return _dt(ms.hour, ms.minute), _dt(me.hour, me.minute)

    def test_exact_match_overlaps(self) -> None:
        ms, me = self._mod(0)
        self.assertTrue(_overlaps_module([(ms, me)], ms, me))

    def test_no_overlap_before_module(self) -> None:
        ms, me = self._mod(0)  # 08:15–09:15
        # event ends at 08:15 exactly — no overlap (strictly E > A)
        self.assertFalse(_overlaps_module([(_dt(7, 0), _dt(8, 15))], ms, me))

    def test_partial_overlap(self) -> None:
        ms, me = self._mod(0)  # 08:15–09:15
        self.assertTrue(_overlaps_module([(_dt(8, 0), _dt(8, 30))], ms, me))

    def test_no_overlap_after_module(self) -> None:
        ms, me = self._mod(0)  # 08:15–09:15
        self.assertFalse(_overlaps_module([(_dt(9, 15), _dt(10, 0))], ms, me))


# ---------------------------------------------------------------------------
# build_busy_map
# ---------------------------------------------------------------------------

class TestBuildBusyMap(unittest.TestCase):
    TODAY = date(2026, 2, 27)

    def test_room_in_universe_becomes_busy(self) -> None:
        ev = _make_event(_dt(8, 15), _dt(9, 15), room="1.07",
                         description="Lokale: 1.07")
        busy = build_busy_map([ev], self.TODAY, _TZ)
        self.assertTrue(len(busy["1.07"]) > 0)

    def test_room_not_in_universe_ignored(self) -> None:
        ev = _make_event(_dt(8, 15), _dt(9, 15), room="99.99",
                         description="Lokale: 99.99")
        busy = build_busy_map([ev], self.TODAY, _TZ)
        # No "99.99" key should exist (only CLASSROOM_UNIVERSE rooms)
        self.assertNotIn("99.99", busy)

    def test_cancelled_not_counted(self) -> None:
        ev = _make_event(_dt(8, 15), _dt(9, 15), room="1.07",
                         description="Lokale: 1.07", status="CANCELLED")
        busy = build_busy_map([ev], self.TODAY, _TZ)
        self.assertEqual(busy["1.07"], [])

    def test_all_day_not_counted(self) -> None:
        ev = LectioEvent(
            uid="allday@test",
            title="All day",
            start=None,
            end=None,
            all_day_date=self.TODAY,
            location="1.07",
            description="Lokale: 1.07",
            status="CONFIRMED",
        )
        busy = build_busy_map([ev], self.TODAY, _TZ)
        self.assertEqual(busy["1.07"], [])

    def test_different_day_not_counted(self) -> None:
        tomorrow = _dt(8, 15, d=date(2026, 2, 28))
        tomorrow_end = _dt(9, 15, d=date(2026, 2, 28))
        ev = _make_event(tomorrow, tomorrow_end, room="1.07", description="Lokale: 1.07")
        busy = build_busy_map([ev], self.TODAY, _TZ)
        self.assertEqual(busy["1.07"], [])

    def test_lokaler_multi_room(self) -> None:
        ev = _make_event(_dt(8, 15), _dt(9, 15),
                         description="Lokaler: 1.07, 2.03")
        busy = build_busy_map([ev], self.TODAY, _TZ)
        self.assertTrue(len(busy["1.07"]) > 0)
        self.assertTrue(len(busy["2.03"]) > 0)


# ---------------------------------------------------------------------------
# compute_free_room_events — core constraints
# ---------------------------------------------------------------------------

class TestComputeFreeRoomEvents(unittest.TestCase):
    TODAY = date(2026, 2, 27)

    def _busy_map_all_free(self) -> dict:
        return {r: [] for r in CLASSROOM_UNIVERSE}

    def _busy_map_one_room_busy_mod0(self, room: str) -> dict:
        bmap = self._busy_map_all_free()
        ms, me = MODULE_GRID[0]
        bmap[room] = [(_dt(ms.hour, ms.minute), _dt(me.hour, me.minute))]
        return bmap

    def test_never_more_than_4_overlapping(self) -> None:
        """At any single datetime during any module, ≤4 events overlap."""
        bmap = self._busy_map_all_free()
        events = compute_free_room_events(bmap, self.TODAY, _TZ)

        for ms_t, me_t in MODULE_GRID:
            mod_start = datetime.combine(self.TODAY, ms_t).replace(tzinfo=_LOCAL_TZ)
            mod_end = datetime.combine(self.TODAY, me_t).replace(tzinfo=_LOCAL_TZ)
            mid = mod_start + (mod_end - mod_start) / 2
            overlapping = [
                ev for ev in events
                if ev.start is not None
                and ev.end is not None
                and ev.start <= mid < ev.end
            ]
            self.assertLessEqual(
                len(overlapping), 4,
                f"More than 4 overlapping at module {ms_t}–{me_t}: {len(overlapping)}",
            )

    def test_busy_room_not_in_output(self) -> None:
        """A room that is busy for all 6 modules should never appear in the output."""
        bmap = self._busy_map_all_free()
        # Make 1.07 busy for every module
        for ms_t, me_t in MODULE_GRID:
            bmap["1.07"].append(
                (_dt(ms_t.hour, ms_t.minute), _dt(me_t.hour, me_t.minute))
            )
        events = compute_free_room_events(bmap, self.TODAY, _TZ)
        self.assertFalse(
            any(ev.location == "1.07" for ev in events),
            "Busy room 1.07 should not appear in free events.",
        )

    def test_consecutive_modules_preferred(self) -> None:
        """A room free for 2 consecutive modules should rank above one free for only 1."""
        # Leave only 2 rooms: "2.03" free for modules 0 and 1; "2.01" free for module 0 only.
        # All other rooms are busy every module.
        bmap: dict[str, list] = {}
        for r in CLASSROOM_UNIVERSE:
            full_busy = []
            for ms_t, me_t in MODULE_GRID:
                full_busy.append((_dt(ms_t.hour, ms_t.minute), _dt(me_t.hour, me_t.minute)))
            bmap[r] = full_busy

        # Free 2.03 for modules 0 and 1
        bmap["2.03"] = [
            (_dt(MODULE_GRID[2][0].hour, MODULE_GRID[2][0].minute),
             _dt(MODULE_GRID[5][1].hour, MODULE_GRID[5][1].minute))
        ]
        # Free 2.01 only for module 1 (busy at module 0, 2-5)
        ms0, me0 = MODULE_GRID[0]
        ms2, me5 = MODULE_GRID[2][0], MODULE_GRID[5][1]
        bmap["2.01"] = [
            (_dt(ms0.hour, ms0.minute), _dt(me0.hour, me0.minute)),
            (_dt(ms2.hour, ms2.minute), _dt(me5.hour, me5.minute)),
        ]

        events = compute_free_room_events(bmap, self.TODAY, _TZ)
        rooms_in_output = {ev.location for ev in events}
        # 2.03 should appear (longer run)
        self.assertIn("2.03", rooms_in_output)

    def test_free_events_have_valid_uid_format(self) -> None:
        bmap = self._busy_map_all_free()
        events = compute_free_room_events(bmap, self.TODAY, _TZ)
        for ev in events:
            self.assertIn("@lectio-sync", ev.uid, f"Bad UID: {ev.uid}")
            self.assertTrue(ev.uid.startswith("free-"), f"Bad UID prefix: {ev.uid}")

    def test_free_events_summary_format(self) -> None:
        bmap = self._busy_map_all_free()
        events = compute_free_room_events(bmap, self.TODAY, _TZ)
        for ev in events:
            self.assertTrue(
                ev.title.startswith("Free: "),
                f"Unexpected summary: {ev.title!r}",
            )

    def test_start_before_end(self) -> None:
        bmap = self._busy_map_all_free()
        events = compute_free_room_events(bmap, self.TODAY, _TZ)
        for ev in events:
            self.assertLess(ev.start, ev.end, f"start >= end for {ev.uid}")

    def test_no_events_when_all_rooms_fully_busy(self) -> None:
        bmap: dict[str, list] = {}
        for r in CLASSROOM_UNIVERSE:
            full_busy = []
            for ms_t, me_t in MODULE_GRID:
                full_busy.append((_dt(ms_t.hour, ms_t.minute), _dt(me_t.hour, me_t.minute)))
            bmap[r] = full_busy
        events = compute_free_room_events(bmap, self.TODAY, _TZ)
        self.assertEqual(events, [])

    def test_merging_adjacent_modules(self) -> None:
        """A room free across modules 0+1 should produce a single VEVENT, not two."""
        bmap = self._busy_map_all_free()
        events = compute_free_room_events(bmap, self.TODAY, _TZ)
        # Find an event for e.g. 1.07 that spans at least 2 modules
        long_events = [
            ev for ev in events
            if ev.start is not None and ev.end is not None
            and (ev.end - ev.start).total_seconds() > 3600
        ]
        # In an all-free scenario most rooms should have multi-module spans
        self.assertGreater(len(long_events), 0, "Expected merged multi-module events")


# ---------------------------------------------------------------------------
# Integration smoke-test using the real HTML fixture
# ---------------------------------------------------------------------------

class TestIntegrationWithFixture(unittest.TestCase):
    def _get_html_path(self, name: str) -> Path:
        repo = Path(__file__).resolve().parents[1]
        p = repo / name
        if not p.exists():
            self.skipTest(f"Fixture not found: {p}")
        return p

    def test_parse_and_free_classrooms_from_fixture(self) -> None:
        """End-to-end: parse real HTML, then run free-classrooms algorithm."""
        from lectio_sync.html_parser import parse_lectio_advanced_schedule_html
        from lectio_sync.free_classrooms import build_busy_map, compute_free_room_events

        html_path = self._get_html_path("Avanceret skema - Lectio - TEC.html")
        events = parse_lectio_advanced_schedule_html(
            html_path, "Europe/Copenhagen", sync_days_past=None, sync_days_future=None
        )
        self.assertGreater(len(events), 0)

        # Use any date from the fixture (just pick 3 dates to be robust)
        dates_seen = set()
        for ev in events:
            if ev.start:
                try:
                    d = ev.start.astimezone(dateutil_tz.gettz("Europe/Copenhagen")).date()
                    dates_seen.add(d)
                except Exception:
                    pass

        for test_date in list(dates_seen)[:3]:
            bmap = build_busy_map(events, test_date, "Europe/Copenhagen")
            free_evs = compute_free_room_events(bmap, test_date, "Europe/Copenhagen")
            # The core invariant: never more than 4 overlapping at any module midpoint
            local_tz = dateutil_tz.gettz("Europe/Copenhagen")
            for ms_t, me_t in MODULE_GRID:
                mod_start = datetime.combine(test_date, ms_t).replace(tzinfo=local_tz)
                mod_end = datetime.combine(test_date, me_t).replace(tzinfo=local_tz)
                mid = mod_start + (mod_end - mod_start) / 2
                overlapping = [
                    ev for ev in free_evs
                    if ev.start is not None
                    and ev.end is not None
                    and ev.start <= mid < ev.end
                ]
                self.assertLessEqual(
                    len(overlapping), 4,
                    f"date={test_date}, module {ms_t}–{me_t}: {len(overlapping)} overlapping",
                )


# ---------------------------------------------------------------------------
# generate_free_classrooms_ics – rolling window
# ---------------------------------------------------------------------------

class TestGenerateFreeClassroomsIcs(unittest.TestCase):
    """Tests for the multi-day rolling-window ICS generator."""

    # Monday 2026-03-09 is the next weekday after today (2026-03-08 Sunday)
    TODAY_MON = date(2026, 3, 9)   # Monday
    TODAY_SUN = date(2026, 3, 8)   # Sunday

    def test_skips_weekends(self) -> None:
        """Events must only be generated for weekdays (Mon–Fri)."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "free.ics"
            evs = generate_free_classrooms_ics(
                schedule_events=[],
                output_path=out,
                timezone_name=_TZ,
                today=self.TODAY_SUN,   # Sunday
                days_ahead=1,           # window: Sun + Mon → only Mon matters
            )
        event_dates = {
            ev.start.astimezone(dateutil_tz.gettz(_TZ)).date()
            for ev in evs
            if ev.start is not None
        }
        # Sunday must not appear; Monday must appear (all rooms free = events generated)
        self.assertNotIn(self.TODAY_SUN, event_dates)
        self.assertIn(self.TODAY_MON, event_dates)

    def test_covers_multiple_days(self) -> None:
        """With days_ahead=4 from a Monday, events must span Mon–Fri (5 days)."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "free.ics"
            evs = generate_free_classrooms_ics(
                schedule_events=[],
                output_path=out,
                timezone_name=_TZ,
                today=self.TODAY_MON,
                days_ahead=4,   # Mon through Fri
            )
        event_dates = {
            ev.start.astimezone(dateutil_tz.gettz(_TZ)).date()
            for ev in evs
            if ev.start is not None
        }
        expected_weekdays = {self.TODAY_MON + timedelta(days=i) for i in range(5)}
        self.assertEqual(event_dates, expected_weekdays)

    def test_days_ahead_zero_is_today_only(self) -> None:
        """days_ahead=0 reproduces the legacy single-day behaviour."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "free.ics"
            evs = generate_free_classrooms_ics(
                schedule_events=[],
                output_path=out,
                timezone_name=_TZ,
                today=self.TODAY_MON,
                days_ahead=0,
            )
        event_dates = {
            ev.start.astimezone(dateutil_tz.gettz(_TZ)).date()
            for ev in evs
            if ev.start is not None
        }
        self.assertEqual(event_dates, {self.TODAY_MON})

    def test_writes_ics_file(self) -> None:
        """Output ICS file must be created and non-empty."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "free.ics"
            generate_free_classrooms_ics(
                schedule_events=[],
                output_path=out,
                timezone_name=_TZ,
                today=self.TODAY_MON,
                days_ahead=0,
            )
            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("BEGIN:VCALENDAR", content)
            self.assertIn("BEGIN:VEVENT", content)


if __name__ == "__main__":
    unittest.main()
