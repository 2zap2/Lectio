---
title: "Add Lectio assignments (Opgaver) as separate ICS feed"
author: "GitHub Copilot (GPT-5.2)"
date: "2026-02-26"
status: complete
estimated_effort: "4–8h"
---

# Add Lectio assignments (Opgaver) as separate ICS feed

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

There is no PLANS.md in this repo at the time of writing.

## Purpose / Big Picture

After this change, the repo will generate a second iCalendar feed containing only upcoming Lectio assignments (from https://www.lectio.dk/lectio/681/OpgaverElev.aspx) as all-day “deadline” events. The new feed will be written to docs/assignments.ics and published/updated the same way as docs/calendar.ics (local PowerShell scripts and GitHub Actions). Users can subscribe to this new ICS link in their calendar client and see assignment deadlines on the due date (“Frist”), with summary built from Status + Opgavetitel + Hold + Elevtid, and the assignment note (“Opgavenote”) placed into the ICS DESCRIPTION.

“Moved/removed” assignments will be reflected automatically because the feed is regenerated fully each run and uses a stable UID derived from exerciseid in the assignment link.

## Progress

- [x] (2026-02-26) Read current schedule pipeline and ICS writer; confirm constraints.
- [x] Add parser for OpgaverElev.aspx HTML -> LectioEvent list (upcoming only).
- [x] Extend ICS writer to correctly represent all-day events (exclusive DTEND).
- [x] Extend CLI to optionally build assignments ICS (from file or fetch).
- [x] Extend scripts to generate and push docs/assignments.ics alongside docs/calendar.ics.
- [x] Add unit tests for assignments parsing + ICS output characteristics.
- [x] Update README with new feed name and where it lands (docs/assignments.ics).

## Surprises & Discoveries

- Observation (repo): src/lectio_sync/ical_writer.py currently emits DTEND equal to DTSTART for all-day events. In RFC5545, DTEND for all-day is exclusive and should typically be the day after DTSTART.
  Evidence: In build_icalendar(), it writes both DTSTART;VALUE=DATE and DTEND;VALUE=DATE using the same date string.

- Observation (Lectio HTML): Assignments appear in a table with id "s_m_Content_Content_ExerciseGV". The “exerciseid=…” parameter in the assignment link is stable and suitable for UID.
  Evidence: Row anchor href looks like /lectio/681/ElevAflevering.aspx?elevid=...&exerciseid=74136529520&prevurl=OpgaverElev.aspx

## Decision Log

- Decision: Use exerciseid from the assignment link as the ICS UID basis (UID = "<exerciseid>@lectio.dk").
  Rationale: Stable across “moved” deadline changes, ensures updates instead of duplicates, and missing assignments drop out naturally on full feed rebuild.
  Date/Author: 2026-02-26 / GitHub Copilot (GPT-5.2)

- Decision: Filter “upcoming” by due date (Frist date) >= today in Europe/Copenhagen, regardless of assignment Status.
  Rationale: Matches user requirement “only upcoming assignments”; Status like “Afleveret” may still appear for future due dates, but it is still an upcoming deadline.
  Date/Author: 2026-02-26 / GitHub Copilot (GPT-5.2)

- Decision: Fix all-day DTEND semantics in the shared ICS writer rather than hacking a per-feed workaround.
  Rationale: All-day events must render reliably in calendar clients; a correct DTEND benefits both schedule and assignment feeds. Tests will be updated to match corrected behavior.
  Date/Author: 2026-02-26 / GitHub Copilot (GPT-5.2)

## Outcomes & Retrospective

All milestones completed on 2026-02-26. 22 tests pass (`py -m pytest -q`).

Key changes delivered:
- `src/lectio_sync/html_parser.py`: added `parse_lectio_assignments_html` / `parse_lectio_assignments_html_text` with fallback table locator, Danish date parsing, and upcoming-only filter.
- `src/lectio_sync/ical_writer.py`: fixed all-day `DTEND` to be exclusive (day+1), added `cal_name` kwarg for `X-WR-CALNAME`.
- `src/lectio_sync/cli.py`: added `--assignments-html`, `--assignments-out`, `--assignments-url`, `--fetch-assignments` flags; both file and fetch modes supported.
- `scripts/update_ics.ps1` / `scripts/update_ics_and_push.ps1`: optional `AssignmentsHtmlPath` parameter; stages both ICS files.
- `.github/workflows/update-calendar.yml`: fetches assignments via `LECTIO_ASSIGNMENTS_URL` secret, commits both files.
- `.github/workflows/build-ics.yml`: builds `docs/assignments.ics` when `input/opgaver.html` is present.
- `tests/test_assignments_parser.py`: 12 new tests (past/today/future filtering, title format, all-day semantics, note, ordering, missing-table error).
- `tests/test_ical_writer.py`: 3 new tests (exclusive DTEND, X-WR-CALNAME present, X-WR-CALNAME absent).

## Context and Orientation

Key existing modules:

- src/lectio_sync/html_parser.py parses “Advanced schedule” HTML and returns a list of LectioEvent objects.
- src/lectio_sync/event_model.py defines LectioEvent (uid, title, start/end or all_day_date, description, etc.).
- src/lectio_sync/ical_writer.py renders a list of LectioEvent to an .ics file (write_icalendar()).
- src/lectio_sync/lectio_fetch.py can fetch HTML from Lectio with an existing session cookie header.
- src/lectio_sync/cli.py provides the CLI entry point (python -m lectio_sync), currently focused on schedule fetching/parsing and writing docs/calendar.ics.
- scripts/update_ics.ps1 and scripts/update_ics_and_push.ps1 generate and optionally commit docs/calendar.ics.
- .github/workflows/update-calendar.yml fetches Lectio schedule via cookie and commits docs/calendar.ics on schedule.

New behavior to add:

- Parse assignments from OpgaverElev.aspx HTML, building all-day events on the Frist date.
- Create docs/assignments.ics with calendar name “lectio opgaver”.
- Update scripts and GitHub Actions so both docs/calendar.ics and docs/assignments.ics are updated together.

## Plan of Work

### Milestone 1: Implement assignments HTML parser (file + text)

Goal: Convert OpgaverElev.aspx HTML into a list of LectioEvent objects representing upcoming assignment deadlines.

Work:

1) Add new parsing functions in src/lectio_sync/html_parser.py (or a new module if cleaner; default is to extend html_parser.py to reuse BeautifulSoup and existing text normalization helpers):
   - parse_lectio_assignments_html(path: Path, timezone_name: str, *, today: date | None = None) -> list[LectioEvent]
   - parse_lectio_assignments_html_text(html: str, timezone_name: str, *, today: date | None = None) -> list[LectioEvent]

   Behavior:
   - Locate table:
     - Primary: table id "s_m_Content_Content_ExerciseGV"
     - Fallback: any table with id ending in "_ExerciseGV" or containing header text “Opgavetitel” and “Frist”.
   - For each data row (tr with td cells, excluding header):
     - Extract:
       - Hold: second desktop column text (e.g., "L2a MA")
       - Opgavetitel: anchor text in “Opgavetitel” column (e.g., "Metrikplakat genaflevering")
       - Frist: due datetime string in “Frist” column (e.g., "10/9-2025 22:00")
       - Elevtid: numeric string in “Elev tid” column (e.g., "1,00")
       - Status: text in “Status” column (e.g., "Afleveret", "Mangler", "Venter")
       - Opgavenote: text in “Opgavenote” column (can be empty; may include newlines)
     - Extract exerciseid:
       - From the anchor href querystring parameter "exerciseid".
       - Build UID: f"{exerciseid}@lectio.dk"
   - Parse Frist into local datetime (Europe/Copenhagen) and then take the date part as due_date.
     - Use a strict parse for Danish format: day/month-year hour:minute where day/month may be 1–2 digits.
     - If parse fails, skip the row (and, in debug mode, print a short diagnostic without leaking full HTML).
   - Filter: include only if due_date >= today (today is computed in timezone_name; tests can pass explicit today).
   - Create LectioEvent:
     - all_day_date = due_date
     - start/end = None (or unused)
     - location = "" (not requested)
     - status = "CONFIRMED" (do not map Lectio assignment status into iCal STATUS)
     - title (SUMMARY) = "{Status} • {Opgavetitel} • {Hold} • {Elevtid}"
       - Use the exact order user requested: status, opgavetitel, Hold, elevtid
       - Use a consistent separator. Default: " • " (plain text).
     - description (DESCRIPTION) = Opgavenote text (normalized; preserve line breaks if present)

2) Add small, privacy-preserving debug hooks (optional) consistent with existing CLI patterns:
   - In parser, accept debug: bool = False and print counts + parse failures (but never dump HTML).

Proof / acceptance for Milestone 1:
- A unit test can feed a minimal HTML string with 2–3 rows and verify:
  - Correct extraction for Hold/title/frist/elevtid/status/opgavenote.
  - Past assignments are excluded when today is set past their Frist date.
  - UID uses exerciseid and is stable.

### Milestone 2: Fix all-day DTEND semantics in ICS writer (required for correct “all day” deadlines)

Goal: Ensure all-day events display as a full day in calendar clients.

Work:

1) Update src/lectio_sync/ical_writer.py:
   - When ev.is_all_day is True:
     - DTSTART;VALUE=DATE = due_date formatted YYYYMMDD
     - DTEND;VALUE=DATE = (due_date + 1 day) formatted YYYYMMDD
   - Keep DTSTAMP and SUMMARY as-is.
   - Do not add extra fields beyond what’s needed.

2) Update existing tests that assert exact ICS text (likely tests/test_ical_writer.py) to match the corrected DTEND behavior.
   - If there are no tests covering all-day events, add one.

Proof / acceptance for Milestone 2:
- Unit test creates a LectioEvent(all_day_date=2026-02-26) and asserts the ICS contains:
  - DTSTART;VALUE=DATE:20260226
  - DTEND;VALUE=DATE:20260227

### Milestone 3: Extend CLI to build assignments.ics (from file and from fetch)

Goal: Running python -m lectio_sync can produce docs/calendar.ics and optionally docs/assignments.ics in the same run, using the same cookie refresh strategy (cookie header passed/env).

Work:

1) Extend src/lectio_sync/cli.py with new optional flags (no breaking changes):
   - --assignments-html <path> : path to saved OpgaverElev.aspx HTML
   - --assignments-out <path> : output path for assignments ICS (default if provided by scripts/workflows: docs/assignments.ics)
   - --assignments-url <url> : base URL for OpgaverElev.aspx (env fallback: LECTIO_ASSIGNMENTS_URL)
   - --fetch-assignments : fetch OpgaverElev.aspx using cookie header, similar to --fetch schedule

2) Behavior:
   - Schedule output remains the same as today when assignments flags are not used.
   - If --fetch is used for schedule and --fetch-assignments is also provided:
     - Fetch schedule pages as today.
     - Fetch assignments page once via lectio_fetch.fetch_html_with_diagnostics(url=assignments_url, cookie_header=...).
     - Parse assignments HTML and write assignments feed to --assignments-out.
   - If not fetching (file mode):
     - If --assignments-html is provided, parse that file and write --assignments-out.
   - Filtering uses timezone_name (from --tz / LECTIO_TIMEZONE) to compute “today”.

3) Calendar naming:
   - Add support in ICS writer for calendar-level name (X-WR-CALNAME).
   - For assignments feed, set X-WR-CALNAME to "lectio opgaver".
   - Keep schedule feed’s calendar name unchanged unless already present (do not change UX beyond the request).

Proof / acceptance for Milestone 3 (CLI smoke tests):
- File mode:
    Working directory: c:\Users\Arthu\Lectio
    Command: py -m lectio_sync --html <schedule.html> --out docs/calendar.ics --assignments-html <opgaver.html> --assignments-out docs/assignments.ics --tz Europe/Copenhagen
    Expected outcome: prints "Wrote <N> events to docs/calendar.ics" and also prints "Wrote <M> assignments to docs/assignments.ics" (exact wording to be implemented and then pinned in this plan once known).

- Fetch mode (local/manual):
    Working directory: c:\Users\Arthu\Lectio
    Command: set LECTIO_COOKIE_HEADER=...; py -m lectio_sync --fetch --schedule-url ... --assignments-url https://www.lectio.dk/lectio/681/OpgaverElev.aspx --fetch-assignments --out docs/calendar.ics --assignments-out docs/assignments.ics
    Expected outcome: both files updated.

### Milestone 4: Extend PowerShell scripts to generate + push both ICS files

Goal: scripts/update_ics.ps1 and scripts/update_ics_and_push.ps1 update assignments.ics whenever calendar.ics is updated.

Work:

1) Update scripts/update_ics.ps1:
   - Add optional parameters:
     - -AssignmentsHtmlPath (optional)
     - -AssignmentsOutPath default "docs\\assignments.ics"
   - If AssignmentsHtmlPath is provided, invoke python once with both schedule and assignments args.
   - Keep existing usage unchanged when AssignmentsHtmlPath is not provided.

2) Update scripts/update_ics_and_push.ps1:
   - Call update_ics.ps1 with both HTML paths when available.
   - git add both docs/calendar.ics and docs/assignments.ics.
   - Commit message can remain “Update calendar.ics (...)” or be broadened (e.g., “Update calendars (...)”); choose the simplest consistent approach.

Proof / acceptance:
- Running update_ics.ps1 with both HTML paths creates/updates both docs/*.ics.
- update_ics_and_push.ps1 stages both files and commits when either changed.

### Milestone 5: Extend GitHub Actions workflows to build both files on schedule

Goal: The hosted repo updates both ICS feeds on the same schedule and commits both files when changed.

Work:

1) Update .github/workflows/update-calendar.yml:
   - Add secret/env var: LECTIO_ASSIGNMENTS_URL (or inline the known URL; prefer secret for flexibility).
   - Modify “Fetch Lectio and build ICS” step to pass:
     - --fetch (schedule)
     - --fetch-assignments and --assignments-url
     - --assignments-out "docs/assignments.ics"
   - Update commit step to git add both files:
     - git add docs/calendar.ics docs/assignments.ics

2) Update .github/workflows/build-ics.yml similarly (optional but recommended for parity):
   - If it builds from input HTML files, require an additional input file for assignments (e.g., input/opgaver.html) or skip assignments there. Choose the simplest:
     - Option A (recommended): Support both input HTML files and build both ICS when both exist.
     - Option B: Keep build-ics.yml unchanged and only update update-calendar.yml (the one you actually use for fetch).

Proof / acceptance:
- Workflow run logs show both files written and committed when changed.

### Milestone 6: Tests and documentation

Goal: Prove correctness and prevent regressions.

Work:

1) Add tests:
   - tests/test_assignments_parser.py:
     - Include a minimal HTML sample with a table id s_m_Content_Content_ExerciseGV and at least:
       - One past assignment row (should be filtered out)
       - One due-today assignment row (should be included)
       - One future assignment row with multi-line Opgavenote (should be included; description preserves newlines)
     - Pass explicit today=date(YYYY,MM,DD) to parser for deterministic behavior.
   - tests/test_ical_writer.py:
     - Add/adjust test for all-day DTEND exclusive behavior.

2) Update README.md:
   - Document that the repo now generates two feeds:
     - docs/calendar.ics (schedule)
     - docs/assignments.ics (“lectio opgaver”)
   - Explain at a high level how to subscribe (without hardcoding your personal GH Pages URL if not known; just say it’s hosted alongside calendar.ics the same way).

Proof / acceptance:
- Running tests succeeds:
    Working directory: c:\Users\Arthu\Lectio
    Command: py -m pytest
    Expected outcome: all tests pass (record exact count after implementation).

## Concrete Steps

Implementation steps a coding agent should follow (repeatable, safe):

1) Explore current tests and confirm how pytest is invoked.
    Working directory: c:\Users\Arthu\Lectio
    Command: py -m pytest -q
    Expected outcome: baseline tests pass (or record failures unrelated to this task; do not fix unrelated failures).

2) Implement Milestone 2 (all-day DTEND) first, update tests accordingly, rerun pytest.

3) Implement Milestone 1 (assignments parser), add tests, rerun pytest.

4) Implement Milestone 3 (CLI flags and optional outputs), add a small CLI smoke test transcript to this plan after verifying locally.

5) Update scripts, then workflows, then README. Rerun pytest after each major change.

## Validation and Acceptance

User-visible acceptance:

- A new file docs/assignments.ics is generated.
- It contains only assignments with Frist date >= today (Europe/Copenhagen).
- Each assignment is an all-day event on the Frist date.
- Event SUMMARY is exactly the concatenation of: Status, Opgavetitel, Hold, Elevtid (in that order).
- Event DESCRIPTION contains the “Opgavenote” text from Lectio.
- The calendar name shown by clients is “lectio opgaver” (X-WR-CALNAME in VCALENDAR).
- When an assignment is removed from Lectio, it disappears from docs/assignments.ics on next run (full-feed regeneration).
- When an assignment Frist changes, it moves in the calendar (same UID, different DTSTART/DTEND).

Repo acceptance:

- py -m pytest passes.
- GitHub Actions workflow update-calendar.yml commits both docs/calendar.ics and docs/assignments.ics when either changes.

## Idempotence and Recovery

- The generator is safe to re-run: it overwrites docs/calendar.ics and docs/assignments.ics deterministically from the current Lectio HTML/fetch results.
- If a cookie expires, fetch mode fails with an actionable error message; retry after refreshing LECTIO_COOKIE_HEADER.
- If the assignments table structure changes, the parser should fail with a clear “could not locate assignments table” error rather than silently emitting an empty calendar (unless the page is truly empty; in that case, emitting an empty feed is acceptable).

## Interfaces and Dependencies

- No new Python dependencies should be introduced. Use existing:
  - bs4 (BeautifulSoup) already in use
  - standard library (datetime, zoneinfo, urllib.parse)
- New/updated public interfaces:
  - In src/lectio_sync/html_parser.py:
      parse_lectio_assignments_html(...)
      parse_lectio_assignments_html_text(...)
  - In src/lectio_sync/cli.py:
      Add CLI flags described above; schedule behavior remains unchanged.
  - In src/lectio_sync/ical_writer.py:
      Correct all-day DTEND behavior.
      Add optional calendar name support (X-WR-CALNAME) if needed for “lectio opgaver”.

## Artifacts and Notes

Expected HTML coding of assignments (what the parser should target):

- Table: <table id="s_m_Content_Content_ExerciseGV">
- Each assignment row:
  - Hold: td[1] text (OnlyDesktop)
  - Opgavetitel: td[2] contains <a href="...exerciseid=...">TITLE</a>
  - Frist: td[3] text like "27/2-2026 23:30"
  - Elevtid: td[4] text like "3,00"
  - Status: td[5] text; sometimes inside <span class="exercisemissing">Mangler</span>
  - Opgavenote: td[8] text; may be empty or multi-line

Plan revision note:
- (2026-02-26) Initial draft created based on provided Lectio OpgaverElev.aspx HTML snippet and existing repo architecture.
