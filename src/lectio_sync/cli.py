from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urlparse

from lectio_sync.config import load_config_from_env_with_overrides
from lectio_sync.free_classrooms import generate_free_classrooms_ics
from lectio_sync.html_parser import (
    parse_lectio_advanced_schedule_html,
    parse_lectio_advanced_schedule_html_text,
    parse_lectio_assignments_html,
    parse_lectio_assignments_html_text,
)
from lectio_sync.ical_writer import write_icalendar
from lectio_sync.lectio_fetch import fetch_weeks_html_with_diagnostics, fetch_html_with_diagnostics, iter_weeks_for_window


def _redact_url_for_logs(url: str) -> str:
    """Return scheme://host/path (query and fragment removed)."""
    try:
        p = urlparse(url)
        scheme = p.scheme or "https"
        netloc = p.netloc or "(no-host)"
        path = p.path or "/"
        return f"{scheme}://{netloc}{path}"
    except Exception:
        return "(unparseable-url)"


_AUTH_REDIRECT_DOMAINS = (
    "security-check.stil.dk",
    "logind.lectio.dk",
)


def _is_auth_redirect(final_url: str) -> bool:
    """Return True when the final URL is a known Lectio/STIL authentication or security-check page."""
    low = (final_url or "").lower()
    return any(domain in low for domain in _AUTH_REDIRECT_DOMAINS)


def _classify_fetched_page(html: str) -> str:
    low = (html or "").lower()
    if "m_content_skemamednavigation_skema_skematabel" in low:
        return "schedule-table-present"
    if "s2skemabrik" in low:
        return "schedule-bricks-present"
    if "mitid" in low:
        return "mitid/login"
    if "log ind" in low or "login" in low:
        return "login"
    if "adgang" in low and "nægt" in low:
        return "access-denied"
    if "error" in low and "request" in low:
        return "error-page"
    if "<html" not in low and "<!doctype" not in low:
        return "not-html-or-undecoded"
    return "unknown-html"


def _filter_events(events: list) -> list:
    """Apply relevance filters before writing to the calendar feed.

    Full-day events: keep only if the title contains at least one of the
    class/group keywords (2.g, 2.G, 3.g, 3.G, Alle, alle).

    Non-full-day events: drop if the title contains any of the club
    keywords (Armwrestling-klubben, Armwrestling, armwrestling-klubben,
    armwrestling, LEGO klubben).
    """
    ALL_DAY_KEEP = ("2.g", "2.G", "3.g", "3.G", "Alle", "alle")
    NON_FULL_DAY_DROP = (
        "Armwrestling-klubben",
        " Armwrestling",
        "armwrestling-klubben",
        " armwrestling",
        "LEGO klubben",
    )

    filtered = []
    for ev in events:
        if ev.is_all_day:
            if any(kw in ev.title for kw in ALL_DAY_KEEP):
                filtered.append(ev)
        else:
            if not any(kw in ev.title for kw in NON_FULL_DAY_DROP):
                filtered.append(ev)
    return filtered


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Lectio Advanced Schedule HTML to .ics")
    parser.add_argument("--html", type=Path, help="Path to Lectio HTML file (overrides LECTIO_HTML_PATH)")
    parser.add_argument("--out", type=Path, help="Output .ics path (overrides OUTPUT_ICS_PATH)")
    parser.add_argument("--tz", type=str, help="Timezone (overrides LECTIO_TIMEZONE)")
    parser.add_argument(
        "--fetch",
        action="store_true",
        help=(
            "Fetch schedule HTML from Lectio using an existing session cookie instead of reading a local HTML file. "
            "Requires --schedule-url (or LECTIO_SCHEDULE_URL) and LECTIO_COOKIE_HEADER."
        ),
    )
    parser.add_argument(
        "--schedule-url",
        type=str,
        help=(
            "Base Lectio schedule URL (SkemaAvanceret.aspx). The 'week' query parameter will be overwritten. "
            "You can also set LECTIO_SCHEDULE_URL."
        ),
    )
    parser.add_argument(
        "--cookie-header",
        type=str,
        help=(
            "Cookie header to use for fetching (advanced). Prefer setting LECTIO_COOKIE_HEADER as an environment variable "
            "or GitHub Secret so it is not visible in process lists/logs."
        ),
    )
    parser.add_argument(
        "--fetch-timeout-seconds",
        type=int,
        default=30,
        help="Timeout in seconds for each Lectio fetch request (default: 30)",
    )
    parser.add_argument(
        "--days-past",
        type=int,
        help="Include events from N days in the past (overrides SYNC_DAYS_PAST)",
    )
    parser.add_argument(
        "--days-future",
        type=int,
        help="Include events up to N days in the future (overrides SYNC_DAYS_FUTURE)",
    )
    parser.add_argument(
        "--delete-missing",
        dest="delete_missing",
        action="store_true",
        help="Enable full-feed replacement behavior (default; can also be set with DELETE_MISSING=true)",
    )
    parser.add_argument(
        "--keep-missing",
        dest="delete_missing",
        action="store_false",
        help="Keep missing events policy flag for compatibility (currently informational only)",
    )
    parser.set_defaults(delete_missing=None)
    parser.add_argument(
        "--emit-cancelled-events",
        action="store_true",
        help="Emit cancelled activities as VEVENT with STATUS:CANCELLED instead of dropping them",
    )
    parser.add_argument(
        "--assignments-html",
        type=Path,
        help="Path to saved OpgaverElev.aspx HTML file for building the assignments feed",
    )
    parser.add_argument(
        "--assignments-out",
        type=Path,
        help="Output path for assignments ICS feed (default: docs/assignments.ics when assignments source provided)",
    )
    parser.add_argument(
        "--assignments-url",
        type=str,
        help="URL for OpgaverElev.aspx (also LECTIO_ASSIGNMENTS_URL env)",
    )
    parser.add_argument(
        "--free-classrooms-out",
        type=Path,
        help=(
            "Output path for the free-classrooms ICS feed "
            "(e.g. docs/free_classrooms.ics). "
            "When set, generates a second feed showing up to 4 free rooms per module slot for today."
        ),
    )
    parser.add_argument(
        "--fetch-assignments",
        action="store_true",
        help="Fetch the assignments page using the same cookie header (requires --fetch and --assignments-url)",
    )
    parser.add_argument("--debug", action="store_true", help="Print parser diagnostics")
    parser.add_argument(
        "--debug-fetch",
        action="store_true",
        help=(
            "Print non-sensitive fetch diagnostics (status/content-type/encoding and redacted URL) for each week. "
            "Does not print the fetched HTML."
        ),
    )
    parser.add_argument(
        "--debug-dump-html-dir",
        type=Path,
        help=(
            "Write fetched HTML pages to this directory for debugging. WARNING: contains private schedule data. "
            "Do not enable on public CI runs."
        ),
    )

    # ------------------------------------------------------------------
    # Cookie refresh (Playwright-based)
    # ------------------------------------------------------------------
    parser.add_argument(
        "--refresh-cookie",
        action="store_true",
        help=(
            "Open a Chromium browser window, wait for you to log in to Lectio, "
            "then capture the session cookie and update LECTIO_COOKIE_HEADER "
            "in GitHub Actions Secrets via `gh secret set`. "
            "Requires Playwright: py -m pip install playwright && py -m playwright install chromium"
        ),
    )
    parser.add_argument(
        "--cookie-profile-dir",
        type=Path,
        help=(
            "Directory for the persistent Playwright browser profile used by --refresh-cookie. "
            "Defaults to %%LOCALAPPDATA%%\\lectio-sync\\playwright-profile (Windows). "
            "Must be outside the repo to avoid accidental git-commit."
        ),
    )
    parser.add_argument(
        "--cookie-login-timeout",
        type=int,
        default=300,
        help="Seconds to wait for the Lectio schedule page to appear (default: 300).",
    )
    parser.add_argument(
        "--cookie-secret-name",
        type=str,
        default="LECTIO_COOKIE_HEADER",
        help="GitHub Secret name to update (default: LECTIO_COOKIE_HEADER).",
    )
    parser.add_argument(
        "--repo",
        type=str,
        help="GitHub repository (owner/name) passed to `gh secret set`. Inferred from cwd when omitted.",
    )
    parser.add_argument(
        "--print-cookie",
        action="store_true",
        help="Print the captured cookie header value to stdout (off by default for privacy).",
    )
    parser.add_argument(
        "--no-gh",
        action="store_true",
        help="Skip `gh secret set`; print the cookie value instead (useful for manual update).",
    )

    args = parser.parse_args()

    if args.days_past is not None and args.days_past < 0:
        parser.error("--days-past must be >= 0")
    if args.days_future is not None and args.days_future < 0:
        parser.error("--days-future must be >= 0")
    if args.fetch_timeout_seconds is not None and args.fetch_timeout_seconds <= 0:
        parser.error("--fetch-timeout-seconds must be > 0")

    # ------------------------------------------------------------------
    # Cookie refresh mode — completely separate from fetch/parse.
    # ------------------------------------------------------------------
    if args.refresh_cookie:
        from lectio_sync.cookie_refresh import refresh_cookie

        schedule_url = args.schedule_url or os.environ.get("LECTIO_SCHEDULE_URL", "").strip()
        if not schedule_url:
            parser.error(
                "--schedule-url is required for --refresh-cookie "
                "(or set the LECTIO_SCHEDULE_URL environment variable)"
            )

        return refresh_cookie(
            schedule_url=schedule_url,
            profile_dir=args.cookie_profile_dir,
            login_timeout_seconds=args.cookie_login_timeout,
            secret_name=args.cookie_secret_name,
            github_repo=args.repo,
            print_cookie=args.print_cookie,
            no_gh=args.no_gh,
        )

    if args.fetch:
        timezone_name = args.tz or os.environ.get("LECTIO_TIMEZONE", "Europe/Copenhagen")
        days_past = 7 if args.days_past is None else args.days_past
        days_future = 90 if args.days_future is None else args.days_future

        schedule_url = args.schedule_url or os.environ.get("LECTIO_SCHEDULE_URL", "")
        if not schedule_url.strip():
            parser.error("--schedule-url is required for --fetch (or set LECTIO_SCHEDULE_URL)")

        cookie_header = args.cookie_header or os.environ.get("LECTIO_COOKIE_HEADER", "")
        if not cookie_header.strip():
            parser.error("LECTIO_COOKIE_HEADER is required for --fetch (prefer GitHub Secret / env var)")

        weeks = iter_weeks_for_window(timezone_name=timezone_name, days_past=days_past, days_future=days_future)
        fetched = fetch_weeks_html_with_diagnostics(
            schedule_url=schedule_url,
            cookie_header=cookie_header,
            weeks=weeks,
            timeout_seconds=args.fetch_timeout_seconds,
        )

        events = []
        seen_uids: set[str] = set()
        auth_redirect_weeks: list[str] = []
        if args.debug_dump_html_dir is not None:
            args.debug_dump_html_dir.mkdir(parents=True, exist_ok=True)

        for wk, html, diag in fetched:
            page_kind = _classify_fetched_page(html)

            if args.debug_fetch:
                print(
                    "Fetch diagnostics: "
                    f"week={wk.week_param}, status={diag.status_code}, "
                    f"content-type={diag.content_type or '(missing)'}, "
                    f"content-encoding={diag.content_encoding or 'identity'}, "
                    f"bytes={diag.raw_bytes_len}, chars={diag.decoded_chars_len}, "
                    f"final-url={_redact_url_for_logs(diag.final_url)}, "
                    f"kind={page_kind}"
                )

            if args.debug_dump_html_dir is not None:
                # WARNING: contains private data. Only for local/manual debugging.
                dump_path = args.debug_dump_html_dir / f"lectio-week-{wk.week_param}.html"
                dump_path.write_text(html, encoding="utf-8", errors="replace")

            # Detect auth/security redirects by final URL before attempting to parse.
            # These happen when the session cookie has expired.
            if _is_auth_redirect(diag.final_url):
                print(
                    f"WARNING: week {wk.week_param} was redirected to "
                    f"{_redact_url_for_logs(diag.final_url)} — "
                    "the session cookie appears to be expired. "
                    "Run scripts/refresh_cookie.ps1 to capture a new cookie."
                )
                auth_redirect_weeks.append(wk.week_param)
                continue

            try:
                week_events = parse_lectio_advanced_schedule_html_text(
                    html,
                    timezone_name,
                    sync_days_past=days_past,
                    sync_days_future=days_future,
                    emit_cancelled_events=args.emit_cancelled_events,
                    debug=args.debug,
                )
            except Exception as exc:
                # Keep the raised exception actionable but privacy-preserving.
                raise RuntimeError(
                    "Failed to parse fetched Lectio HTML. This often means the cookie is invalid/expired, "
                    "or the URL did not return the schedule page. "
                    f"(week={wk.week_param}, status={diag.status_code}, content-type={diag.content_type or '(missing)'}, "
                    f"content-encoding={diag.content_encoding or 'identity'}, final-url={_redact_url_for_logs(diag.final_url)}, "
                    f"kind={page_kind}). "
                    "If your secret contains a full header line like 'Cookie: ...', remove the 'Cookie:' prefix (or update the secret)."
                ) from exc

            for ev in week_events:
                if ev.uid in seen_uids:
                    continue
                seen_uids.add(ev.uid)
                events.append(ev)

        # Keep deterministic ordering across all weeks
        from datetime import datetime
        from dateutil import tz

        def _sort_key(ev):
            if ev.is_all_day:
                return (0, ev.all_day_date, ev.title, ev.uid)
            return (1, ev.start or datetime.min.replace(tzinfo=tz.UTC), ev.title, ev.uid)

        events.sort(key=_sort_key)
        events = _filter_events(events)

        # If every week was an auth redirect and we got no events, preserve the
        # existing ICS files unchanged and exit non-zero so the CI failure is visible.
        if not events and auth_redirect_weeks:
            print(
                f"ERROR: All {len(auth_redirect_weeks)} fetched week(s) returned authentication redirects "
                f"({', '.join(auth_redirect_weeks)}). "
                "The session cookie is expired. "
                "Run scripts/refresh_cookie.ps1 to capture a new cookie and update the GitHub Secret, "
                "then re-run the workflow. "
                "The existing ICS files have NOT been changed."
            )
            return 1

        out_path = args.out or Path(os.environ.get("OUTPUT_ICS_PATH", "docs/calendar.ics"))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_icalendar(events, out_path)

        print(f"Wrote {len(events)} events to {out_path}")

        # -- Assignments feed (fetch mode) --
        if args.fetch_assignments:
            assignments_url = args.assignments_url or os.environ.get("LECTIO_ASSIGNMENTS_URL", "")
            if not assignments_url.strip():
                print(
                    "WARNING: --fetch-assignments was requested but --assignments-url is empty and "
                    "LECTIO_ASSIGNMENTS_URL is not set. Skipping assignments feed."
                )
                return 0

            assignments_html, assign_diag = fetch_html_with_diagnostics(
                url=assignments_url,
                cookie_header=cookie_header,
                timeout_seconds=args.fetch_timeout_seconds,
            )
            if args.debug_fetch:
                print(
                    "Fetch diagnostics (assignments): "
                    f"status={assign_diag.status_code}, "
                    f"content-type={assign_diag.content_type or '(missing)'}, "
                    f"bytes={assign_diag.raw_bytes_len}, "
                    f"final-url={_redact_url_for_logs(assign_diag.final_url)}"
                )
            try:
                assignment_events = parse_lectio_assignments_html_text(
                    assignments_html, timezone_name, debug=args.debug
                )
            except Exception as exc:
                raise RuntimeError(
                    "Failed to parse fetched assignments HTML. "
                    f"(status={assign_diag.status_code}, final-url={_redact_url_for_logs(assign_diag.final_url)})"
                ) from exc

            assign_out = args.assignments_out or Path("docs/assignments.ics")
            assign_out.parent.mkdir(parents=True, exist_ok=True)
            write_icalendar(assignment_events, assign_out, cal_name="lectio opgaver")
            print(f"Wrote {len(assignment_events)} assignments to {assign_out}")

        # -- Free classrooms feed (fetch mode) --
        if args.free_classrooms_out is not None:
            free_out = args.free_classrooms_out
            free_events = generate_free_classrooms_ics(
                events,
                free_out,
                timezone_name,
            )
            print(f"Wrote {len(free_events)} events to {free_out}")

        return 0

    config = load_config_from_env_with_overrides(
        lectio_html_path=args.html,
        output_ics_path=args.out,
        timezone=args.tz,
        sync_days_past=args.days_past,
        sync_days_future=args.days_future,
        delete_missing=args.delete_missing,
        emit_cancelled_events=args.emit_cancelled_events,
    )

    events = parse_lectio_advanced_schedule_html(
        config.lectio_html_path,
        config.timezone,
        sync_days_past=config.sync_days_past,
        sync_days_future=config.sync_days_future,
        emit_cancelled_events=config.emit_cancelled_events,
        debug=args.debug,
    )

    if args.debug and not config.delete_missing:
        print(
            "Delete missing policy: keep-missing requested, but current implementation regenerates a full feed each run."
        )
    events = _filter_events(events)
    out_path = config.output_ics_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_icalendar(events, out_path)

    print(f"Wrote {len(events)} events to {out_path}")

    # -- Assignments feed (file mode) --
    if args.assignments_html is not None:
        tz_name = args.tz or os.environ.get("LECTIO_TIMEZONE", "Europe/Copenhagen")
        assignment_events = parse_lectio_assignments_html(
            args.assignments_html, tz_name, debug=args.debug
        )
        assign_out = args.assignments_out or Path("docs/assignments.ics")
        assign_out.parent.mkdir(parents=True, exist_ok=True)
        write_icalendar(assignment_events, assign_out, cal_name="lectio opgaver")
        print(f"Wrote {len(assignment_events)} assignments to {assign_out}")

    # -- Free classrooms feed (file mode) --
    if args.free_classrooms_out is not None:
        tz_name = args.tz or os.environ.get("LECTIO_TIMEZONE", "Europe/Copenhagen")
        free_out = args.free_classrooms_out
        free_events = generate_free_classrooms_ics(
            events,
            free_out,
            tz_name,
        )
        print(f"Wrote {len(free_events)} events to {free_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
