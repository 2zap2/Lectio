---
title: "Fix free-classrooms calendar: stale HTML shows all rooms free"
author: "GitHub Copilot"
date: "2026-03-15T00:00:00Z"
status: draft
estimated_effort: "2–4h"
---

# Fix free-classrooms calendar: stale HTML shows all rooms free

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries,
Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.
There is no PLANS.md in this repository; this document follows the planning skill at
`.agents/skills/planning/SKILL.md` directly.


## Purpose / Big Picture

The free-classrooms ICS feed (`docs/free_classrooms.ics`) is supposed to show up to 4
classrooms that are genuinely free during each of the 6 school modules on a given day.
Instead it always shows rooms 0.75, 0.76, 0.77, and 1.02 as free from 08:15 to 15:30,
regardless of what is actually happening that day.

After this fix, the feed will only emit free-room events for dates that are actually
covered by the schedule HTML that was last fetched. When a date is not covered (e.g.
because the HTML is stale from a previous week), no free-room events will be emitted
for that date — so the user sees nothing rather than misleading "all rooms free" data.
The feed also continues to correctly exclude rooms with scheduled lessons and correctly
merges consecutive free modules into a single calendar event.


## Root Cause

There are two compounding problems:

**Problem 1 — Stale HTML, zero busy rooms, alphabetical fallback.**
The HTML file (`Avanceret skema - Lectio - TEC.html`) only covers one school week. The
rolling-window generator (`generate_free_classrooms_ics`) asks for events covering
"today through today + 6 days". If the HTML is from a previous week (e.g. Feb 2-6)
and today is Mar 15, `build_busy_map` finds zero events for Mar 15 and returns an
empty busy map. An empty busy map means ALL 21 rooms are free for ALL 6 modules. The
selection algorithm then picks the top-4 alphabetically — which are always 0.75, 0.76,
0.77, 1.02.

**Problem 2 — Full-day span from merging.**
When a room is free for all 6 consecutive modules, the merge logic produces a single
VEVENT spanning 08:15–15:30. This is correct behaviour for a truly all-day-free room,
but it is fed by Problem 1: the room is only "all-day free" because no events were
found at all for that date.

The fix for Problem 1 eliminates Problem 2's symptoms automatically.


## Repository Orientation

All source files live under `src/lectio_sync/`. The one file you will change is:

- `src/lectio_sync/free_classrooms.py` — contains `generate_free_classrooms_ics`,
  `build_busy_map`, and `compute_free_room_events`. This is the only file that needs
  to change.

The test file is:

- `tests/test_free_classrooms.py` — you will add tests here.

The HTML fixture used in tests is:

- `Avanceret skema - Lectio - TEC.html` (root of the repo) — covers week of Feb 2–6, 2026.

The program entry point is `src/lectio_sync/cli.py`. It calls
`generate_free_classrooms_ics(events, free_out, timezone_name)` where `events` is the
full list of `LectioEvent` objects already parsed from the HTML. You do NOT need to
change `cli.py`.


## Definitions (plain language)

- Module: one of the 6 fixed teaching slots — 08:15–09:15, 09:20–10:20, 10:30–11:30,
  12:10–13:10, 13:20–14:20, 14:30–15:30. The `MODULE_GRID` constant in
  `src/lectio_sync/free_classrooms.py` already defines these exactly.
- Busy map: a dict `{room_name: [(start_datetime, end_datetime), ...]}` built by
  `build_busy_map`. Rooms with no events have an empty list — which currently reads as
  "free all day" even when it means "no data at all".
- Covered date: a date for which at least one timed, non-cancelled event exists in the
  parsed events list. Only covered dates have reliable busy/free information.
- Free event: a `LectioEvent` representing a free classroom suggestion emitted to the
  ICS feed. Its `start` and `end` align exactly with the module grid boundaries.
- Rolling window: `generate_free_classrooms_ics` loops over `days_ahead + 1` calendar
  days starting from `today`. Weekends are skipped.


## The Fix

### Step 1 — Compute the set of "covered dates" from the parsed events

In `generate_free_classrooms_ics`, before the per-day loop, collect the set of dates
for which the schedule actually has data. A date is covered if at least one timed,
non-cancelled event starts on that date (after converting the start time to local
timezone).

Add this helper inside `generate_free_classrooms_ics`, right after the `today`
assignment:

    # Dates that have at least one real scheduled event (so busy data is trustworthy).
    covered_dates: set[date] = set()
    for ev in schedule_events:
        if ev.is_all_day or ev.start is None:
            continue
        if (ev.status or "").upper() == "CANCELLED":
            continue
        try:
            ev_local_date = ev.start.astimezone(local_tz).date()
        except Exception:
            ev_local_date = ev.start.date()
        covered_dates.add(ev_local_date)

### Step 2 — Skip dates not covered by the HTML

Inside the existing `for offset in range(days_ahead + 1):` loop, after the weekend
check, add an early-continue for uncovered dates:

    if target_date not in covered_dates:
        continue   # no schedule data for this date; don't emit misleading "all free"

This single check is the entire runtime fix. No other logic changes.

### What this looks like in context

The relevant section of `generate_free_classrooms_ics` (starting around line 315 of
`src/lectio_sync/free_classrooms.py`) currently reads:

    all_free_events: list[LectioEvent] = []
    for offset in range(days_ahead + 1):
        target_date = today + timedelta(days=offset)
        # School is only open Mon–Fri (isoweekday: 1=Mon … 5=Fri).
        if target_date.isoweekday() > 5:
            continue
        busy_map = build_busy_map(schedule_events, target_date, timezone_name)
        day_events = compute_free_room_events(busy_map, target_date, timezone_name)
        all_free_events.extend(day_events)

After the fix it must read:

    # Dates that have at least one real scheduled event (so busy data is trustworthy).
    covered_dates: set[date] = set()
    for ev in schedule_events:
        if ev.is_all_day or ev.start is None:
            continue
        if (ev.status or "").upper() == "CANCELLED":
            continue
        try:
            ev_local_date = ev.start.astimezone(local_tz).date()
        except Exception:
            ev_local_date = ev.start.date()
        covered_dates.add(ev_local_date)

    all_free_events: list[LectioEvent] = []
    for offset in range(days_ahead + 1):
        target_date = today + timedelta(days=offset)
        # School is only open Mon–Fri (isoweekday: 1=Mon … 5=Fri).
        if target_date.isoweekday() > 5:
            continue
        # Only emit free-room suggestions for dates the HTML actually covers.
        # If the HTML is from a previous week, skip silently rather than showing
        # all rooms as free (a misleading artefact of an empty busy map).
        if target_date not in covered_dates:
            continue
        busy_map = build_busy_map(schedule_events, target_date, timezone_name)
        day_events = compute_free_room_events(busy_map, target_date, timezone_name)
        all_free_events.extend(day_events)


## Tests to Add

Add a new test class `TestCoveredDatesGuard` in `tests/test_free_classrooms.py` after
the existing `TestComputeFreeRoomEvents` class. All tests use the existing `_dt` and
`_make_event` helpers already defined at the top of that file.

**Test 1 — Stale HTML yields empty output.**
Call `generate_free_classrooms_ics` with events whose only dates are in the past (use
date(2026, 2, 2) which is in the HTML fixture), and set `today` to a weekday with no
events (e.g. date(2026, 3, 16), a Monday). With `days_ahead=0`, the output list must
be empty.

    def test_stale_html_yields_no_free_events(self) -> None:
        """When today has no schedule data, no free-room events should be emitted."""
        import tempfile
        from pathlib import Path
        # One event exists, but on a completely different date (Feb 2, a Monday)
        ev = _make_event(
            _dt(8, 15, d=date(2026, 2, 2)),
            _dt(9, 15, d=date(2026, 2, 2)),
            room="1.07",
            description="Lokale: 1.07",
        )
        # today = 2026-03-16 (Monday) – not in the event list at all
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "free.ics"
            evs = generate_free_classrooms_ics(
                schedule_events=[ev],
                output_path=out,
                timezone_name=_TZ,
                today=date(2026, 3, 16),
                days_ahead=0,
            )
        self.assertEqual(evs, [], "Expected empty output for a date not in the schedule")

**Test 2 — Covered date does produce output.**
Call `generate_free_classrooms_ics` with a single event on Feb 2 (a Monday in the
fixture), and set `today=date(2026, 2, 2)` with `days_ahead=0`. One room (1.07) is
busy for module 0; all other 20 rooms are free. The output must be non-empty (at least
one free-room event exists).

    def test_covered_date_emits_free_events(self) -> None:
        """A date that has schedule data should still produce free-room events."""
        import tempfile
        from pathlib import Path
        ev = _make_event(
            _dt(8, 15, d=date(2026, 2, 2)),
            _dt(9, 15, d=date(2026, 2, 2)),
            room="1.07",
            description="Lokale: 1.07",
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "free.ics"
            evs = generate_free_classrooms_ics(
                schedule_events=[ev],
                output_path=out,
                timezone_name=_TZ,
                today=date(2026, 2, 2),
                days_ahead=0,
            )
        self.assertGreater(len(evs), 0, "Expected free-room events for a covered date")

**Test 3 — Only covered dates within the window emit free events.**
Call `generate_free_classrooms_ics` with events for Monday Feb 2 only, today set to
Feb 2, and `days_ahead=4` (Mon–Fri). Only Feb 2 has scheduled data; Tue–Fri have none.
The set of dates in the output events must be exactly `{date(2026, 2, 2)}`.

    def test_only_covered_dates_in_output(self) -> None:
        """With days_ahead=4, only dates that have schedule data emit events."""
        import tempfile
        from pathlib import Path
        ev = _make_event(
            _dt(8, 15, d=date(2026, 2, 2)),
            _dt(9, 15, d=date(2026, 2, 2)),
            room="1.07",
            description="Lokale: 1.07",
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "free.ics"
            evs = generate_free_classrooms_ics(
                schedule_events=[ev],
                output_path=out,
                timezone_name=_TZ,
                today=date(2026, 2, 2),
                days_ahead=4,
            )
        output_dates = {
            e.start.astimezone(dateutil_tz.gettz(_TZ)).date()
            for e in evs if e.start is not None
        }
        self.assertEqual(output_dates, {date(2026, 2, 2)})

Note: the `dateutil_tz` import is already at the top of the test file as
`from dateutil import tz as dateutil_tz`.

Note: `_dt` in the test file accepts an optional `d` keyword argument for the date
(see line `def _dt(h: int, m: int, d: date = date(2026, 2, 27)) -> datetime:`). Use
it to specify Feb 2 as shown above.


## Existing Tests That Must Continue to Pass

Run the full suite before and after your changes:

    Working directory: C:\Users\Arthu\Lectio
    $ py -m pytest tests/test_free_classrooms.py -v
    Expected: 27 passed (all existing tests)

After adding the new tests:

    $ py -m pytest tests/test_free_classrooms.py -v
    Expected: 30 passed (27 existing + 3 new)

Pay particular attention to the rolling-window tests in `TestGenerateFreeClassroomsIcs`
— specifically `test_covers_multiple_days` and `test_days_ahead_zero_is_today_only`.
Those tests pass an empty `schedule_events=[]` list and set `today` to a known Monday
(Mar 9, 2026). With the fix in place, those tests will now also receive empty output
because an empty events list has no covered dates. The assertions in those tests check
for specific dates appearing in the output events; they will need to be updated to
assert that when `schedule_events=[]` the output is empty, OR the tests should be
changed to include at least one dummy scheduled event on the target date.

Inspect those tests before running:

- `test_covers_multiple_days` — currently asserts output spans Mon–Fri starting
  today_mon. After the fix, with `schedule_events=[]`, the output will be empty. You
  MUST update this test so that it passes schedule events covering those dates.
- `test_days_ahead_zero_is_today_only` — similarly asserts exactly one day in output
  with `schedule_events=[]`. Must be updated.
- `test_skips_weekends` — asserts Sunday does not appear. Will also be affected.
- `test_writes_ics_file` — checks the ICS file is created and has `BEGIN:VEVENT`. With
  empty schedule events and the fix, the ICS file will still be created but will have
  no VEVENT blocks. Either add a dummy event or change the assertion.

### How to update the rolling-window tests

The simplest fix for each is to add a dummy busy event on the relevant date(s) so that
`covered_dates` includes those dates. For example, to make `test_covers_multiple_days`
work with 5 weekday covered dates, build a list of 5 dummy events:

    dummy_events = [
        _make_event(
            _dt(8, 15, d=self.TODAY_MON + timedelta(days=i)),
            _dt(9, 15, d=self.TODAY_MON + timedelta(days=i)),
            room="1.07",
            description="Lokale: 1.07",
        )
        for i in range(5)   # Mon, Tue, Wed, Thu, Fri
    ]

Then pass `schedule_events=dummy_events` to `generate_free_classrooms_ics`.

For `test_writes_ics_file`, just pass one such dummy event.

For `test_skips_weekends`, pass one dummy event on the Sunday and one on the Monday,
and verify that Sunday does not appear in output.


## Acceptance Criteria

The fix is complete when:

1. `py -m pytest tests/test_free_classrooms.py -v` passes all 30 tests (27 existing
   updated + 3 new).
2. Manually running the parser against the real fixture produces the right result:
   - Events on dates the HTML covers (Feb 2–6 2026) produce sensible free-room events
     where rooms with scheduled lessons are correctly excluded.
   - Request to generate free rooms for dates NOT in the HTML (e.g., today, March 15)
     produces zero free-room events.
3. The free-room calendar no longer shows 0.75, 0.76, 0.77, 1.02 free from 08:15 to
   15:30 on every day.

To manually verify criterion 2, run from `C:\Users\Arthu\Lectio`:

    py -c "
    from lectio_sync.html_parser import parse_lectio_advanced_schedule_html
    from lectio_sync.free_classrooms import generate_free_classrooms_ics
    from datetime import date
    from pathlib import Path

    events = parse_lectio_advanced_schedule_html(
        Path('Avanceret skema - Lectio - TEC.html'),
        'Europe/Copenhagen',
        sync_days_past=None, sync_days_future=None,
    )
    print(f'Parsed {len(events)} schedule events')

    # Test with date covered by HTML (Feb 2, Monday)
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'free.ics'
        evs = generate_free_classrooms_ics(events, out, 'Europe/Copenhagen',
                                           today=date(2026, 2, 2), days_ahead=0)
        print(f'Feb 2 (covered): {len(evs)} free-room events')
        for e in evs[:4]:
            print(f'  {e.location}: {e.start.strftime(\"%H:%M\")} – {e.end.strftime(\"%H:%M\")}')

    # Test with today (should be empty if HTML is stale)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'free.ics'
        evs2 = generate_free_classrooms_ics(events, out, 'Europe/Copenhagen',
                                            today=date.today(), days_ahead=0)
        print(f'Today ({date.today()}, not covered): {len(evs2)} free-room events')
    "

Expected output:
    Parsed 48 schedule events
    Feb 2 (covered): <N > 0 free-room events
      (some rooms listed with module-aligned times, NOT 08:15-15:30 unless genuinely free all day)
    Today (2026-03-15, not covered): 0 free-room events


## Progress

- [x] Implemented the covered-dates guard in `generate_free_classrooms_ics`
- [x] Updated the 4 affected rolling-window tests in `TestGenerateFreeClassroomsIcs`
- [x] Added 3 new tests in a new `TestCoveredDatesGuard` class
- [x] Ran `py -m pytest tests/test_free_classrooms.py -v` and confirmed 30 passes
- [x] Ran manual verification script: covered date emitted events; uncovered date emitted zero events


## Surprises & Discoveries

- The rolling-window tests relied on `schedule_events=[]` producing synthetic "all free" output across weekdays.
- With covered-date guarding, those tests must provide at least one timed event on each expected output date.


## Decision Log

- Chose to implement the guard only in `generate_free_classrooms_ics` and leave `build_busy_map`/`compute_free_room_events` unchanged to keep behaviour scoped and predictable.
- Kept "covered date" definition strict: timed + non-cancelled event date in local timezone.


## Outcomes & Retrospective

- The stale-HTML failure mode is removed: uncovered dates now emit no free-room events instead of misleading all-day free-room blocks.
- Targeted suite `tests/test_free_classrooms.py` passes with 30/30 after test updates and additions.

2026-03-15: Chose to fix at the `generate_free_classrooms_ics` level (skip uncovered
dates entirely) rather than at `compute_free_room_events` level (emit nothing when busy
map is empty) because the rolling-window function has the right view of "which dates
have data" without needing to change the lower-level building blocks. This keeps
`compute_free_room_events` purely functional and easier to unit-test.

2026-03-15: Did NOT change `build_busy_map` or `compute_free_room_events` because those
functions are correct — an empty busy map correctly means "no busy rooms". The mistake
was calling them for dates with no data and treating the result as meaningful.

2026-03-15: Did NOT add an explicit "no data for today" VEVENT placeholder to the feed.
The user's requirement is simply to show rooms that ARE free; showing nothing on a stale
day is the correct behaviour and avoids false information.


## Outcomes & Retrospective

(fill in upon completion)
