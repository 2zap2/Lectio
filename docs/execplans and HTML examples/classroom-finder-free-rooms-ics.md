---
title: "Classroom finder: free rooms ICS (today-only, top-4)"
author: "GitHub Copilot (GPT-5.2)"
date: "2026-02-27"
status: "draft"
estimated_effort: "3–8h"
---

# Classroom finder: free rooms ICS (today-only, top-4)

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

There is no PLANS.md in this repository; follow the conventions described in skills-repo/skills/planning/SKILL.md.

## Purpose / Big Picture

Lectio has no student-facing “find a free classroom” page, but Lectio *does* provide an Advanced Schedule view that can show lessons in multiple classrooms at once.

Goal: generate a separate iCal feed (ICS) that helps students quickly spot a few good candidate rooms that are free right now / next module, without clutter.

After this change, a student (or anyone subscribing to the published calendar files) can open a new calendar feed and immediately see up to four suggested classrooms that are free for at least one full module, with preference for rooms that remain free for two or more consecutive modules.

The feed must meet these user-visible requirements:

- Use only today’s data (no multi-week horizon).
- Only consider the fixed module grid (below).
- Only show rooms that are free for ≥ 1 hour.
- At any point in time, show max 4 rooms.
- Prioritize rooms that remain free for longer consecutive stretches (prefer ≥ 2 hours over 1 hour).

How to see it working (after implementation):

		Working directory: C:\Users\Arthu\Lectio
		Command: py -m lectio_sync --fetch --schedule-url "%LECTIO_SCHEDULE_URL%" --out docs/calendar.ics --free-classrooms-out docs/free_classrooms.ics
		Expected stdout (example):
			Wrote <N> events to docs/calendar.ics
			Wrote <M> events to docs/free_classrooms.ics
		Expected exit code: 0

## Progress

- [x] (2026-02-27) Align plan structure with skills-repo/skills/planning/SKILL.md (definitions, proof commands).
- [x] (2026-02-27) Verify parsing of today's room events from SkemaAvanceret HTML.
- [x] (2026-02-27) Decide handling for `Lokaler:` multi-room tooltips.
- [x] (2026-02-27) Implement module-grid free-room algorithm + selection.
- [x] (2026-02-27) Emit separate ICS output and wire into scripts.
- [x] (2026-02-27) Add tests.

## Context and Orientation

This repository already fetches Lectio “Advanced Schedule” HTML and converts it to an iCal feed.

Key files (repository-relative paths):

- src/lectio_sync/cli.py: CLI entry point (arg parsing, fetch-vs-local HTML, writing ICS outputs).
- src/lectio_sync/lectio_fetch.py: HTTP fetching (when using `--fetch` and cookie header).
- src/lectio_sync/html_parser.py: Lectio Advanced Schedule HTML parsing into structured events.
- src/lectio_sync/ical_writer.py: ICS writing.
- scripts/update_ics.ps1 and scripts/update_ics_and_push.ps1: automation helpers.

Important existing behavior to preserve:

- Cancelled Lectio bricks (CSS class contains `s2cancelled` or tooltip starts with “Aflyst!”) are not emitted unless explicitly requested, and they should not count as “busy” for the free-room finder.
- The parser’s primary data source is the `data-tooltip` attribute of `a.s2skemabrik` elements.

## Definitions (plain language)

- ICS: the `.ics` calendar file format (iCalendar).
- VEVENT: a single timed event entry inside an ICS file.
- Module: one fixed teaching block (e.g., 08:15–09:15). In this plan we only care about the six modules listed below.
- Busy (for a room): a room is considered busy in a module if any schedule event overlaps that module’s time window.
- Free (for a room): a room is free in a module if it is not busy in that module.
- Consecutive free time: how many modules in a row the room remains free starting from a given module start.
- “Today”: the current local date in the configured Lectio timezone (the same timezone used for the existing schedule ICS). This plan uses only the events whose start date equals that “today” date.

## Inputs / Constraints

### Source HTML

- Lectio Advanced Schedule URL (example):
	- https://www.lectio.dk/lectio/681/SkemaAvanceret.aspx?type=skema&lokalesel=...
- Schedule URL configuration:
	- CLI flag: `--schedule-url <URL>`
	- Environment variable: `LECTIO_SCHEDULE_URL`
- Authentication (Lectio session cookie header):
	- CLI flag: `--cookie-header <COOKIE_HEADER_VALUE>`
	- Environment variable / GitHub Secret: `LECTIO_COOKIE_HEADER`
- Timezone configuration (used for interpreting “today” and writing DTSTART/DTEND):
	- CLI flag: `--tz <TZ_NAME>`
	- Environment variable: `LECTIO_TIMEZONE`
- Parsing target in HTML:
	- Table id: `m_Content_SkemaMedNavigation_skema_skematabel` (class `s2skema`).
	- Events (“schedule bricks”): `<a class="s2skemabrik ..." data-tooltip="...">`.
	- Day association: the brick is inside a `<td data-date="YYYY-MM-DD">`.

A real HTML example exists in:

- docs/execplans and HTML examples/HTML example of calendar for classrooms

### Classroom universe

Rooms to consider (provided list):

- 0.75
- 0.76
- 0.77
- 1.02
- 1.03a
- 1.07
- 1.09
- 1.10
- 1.59
- 1.60
- 1.61
- 1.62
- 1.64
- 1.65
- 2.01
- 2.03
- 2.04
- 2.05
- 2.27
- 2.29
- 2.31

### Fixed module grid (only times we care about)

We only model the school day as these six modules:

1) 08:15–09:15
2) 09:20–10:20
3) 10:30–11:30
4) 12:10–13:10
5) 13:20–14:20
6) 14:30–15:30

Notes:

- Ignore any other times shown in Lectio (e.g., “7. modul 15:35–16:35”, evening events, etc.).
- When a room is free across consecutive modules, treat it as continuously free including the small breaks between modules for the purpose of “consecutive” duration and for emitting a single merged free interval in the ICS.

## Output

Create a separate ICS file (default path to be decided; suggested: `docs/free_classrooms.ics`).

Calendar behavior:

- The calendar consists only of VEVENT blocks representing “Free room suggestions”.
- At any time, there should be no more than 4 overlapping “free room” VEVENTs.
- VEVENT summaries should be short and consistent, e.g.:
	- `Free: 1.07` or `Free classroom: 1.07`

## Plan of Work (Idea 1 adapted to today-only + fixed modules)

### 1) Build a busy map per room, for today only

Fetch one Advanced Schedule HTML page (the week view is fine) and parse it with the existing advanced schedule parser (`parse_lectio_advanced_schedule_html_text`). Filter down to timed events that occur on “today” and convert them into a “busy intervals per room” map restricted to the known classroom universe.

Important edge case: multi-room tooltips.

- Some bricks contain `Lokaler:` (plural) with multiple rooms (comma-separated).
- Current parsing likely extracts only `Lokale:` (singular).
- Plan requirement: treat a multi-room event as busy for each listed room that is in our universe.

Implementation strategy options:

- Preferred: extend tooltip parsing to return `rooms: list[str]` (covering both `Lokale:` and `Lokaler:`).
- Minimal change: post-process the parsed `event.description` lines; if a line starts with `Lokaler:`, split it and add those rooms as busy.

### 2) Project busy intervals onto the fixed module grid

For each room and each of the six modules, determine if the room is busy.

Rule: a room is busy in a module if any busy interval overlaps the module window.

Formally, with module interval [A, B) and event [S, E): overlap if `S < B and E > A`.

### 3) Compute consecutive free duration per module boundary

For each module boundary i (i from 1..6):

- A room qualifies at boundary i if it is free in module i.
- Its “consecutive free length” is the count of consecutive free modules starting at i.
- Convert to minutes by using real clock times and including breaks between consecutive modules.

This gives a score signal that aligns with the user requirement:

- 1 free module → ~60 minutes (eligible)
- 2+ free modules → ≥ 120 minutes (preferred)

### 4) Select at most 4 rooms “visible” per time segment

We need a selection over time such that at any moment, ≤4 rooms are shown.

Given the fixed grid, we can treat the day as discrete segments that begin at each module start time.

For each module boundary i:

1) Consider all rooms that are free in module i.
2) Filter to those with consecutive free length ≥ 1 module (always true if free in module i).
3) Rank by:
	 - Primary: consecutive free length (modules), descending.
	 - Secondary tie-breaker: deterministic (room name) to avoid churn.
4) Take top 4.

Emit “Free room” events that start at the module start time.

Merging:

- If the same room remains selected across adjacent module boundaries and stays free, merge into a single VEVENT spanning the combined time range.

Optional stability tweak (only if needed for readability):

- “Keep winners”: if a room was selected in previous module and is still free, keep it unless it falls below the top-4 by a large margin.
- Start without this; only add if the calendar feels too jumpy.

### 5) Generate ICS events

For each merged interval (room R, start T0, end T1):

- SUMMARY: `Free: {R}`
- DTSTART/DTEND: local timezone (same as existing schedule feeds).
- LOCATION: `{R}`
- UID: deterministic, e.g. `free-{YYYYMMDD}-{R}-{HHMM}-{HHMM}@lectio-sync`

## Milestones

### Milestone 1: Confirm we can reliably parse rooms + times for today

Goal

- Given a fetched HTML page, we can extract all busy intervals for the room universe for a specific day.

Steps

Use the existing HTML parser on the example HTML file and verify it produces correct structured events for the timetable bricks. Specifically, confirm that:

- Timed bricks have correct start/end datetimes.
- `Lokale: X` is extracted.
- Cancelled bricks (`s2cancelled` or tooltip “Aflyst!”) do not mark rooms as busy.

Also identify at least one real example of `Lokaler:` (plural) and decide how to support it so multi-room events mark all listed rooms as busy.

Proof (example transcript you should be able to reproduce while implementing):

		Working directory: C:\Users\Arthu\Lectio
		Command: py -m lectio_sync --html "docs/execplans and HTML examples/HTML example of calendar for classrooms" --out docs/_debug_calendar.ics --debug
		Expected stdout contains (example):
			Parse stats: selector=id=m_Content_SkemaMedNavigation_skema_skematabel, bricks=<N>, added=<M>, emit_cancelled_events=False, cancelled_emitted=0, skipped_empty=<...>, skipped_cancelled=<...>, skipped_missing_date=<...>, skipped_missing_time=<...>, skipped_duplicate_uid=<...>
			Wrote <M> events to docs/_debug_calendar.ics
		Expected exit code: 0

Acceptance

- For a chosen date (e.g., 2026-02-27), we can list busy modules per room.

### Milestone 2: Implement the “top-4 free rooms” selector on the fixed grid

Goal

- Deterministically produce the selected rooms per module boundary.

Steps

1) Implement module grid constants.
2) Implement busy→free projection.
3) Implement consecutive-free scoring.
4) Implement top-4 selection and merging across modules.

Acceptance

- For a fixture day, selection is stable and always ≤4.
- Rooms selected are always actually free for the displayed time.

### Milestone 3: Write a separate ICS file

Goal

- Produce `docs/free_classrooms.ics` (or configured path) alongside existing feeds.

Steps

1) Convert selections into `LectioEvent` (or a new small event type compatible with `write_icalendar`).
2) Write ICS with correct timezone handling.
3) Ensure the output contains only today’s events.

Acceptance

- Opening the ICS in a calendar shows up to 4 “Free: room” events at any time.

### Milestone 4: CLI + script integration

Goal

- Make this runnable in the same automation flow as the existing calendars.

Steps

1) Add CLI arguments, suggested:
	 - `--free-classrooms-out` (path)
	 - `--classrooms` (comma-separated list) OR hardcode the known list first.
2) Update `scripts/update_ics.ps1` (and/or `scripts/update_ics_and_push.ps1`) to also generate the new ICS.

Acceptance

- One command produces both the normal schedule ICS and the free-classrooms ICS.

### Milestone 5: Unit tests

Goal

- Lock in the logic so it doesn’t regress.

Steps

1) Add tests for:
	 - multi-room parsing (`Lokaler:`) expansion
	 - top-4 selection (never >4)
	 - consecutive-free scoring (2 modules beats 1)
2) Use a small HTML fixture derived from the example (minimized, privacy-safe if this ever becomes public).

Acceptance

- `py -m pytest -q` passes.

## Test plan

Unit tests:

		Working directory: C:\Users\Arthu\Lectio
		Command: py -m pytest -q
		Expected outcome: all tests pass

CLI smoke test (after feature is implemented):

		Working directory: C:\Users\Arthu\Lectio
		Command: py -m lectio_sync --fetch --schedule-url "%LECTIO_SCHEDULE_URL%" --out docs/calendar.ics --free-classrooms-out docs/free_classrooms.ics
		Expected stdout contains:
			Wrote <M> events to docs/free_classrooms.ics
		Expected exit code: 0

Manual sanity check:

- Subscribe to the generated ICS.
- Verify that during 08:15–09:15, all suggested rooms are actually free in Lectio.

## Surprises & Discoveries

- `_extract_rooms()` in `free_classrooms.py` re-parses `Lokale:`/`Lokaler:` lines from
  `LectioEvent.description` rather than changing `LectioEvent` itself, keeping backward
  compatibility with the rest of the pipeline.
- The `_filter_events()` function in `cli.py` removes club/extracurricular timed events
  *before* the free-room algorithm runs, so those do not spuriously mark rooms as busy.

## Decision Log

- Decision: Treat breaks between modules as part of “consecutive free time” when merging displayed intervals.
	Rationale: The user goal is “a room you can use continuously”; students do not need separate entries per module when the room remains unused across adjacent modules.
	Date/Author: 2026-02-27 / GitHub Copilot (GPT-5.2)

- Decision: Filter to only the six specified modules and ignore all other times.
	Rationale: Matches the user’s requirement and prevents clutter from after-school events.
	Date/Author: 2026-02-27 / GitHub Copilot (GPT-5.2)

## Outcomes & Retrospective

- All five milestones implemented in a single pass.
- New file: `src/lectio_sync/free_classrooms.py` (algorithm + ICS generation).
- `cli.py` extended with `--free-classrooms-out` (both `--fetch` and file modes).
- `scripts/update_ics.ps1` and `scripts/update_ics_and_push.ps1` accept optional `-FreeClassroomsOut`.
- `tests/test_free_classrooms.py` covers: room extraction, overlap logic, busy-map building,
  ≤4 invariant, merging, all-busy edge case, and an integration smoke-test against the real fixture.