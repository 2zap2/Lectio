"""Fetch and build a complete calendar generation through one local browser."""
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

from bs4 import BeautifulSoup

from .browser_session import InvalidLectioPage, LoginRequired, browser_context, ensure_authenticated
from .cookie_refresh import _is_authenticated_schedule, _is_logged_in_page, _is_login_page
from .free_classrooms import generate_free_classrooms_ics
from .html_parser import parse_lectio_advanced_schedule_html_text, parse_lectio_assignments_html_text
from .ical_writer import write_icalendar
from .lectio_fetch import build_student_url, build_week_url, iter_weeks_for_window


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != "www.lectio.dk"
            or not parsed.path.startswith("/lectio/") or parsed.username or parsed.password):
        raise ValueError("Only HTTPS www.lectio.dk school URLs are supported")


def validate_page(html: str, requested_url: str, final_url: str, *, assignments=False) -> None:
    """Accept real empty tables, reject login, partial and redirected week pages."""
    final = urlparse(final_url)
    requested = urlparse(requested_url)
    if final.hostname == "security-check.stil.dk" or (
        not _is_logged_in_page(html) and _is_login_page(html)
    ):
        raise LoginRequired("Lectio requires local login or verification")
    if (final.scheme, final.netloc, final.path.lower()) != (
        requested.scheme, requested.netloc, requested.path.lower()
    ):
        raise InvalidLectioPage("Lectio redirected away from the requested data page")
    expected, actual = parse_qs(requested.query), parse_qs(final.query)
    for key in ("week", "studentsel", "lokalesel"):
        if key in expected and actual.get(key) != expected[key]:
            raise InvalidLectioPage("Lectio returned a different week or selection")
    soup = BeautifulSoup(html, "html.parser")
    table_id = ("s_m_Content_Content_ExerciseGV" if assignments
                else "m_Content_SkemaMedNavigation_skema_skematabel")
    if not _is_logged_in_page(html) or soup.find("table", id=table_id) is None:
        raise InvalidLectioPage("The authenticated Lectio data table is missing")


def fetch_page(page, url: str, *, assignments=False) -> str:
    validate_url(url)
    response = page.goto(url, timeout=30_000, wait_until="domcontentloaded")
    if response is None or response.status >= 400:
        raise InvalidLectioPage("Lectio returned an unsuccessful HTTP response")
    html = page.content()
    validate_page(html, url, page.url, assignments=assignments)
    return html


def build_calendars(output: Path, *, schedule_url: str, rooms_url: str,
                    additional_student_ids: list[str], assignments_url: str | None = None,
                    profile: Path | None = None, interactive=False,
                    days_past=7, days_future=90, timezone="Europe/Copenhagen") -> list[str]:
    from .cli import _filter_events

    validate_url(schedule_url)
    validate_url(rooms_url)
    parsed = urlparse(schedule_url)
    if assignments_url is None:
        school_path = parsed.path.rsplit("/", 1)[0]
        assignments_url = urlunparse(parsed._replace(path=school_path + "/OpgaverElev.aspx", query="", fragment=""))
    validate_url(assignments_url)
    weeks = iter_weeks_for_window(timezone_name=timezone, days_past=days_past, days_future=days_future)
    output.mkdir(parents=True, exist_ok=True)
    files = []
    with browser_context(profile, interactive=interactive) as context:
        page = context.pages[0] if context.pages else context.new_page()
        ensure_authenticated(page, schedule_url, interactive=interactive)

        def schedules(url):
            events = {}
            for week in weeks:
                html = fetch_page(page, build_week_url(url, week))
                parsed_events = parse_lectio_advanced_schedule_html_text(
                    html, timezone, sync_days_past=days_past, sync_days_future=days_future,
                    emit_cancelled_events=False,
                )
                for event in parsed_events:
                    events.setdefault(event.uid, event)
            return sorted(events.values(), key=lambda e: e.uid)

        students = [("calendar.ics", schedule_url, None)]
        for student_id in dict.fromkeys(additional_student_ids):
            students.append((f"calendar-{student_id}.ics", build_student_url(schedule_url, student_id),
                             f"Lectio - elev {student_id}"))
        for name, url, cal_name in students:
            events = _filter_events(schedules(url))
            write_icalendar(events, output / name, cal_name=cal_name)
            files.append(name)
            print(f"Built {name}: {len(events)} events from {len(weeks)} verified weeks")
        assignments = parse_lectio_assignments_html_text(
            fetch_page(page, assignments_url, assignments=True), timezone)
        write_icalendar(assignments, output / "assignments.ics", cal_name="lectio opgaver")
        files.append("assignments.ics")
        generate_free_classrooms_ics(schedules(rooms_url), output / "free_classrooms.ics",
                                     timezone, days_ahead=1)
        files.append("free_classrooms.ics")
    return files
