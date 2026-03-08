"""Free classroom finder.

Selects up to 4 free rooms per module slot and writes a separate ICS feed
(``docs/free_classrooms.ics`` by default).

Algorithm overview
------------------
1.  Take all *non-cancelled, timed* events from today.
2.  For each event extract the room(s) it occupies (handles both ``Lokale:``
    and ``Lokaler:`` tooltip lines, as well as the ``LectioEvent.location``
    fallback).
3.  Project busy intervals onto the fixed 6-module grid to get a
    free/busy boolean per (room, module) pair.
4.  For each module index *i*, rank all free rooms by how many consecutive
    modules they remain free (descending), break ties alphabetically, take
    top 4.
5.  Merge adjacent module slots where the same room is consistently in the
    top-4 selection into a single VEVENT spanning the combined time window.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from dateutil import tz as dateutil_tz

from lectio_sync.event_model import LectioEvent
from lectio_sync.ical_writer import write_icalendar


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The fixed 6-module school day grid.  Only these windows are considered.
MODULE_GRID: list[tuple[time, time]] = [
    (time(8, 15),  time(9, 15)),
    (time(9, 20),  time(10, 20)),
    (time(10, 30), time(11, 30)),
    (time(12, 10), time(13, 10)),
    (time(13, 20), time(14, 20)),
    (time(14, 30), time(15, 30)),
]

#: Rooms that are part of the "classroom universe" we track.
CLASSROOM_UNIVERSE: list[str] = [
    "0.75",
    "0.76",
    "0.77",
    "1.02",
    "1.03a",
    "1.07",
    "1.09",
    "1.10",
    "1.59",
    "1.60",
    "1.61",
    "1.62",
    "1.64",
    "1.65",
    "2.01",
    "2.03",
    "2.04",
    "2.05",
    "2.27",
    "2.29",
    "2.31",
]


# ---------------------------------------------------------------------------
# Room extraction from events
# ---------------------------------------------------------------------------

def _extract_rooms(event: LectioEvent) -> list[str]:
    """Return all rooms mentioned in the event's description and/or location.

    Handles:
    - ``Lokale: X``  (singular – one room)
    - ``Lokaler: X, Y, Z``  (plural – multiple rooms, comma-separated)
    - Fallback: ``event.location`` when neither tooltip line is found.
    """
    rooms: list[str] = []
    for line in (event.description or "").split("\n"):
        stripped = line.strip()
        lo = stripped.lower()
        if lo.startswith("lokale:"):
            room = stripped.split(":", 1)[1].strip()
            if room:
                rooms.append(room)
        elif lo.startswith("lokaler:"):
            raw = stripped.split(":", 1)[1].strip()
            for r in raw.split(","):
                r = r.strip()
                if r:
                    rooms.append(r)
    # Fallback: use the location field if we found nothing in the description.
    if not rooms and event.location:
        rooms.append(event.location)
    return rooms


# ---------------------------------------------------------------------------
# Busy-map builder
# ---------------------------------------------------------------------------

def build_busy_map(
    events: list[LectioEvent],
    today: date,
    timezone_name: str,
) -> dict[str, list[tuple[datetime, datetime]]]:
    """Return ``{room: [(start, end), ...]}`` for *today* using the classroom universe.

    Only timed, non-cancelled events are considered.  Multi-room events
    (``Lokaler:``) mark *each* listed room as busy.
    """
    local_tz = dateutil_tz.gettz(timezone_name)
    if local_tz is None:
        raise ValueError(f"Unknown timezone: {timezone_name!r}")

    # Case-insensitive lookup: lower(room) → canonical room name
    universe_lower: dict[str, str] = {r.lower(): r for r in CLASSROOM_UNIVERSE}

    busy: dict[str, list[tuple[datetime, datetime]]] = {r: [] for r in CLASSROOM_UNIVERSE}

    for ev in events:
        # Only timed, non-cancelled events count as "busy".
        if ev.is_all_day or ev.start is None or ev.end is None:
            continue
        if (ev.status or "").upper() == "CANCELLED":
            continue

        # Restrict to today.
        try:
            ev_date = ev.start.astimezone(local_tz).date()
        except Exception:
            ev_date = ev.start.date()  # type: ignore[union-attr]
        if ev_date != today:
            continue

        for room in _extract_rooms(ev):
            canonical = universe_lower.get(room.lower())
            if canonical:
                busy[canonical].append((ev.start, ev.end))

    return busy


# ---------------------------------------------------------------------------
# Module overlap helper
# ---------------------------------------------------------------------------

def _overlaps_module(
    busy_intervals: list[tuple[datetime, datetime]],
    mod_start: datetime,
    mod_end: datetime,
) -> bool:
    """Return True if any busy interval overlaps the module window [mod_start, mod_end)."""
    for s, e in busy_intervals:
        if s < mod_end and e > mod_start:
            return True
    return False


# ---------------------------------------------------------------------------
# Free-room selection and event generation
# ---------------------------------------------------------------------------

def compute_free_room_events(
    busy_map: dict[str, list[tuple[datetime, datetime]]],
    today: date,
    timezone_name: str,
) -> list[LectioEvent]:
    """Produce a list of ``LectioEvent`` objects representing free classroom suggestions.

    At any module boundary, at most 4 rooms are selected.  Adjacent selections
    of the same room are merged into a single VEVENT.
    """
    local_tz = dateutil_tz.gettz(timezone_name)
    if local_tz is None:
        raise ValueError(f"Unknown timezone: {timezone_name!r}")

    # Convert the module grid to aware datetimes for today.
    mod_windows: list[tuple[datetime, datetime]] = [
        (
            datetime.combine(today, s).replace(tzinfo=local_tz),
            datetime.combine(today, e).replace(tzinfo=local_tz),
        )
        for s, e in MODULE_GRID
    ]

    # Precompute free[room][module_index] → bool
    free: dict[str, list[bool]] = {
        room: [
            not _overlaps_module(busy_map[room], ms, me)
            for ms, me in mod_windows
        ]
        for room in CLASSROOM_UNIVERSE
    }

    # For each module index i, count consecutive free modules starting at i.
    def _consec_from(room: str, start_i: int) -> int:
        count = 0
        for j in range(start_i, len(MODULE_GRID)):
            if free[room][j]:
                count += 1
            else:
                break
        return count

    # selected[i] = ordered list of rooms selected at module slot i (≤4 rooms).
    selected: list[list[str]] = []
    for i in range(len(MODULE_GRID)):
        free_at_i = [r for r in CLASSROOM_UNIVERSE if free[r][i]]
        if not free_at_i:
            selected.append([])
            continue
        ranked = sorted(free_at_i, key=lambda r: (-_consec_from(r, i), r))
        selected.append(ranked[:4])

    # Merge consecutive slots where the same room appears in selected[].
    events: list[LectioEvent] = []

    for room in CLASSROOM_UNIVERSE:
        in_span = False
        span_start_idx = 0
        for i in range(len(MODULE_GRID)):
            is_selected = room in selected[i]
            if is_selected and not in_span:
                in_span = True
                span_start_idx = i
            elif not is_selected and in_span:
                in_span = False
                events.append(
                    _make_free_event(room, today, mod_windows, span_start_idx, i - 1)
                )
        if in_span:
            events.append(
                _make_free_event(room, today, mod_windows, span_start_idx, len(MODULE_GRID) - 1)
            )

    events.sort(key=lambda e: (e.start, e.location))  # type: ignore[arg-type]
    return events


def _make_free_event(
    room: str,
    today: date,
    mod_windows: list[tuple[datetime, datetime]],
    start_idx: int,
    end_idx: int,
) -> LectioEvent:
    """Build a single ``LectioEvent`` for a free-room span."""
    span_start = mod_windows[start_idx][0]
    span_end = mod_windows[end_idx][1]
    start_str = span_start.strftime("%H:%M")
    end_str = span_end.strftime("%H:%M")
    uid = (
        f"free-{today.strftime('%Y%m%d')}-{room.replace('.', '')}"
        f"-{span_start.strftime('%H%M')}-{span_end.strftime('%H%M')}"
        f"@lectio-sync"
    )
    return LectioEvent(
        uid=uid,
        title=f"Free: {room}",
        start=span_start,
        end=span_end,
        all_day_date=None,
        location=room,
        description=f"Free classroom: {room}\nAvailable {start_str}–{end_str}",
        status="CONFIRMED",
    )


# ---------------------------------------------------------------------------
# Top-level convenience function
# ---------------------------------------------------------------------------

def generate_free_classrooms_ics(
    schedule_events: list[LectioEvent],
    output_path: Path,
    timezone_name: str,
    today: Optional[date] = None,
    days_ahead: int = 6,
) -> list[LectioEvent]:
    """Build and write the free-classrooms ICS from already-parsed schedule events.

    Generates free-room events for a rolling window of weekdays starting from
    *today* and covering the next *days_ahead* calendar days (weekends skipped).
    This ensures the feed remains useful even if the sync misses a day.

    Parameters
    ----------
    schedule_events:
        All events from the normal schedule feed (the entire window is fine;
        only events matching each target date are used internally).
    output_path:
        Where to write the ``free_classrooms.ics``.  Parent dirs are created.
    timezone_name:
        IANA timezone name (e.g. ``"Europe/Copenhagen"``).
    today:
        Override "today" (useful in tests).  Defaults to the current local date.
    days_ahead:
        Number of additional calendar days to include after *today* (default 6).
        Weekends are skipped; free-room events are only generated for Mon–Fri.

    Returns
    -------
    list[LectioEvent]
        The free-room events that were written.
    """
    local_tz = dateutil_tz.gettz(timezone_name)
    if local_tz is None:
        raise ValueError(f"Unknown timezone: {timezone_name!r}")

    if today is None:
        today = datetime.now(local_tz).date()

    all_free_events: list[LectioEvent] = []
    for offset in range(days_ahead + 1):
        target_date = today + timedelta(days=offset)
        # School is only open Mon–Fri (isoweekday: 1=Mon … 5=Fri).
        if target_date.isoweekday() > 5:
            continue
        busy_map = build_busy_map(schedule_events, target_date, timezone_name)
        day_events = compute_free_room_events(busy_map, target_date, timezone_name)
        all_free_events.extend(day_events)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_icalendar(all_free_events, output_path, cal_name="Ledige lokaler")

    return all_free_events
