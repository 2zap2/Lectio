from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from dateutil import tz

from lectio_sync.event_model import LectioEvent


_TABLE_ID = "m_Content_SkemaMedNavigation_skema_skematabel"
_DATE_LINE_RE = re.compile(
    r"(?P<day>\d{1,2})/(?P<month>\d{1,2})-(?P<year>\d{4})\s+"
    r"(?:(?P<all_day>Hele\s+dagen|All\s+day)|(?P<start>\d{2}:\d{2})\s+til\s+(?P<end>\d{2}:\d{2}))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _TooltipParsed:
    title: str
    start: Optional[datetime]
    end: Optional[datetime]
    all_day_date: Optional[date]
    room: str
    description: str
    effective_date: Optional[date]


def _normalize_text(raw: str) -> str:
    if raw is None:
        return ""

    text = raw.strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    text = unicodedata.normalize("NFC", text)

    text = re.sub(r"<[^>]+>", "", text)

    lines = [ln.rstrip() for ln in text.split("\n")]

    cleaned: list[str] = []
    previous_blank = False
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:]
        if stripped == "":
            if previous_blank:
                continue
            previous_blank = True
            cleaned.append("")
            continue
        previous_blank = False
        cleaned.append(stripped)

    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()

    return "\n".join(cleaned)


def _first_meaningful_line(lines: list[str]) -> Optional[str]:
    for ln in lines:
        if ln.strip() != "":
            return ln.strip()
    return None


def _line_looks_like_datetime(line: str) -> bool:
    return _DATE_LINE_RE.search(line.strip()) is not None


def _parse_date_from_data_date(raw: str) -> date:
    try:
        year_s, month_s, day_s = raw.split("-")
        return date(int(year_s), int(month_s), int(day_s))
    except Exception as exc:
        raise ValueError(f"Invalid data-date value: {raw!r}") from exc


def _parse_tooltip(
    tooltip_text: str,
    content_fallback_title: str,
    inherited_date: Optional[date],
    timezone_name: str,
) -> _TooltipParsed:
    normalized = _normalize_text(tooltip_text)
    lines = normalized.split("\n") if normalized else []

    meaningful = [ln.strip() for ln in lines if ln.strip() != ""]
    title_line = _first_meaningful_line(meaningful) or ""

    if title_line.lower() in {"ændret!", "changed!", "aflyst!", "cancelled!", "canceled!"}:
        meaningful = meaningful[1:]
        title_line = _first_meaningful_line(meaningful) or ""

    title = title_line
    if title == "" or _line_looks_like_datetime(title):
        title = _normalize_text(content_fallback_title).split("\n")[0].strip() or "(Untitled)"

    parsed_date_line: Optional[re.Match[str]] = None
    for idx, ln in enumerate(lines):
        m = _DATE_LINE_RE.search(ln)
        if m:
            parsed_date_line = m
            break

    local_tz = tz.gettz(timezone_name)
    if local_tz is None:
        raise ValueError(f"Unknown timezone: {timezone_name}")

    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None
    all_day: Optional[date] = None
    effective_date: Optional[date] = None

    if parsed_date_line:
        day = int(parsed_date_line.group("day"))
        month = int(parsed_date_line.group("month"))
        year = int(parsed_date_line.group("year"))
        effective_date = date(year, month, day)

        if parsed_date_line.group("all_day"):
            all_day = effective_date
        else:
            start_s = parsed_date_line.group("start")
            end_s = parsed_date_line.group("end")
            if start_s and end_s:
                sh, sm = [int(x) for x in start_s.split(":")]
                eh, em = [int(x) for x in end_s.split(":")]
                start_dt = datetime.combine(effective_date, time(sh, sm)).replace(tzinfo=local_tz)
                end_dt = datetime.combine(effective_date, time(eh, em)).replace(tzinfo=local_tz)
                if end_dt <= start_dt:
                    end_dt = end_dt + timedelta(days=1)

    if effective_date is None:
        effective_date = inherited_date

    room = ""
    room_index: Optional[int] = None
    for idx, ln in enumerate(lines):
        if ln.strip().lower().startswith("lokale:"):
            room_index = idx
            room = ln.split(":", 1)[1].strip() if ":" in ln else ""
            break

    return _TooltipParsed(
        title=title,
        start=start_dt,
        end=end_dt,
        all_day_date=all_day,
        room=room,
        description=normalized,
        effective_date=effective_date,
    )


def _looks_cancelled(tooltip: str, content_text: str) -> bool:
    combined = (tooltip + "\n" + content_text).lower()
    # Heuristic keywords. If you provide exact wording, we can tighten this.
    return any(
        kw in combined
        for kw in [
            "aflyst",
            "aflyses",
            "cancelled",
            "canceled",
            "annulleret",
            "annullered",
        ]
    )


def _is_cancelled_event(tooltip: str, content_text: str, classes: list[str]) -> bool:
    class_set = {c.strip().lower() for c in classes if c and c.strip()}
    if {
        "s2cancelled",
        "cancelled",
        "canceled",
        "aflyst",
    }.intersection(class_set):
        return True

    tooltip_first = _first_meaningful_line(_normalize_text(tooltip).split("\n") if tooltip else [])
    if tooltip_first and tooltip_first.strip().lower() in {
        "aflyst!",
        "aflyst",
        "cancelled!",
        "cancelled",
        "canceled!",
        "canceled",
        "annulleret!",
        "annulleret",
    }:
        return True

    return _looks_cancelled(tooltip, content_text)


def _locate_schedule_table(soup: BeautifulSoup):
    table = soup.find("table", id=_TABLE_ID)
    if table is not None:
        return table, f"id={_TABLE_ID}"

    candidate_tables = []
    for candidate in soup.find_all("table"):
        if candidate.find("td", attrs={"data-date": True}) is None:
            continue
        if candidate.find("a", class_=lambda c: c and "s2skemabrik" in c.split()) is None:
            continue
        candidate_tables.append(candidate)

    if candidate_tables:
        return candidate_tables[0], "fallback=table with td[data-date] + a.s2skemabrik"

    signatures: list[str] = []
    for idx, t in enumerate(soup.find_all("table"), start=1):
        table_id = (t.get("id") or "").strip() or "(no-id)"
        classes = " ".join(t.get("class") or []) or "(no-class)"
        has_date_td = t.find("td", attrs={"data-date": True}) is not None
        has_bricks = t.find("a", class_=lambda c: c and "s2skemabrik" in c.split()) is not None
        signatures.append(
            f"#{idx}: id={table_id}, class={classes}, has_date_cells={has_date_td}, has_bricks={has_bricks}"
        )
        if idx >= 10:
            break

    details = " | ".join(signatures) if signatures else "No <table> elements found"
    raise ValueError(
        f"Could not locate Lectio schedule table. Tried id={_TABLE_ID!r} and fallback selector. Found tables: {details}"
    )


def _build_uid(brikid: Optional[str], tooltip: str, effective_date: date) -> str:
    if brikid:
        return f"{brikid}@lectio.dk"
    stable_source = _normalize_text(tooltip) + "\n" + effective_date.isoformat()
    digest = hashlib.sha256(stable_source.encode("utf-8")).hexdigest()[:24]
    return f"lectio-{digest}@lectio.dk"


def _compose_title(base_title: str, tooltip: str, room: str) -> str:
    # Requirement: title should include subject + teacher + room when available.
    # We extract teachers from lines like "Lærer:" / "Lærere:" and append room.
    t = _normalize_text(tooltip)
    teachers: str = ""
    for ln in t.split("\n"):
        low = ln.lower()
        if low.startswith("lærer:") or low.startswith("lærere:"):
            teachers = ln.split(":", 1)[1].strip() if ":" in ln else ""
            break

    parts = [base_title.strip()]
    if teachers:
        parts.append(teachers)
    if room:
        parts.append(room)
    return " - ".join([p for p in parts if p])


def parse_lectio_advanced_schedule_html(
    html_path: Path,
    timezone_name: str,
    *,
    sync_days_past: int | None = None,
    sync_days_future: int | None = None,
    emit_cancelled_events: bool = False,
    debug: bool = False,
) -> list[LectioEvent]:
    html = html_path.read_text(encoding="utf-8", errors="replace")
    return parse_lectio_advanced_schedule_html_text(
        html,
        timezone_name,
        sync_days_past=sync_days_past,
        sync_days_future=sync_days_future,
        emit_cancelled_events=emit_cancelled_events,
        debug=debug,
    )


def parse_lectio_advanced_schedule_html_text(
    html: str,
    timezone_name: str,
    *,
    sync_days_past: int | None = None,
    sync_days_future: int | None = None,
    emit_cancelled_events: bool = False,
    debug: bool = False,
) -> list[LectioEvent]:
    # Use Python's builtin parser to avoid lxml/bs4 deprecation warnings
    # while remaining robust for the Lectio HTML used in tests.
    soup = BeautifulSoup(html, "html.parser")

    table, table_selector_used = _locate_schedule_table(soup)

    events: list[LectioEvent] = []
    seen_uids: set[str] = set()

    bricks_found = 0
    skipped_empty = 0
    skipped_cancelled = 0
    skipped_missing_date = 0
    skipped_missing_time = 0
    skipped_duplicate_uid = 0
    duplicate_uid_examples: list[str] = []
    cancelled_emitted = 0

    for a in table.find_all("a", class_=lambda c: c and "s2skemabrik" in c.split()):
        bricks_found += 1

        inherited_date: Optional[date] = None
        parent_td = a.find_parent("td")
        if parent_td is not None and parent_td.has_attr("data-date"):
            raw_data_date = parent_td.get("data-date")
            if raw_data_date:
                try:
                    inherited_date = _parse_date_from_data_date(raw_data_date)
                except ValueError:
                    inherited_date = None

        tooltip_raw = a.get("data-tooltip") or ""
        tooltip = _normalize_text(tooltip_raw)

        content_div = a.find("div", class_="s2skemabrikcontent")
        content_text = _normalize_text(content_div.get_text("\n") if content_div else a.get_text("\n"))

        if tooltip.strip() == "" and content_text.strip() == "":
            skipped_empty += 1
            continue

        # Cancellation can also show up as CSS classes.
        class_list = [str(c) for c in (a.get("class") or [])]
        is_cancelled = _is_cancelled_event(tooltip, content_text, class_list)
        if is_cancelled and not emit_cancelled_events:
            skipped_cancelled += 1
            continue

        parsed = _parse_tooltip(tooltip, content_text, inherited_date, timezone_name)
        effective_date = parsed.effective_date
        if effective_date is None:
            skipped_missing_date += 1
            continue

        # Fault tolerant: we can only use tooltip-provided date/time.
        if parsed.all_day_date is None and (parsed.start is None or parsed.end is None):
            skipped_missing_time += 1
            continue

        brikid = a.get("data-brikid")
        uid = _build_uid(brikid, tooltip, effective_date)
        if uid in seen_uids:
            skipped_duplicate_uid += 1
            if len(duplicate_uid_examples) < 5:
                duplicate_uid_examples.append(uid)
            continue
        seen_uids.add(uid)

        title = _compose_title(parsed.title, tooltip, parsed.room)

        # Description must include full tooltip text (normalized).
        description = parsed.description

        events.append(
            LectioEvent(
                uid=uid,
                title=title,
                start=parsed.start,
                end=parsed.end,
                all_day_date=parsed.all_day_date,
                location=parsed.room,
                description=description,
                status="CANCELLED" if is_cancelled else "CONFIRMED",
            )
        )
        if is_cancelled:
            cancelled_emitted += 1

    pre_filter_count = len(events)

    if debug:
        print(
            "Parse stats: "
            f"selector={table_selector_used}, "
            f"bricks={bricks_found}, "
            f"added={len(events)}, "
            f"emit_cancelled_events={emit_cancelled_events}, "
            f"cancelled_emitted={cancelled_emitted}, "
            f"skipped_empty={skipped_empty}, "
            f"skipped_cancelled={skipped_cancelled}, "
            f"skipped_missing_date={skipped_missing_date}, "
            f"skipped_missing_time={skipped_missing_time}, "
            f"skipped_duplicate_uid={skipped_duplicate_uid}"
        )
        if duplicate_uid_examples:
            print("Duplicate UID examples (first 5): " + ", ".join(duplicate_uid_examples))

    # Keep deterministic ordering
    def _sort_key(ev: LectioEvent):
        if ev.is_all_day:
            return (0, ev.all_day_date or date.min, ev.title, ev.uid)
        return (1, (ev.start or datetime.min.replace(tzinfo=tz.UTC)), ev.title, ev.uid)

    events.sort(key=_sort_key)

    if sync_days_past is not None or sync_days_future is not None:
        past = 7 if sync_days_past is None else sync_days_past
        future = 90 if sync_days_future is None else sync_days_future
        local_tz = tz.gettz(timezone_name)
        if local_tz is None:
            raise ValueError(f"Unknown timezone: {timezone_name}")
        today = datetime.now(local_tz).date()
        window_start = today - timedelta(days=past)
        window_end = today + timedelta(days=future)

        def _event_date(ev: LectioEvent) -> Optional[date]:
            if ev.is_all_day:
                return ev.all_day_date
            if ev.start is None:
                return None
            try:
                return ev.start.astimezone(local_tz).date()
            except Exception:
                return ev.start.date()

        events = [
            ev
            for ev in events
            if (d := _event_date(ev)) is not None and window_start <= d <= window_end
        ]

        if debug:
            print(
                "Window filter: "
                f"today={today.isoformat()}, "
                f"window_start={window_start.isoformat()}, "
                f"window_end={window_end.isoformat()}, "
                f"before={pre_filter_count}, "
                f"after={len(events)}"
            )
    elif debug:
        print("Window filter: disabled (both sync_days_past and sync_days_future are None)")

    return events
