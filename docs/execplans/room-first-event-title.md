---
title: "Reorder calendar event title: room number first"
author: "GitHub Copilot"
date: "2026-03-10T00:00:00Z"
status: completed
estimated_effort: "30m"
---

# Reorder calendar event title: room number first

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.
There is no PLANS.md in this repository; this document follows the planning skill at
`.agents/skills/planning/SKILL.md` directly.


## Purpose / Big Picture

Currently every event written to `docs/calendar.ics` has a title of the form:

    L2a MA - Kasper Prindal-Nielsen (kpn) - 1.59

That is: [class name] - [teacher] - [room number].

When this calendar is displayed inside Google Calendar, Apple Calendar, or a phone lock
screen, only the first few characters are visible. The room number — which is the most
actionable piece of information when you are physically walking to a lesson — is buried
at the end and often cut off.

After this change, every event title will be reordered to:

    1.59 - L2a MA - Kasper Prindal-Nielsen (kpn)

That is: [room number] - [class name] - [teacher].

Events that have no room number keep the existing format ([class] - [teacher]).
Events that have no teacher keep [room] - [class].
Events with neither a room nor a teacher stay as just [class] — no regression.

You can verify the change by running the existing test suite, and then by running
`py -m lectio_sync` against the local fixture HTML and inspecting the generated
`docs/calendar.ics` file for `SUMMARY:` lines.


## Repository orientation

All source files live under `src/lectio_sync/`. The two files you will touch are:

- `src/lectio_sync/html_parser.py` — parses the Lectio HTML schedule and builds
  `LectioEvent` objects. The function `_compose_title` (around line 253 of the file)
  is the single place where the event title string is assembled.

- `tests/test_html_parser.py` — the test suite for the parser. Currently it exercises
  parsing of the local HTML fixture but does not test `_compose_title` directly. You
  will add focused unit tests for `_compose_title` here.

There is no separate "formatter" module; the title is determined entirely inside
`_compose_title` and is never reprocessed by `ical_writer.py`.

A "room number" in this codebase is a string like `1.59` or `2.12`. It is extracted
from the tooltip text by `_parse_tooltip` (which looks for lines starting with
`Lokale:`) and passed as the `room` argument to `_compose_title`. A room value is
a plain string; no regex parsing is needed inside `_compose_title`.


## Milestone 1 — Change `_compose_title` and add unit tests

**Scope.** Modify the one function that builds the event title so that `room` comes
first. Add three unit tests that assert the new ordering under the three meaningful
combinations of room/teacher presence.

**What exists before this milestone.**
`_compose_title` in `src/lectio_sync/html_parser.py` currently reads:

    def _compose_title(base_title: str, tooltip: str, room: str) -> str:
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

**Step 1 — Edit `src/lectio_sync/html_parser.py`.**

Find the function `_compose_title` (search for `def _compose_title`) and replace the
`parts` assembly block — the four lines beginning with `parts = [base_title.strip()]`
— so that room comes first, followed by the class name, followed by the teacher:

    parts = []
    if room:
        parts.append(room)
    parts.append(base_title.strip())
    if teachers:
        parts.append(teachers)
    return " - ".join([p for p in parts if p])

Leave all other lines in the function unchanged (the teacher-extraction loop, the
function signature, etc.).

**Step 2 — Add unit tests to `tests/test_html_parser.py`.**

The existing test file imports `parse_lectio_advanced_schedule_html` from
`lectio_sync.html_parser`. You need to also import `_compose_title` (it is a
module-private helper, but importing it directly in tests is fine for a focused
unit test). Add the following import near the top of the file:

    from lectio_sync.html_parser import _compose_title

Then add a new test class (place it after all existing classes) that covers the
three meaningful combinations. Use `unittest.TestCase` for consistency with the
existing style:

    class ComposeTitleTests(unittest.TestCase):

        def _tooltip_with_teacher(self, teacher: str) -> str:
            # Build a minimal tooltip string that _compose_title can extract
            # a teacher from. The parser looks for lines starting with
            # "Lærer:" (single teacher) or "Lærere:" (multiple teachers).
            return f"Lærer: {teacher}"

        def test_room_teacher_both_present(self) -> None:
            tooltip = self._tooltip_with_teacher("Kasper Prindal-Nielsen (kpn)")
            result = _compose_title("L2a MA", tooltip, "1.59")
            self.assertEqual(result, "1.59 - L2a MA - Kasper Prindal-Nielsen (kpn)")

        def test_room_present_no_teacher(self) -> None:
            # An empty tooltip means no teacher is extracted.
            result = _compose_title("L2a MA", "", "1.59")
            self.assertEqual(result, "1.59 - L2a MA")

        def test_no_room_teacher_present(self) -> None:
            tooltip = self._tooltip_with_teacher("Kasper Prindal-Nielsen (kpn)")
            result = _compose_title("L2a MA", tooltip, "")
            self.assertEqual(result, "L2a MA - Kasper Prindal-Nielsen (kpn)")

        def test_neither_room_nor_teacher(self) -> None:
            result = _compose_title("L2a MA", "", "")
            self.assertEqual(result, "L2a MA")

**Step 3 — Run the full test suite.**

Working directory: `C:\Users\Arthu\Lectio`

    py -m pytest tests/ -v

Expected outcome: all pre-existing tests pass, and the four new `ComposeTitleTests`
tests also pass. Total pass count increases by 4. Zero failures.

Fail-before proof: before editing `_compose_title`, `test_room_teacher_both_present`
will fail with an AssertionError like:

    AssertionError: '1.59 - L2a MA - Kasper Prindal-Nielsen (kpn)' !=
                   'L2a MA - Kasper Prindal-Nielsen (kpn) - 1.59'

Pass-after proof: after the edit, all four tests report `PASSED`.

**Verification with the real fixture (optional but recommended).**

If the local fixture file `Avanceret skema - Lectio - TEC.html` is present, you can do
a quick spot-check to confirm real events are reordered:

Working directory: `C:\Users\Arthu\Lectio`

    py -m lectio_sync --output docs/calendar.ics

Then open `docs/calendar.ics` in a text editor and search for `SUMMARY:`. Confirm that
lines containing a room number (a pattern like `\d+\.\d+`) appear at the *start* of the
summary value, not at the end. For example:

    SUMMARY:1.59 - L2a MA - Kasper Prindal-Nielsen (kpn)

rather than:

    SUMMARY:L2a MA - Kasper Prindal-Nielsen (kpn) - 1.59


## Progress

- [x] (2026-03-10) M1: Edit `_compose_title` in `src/lectio_sync/html_parser.py` to put room first
- [x] (2026-03-10) M1: Add `ComposeTitleTests` to `tests/test_html_parser.py` (4 test cases)
- [x] (2026-03-10) M1: Run `py -m pytest tests/test_html_parser.py -v` — 7 passed, 0 failed


## Surprises & Discoveries

(Fill in as work proceeds.)


## Decision Log

- Decision: Change only `_compose_title`; do not touch `event_model.py`, `ical_writer.py`,
  or any other file.
  Rationale: The title is assembled in exactly one place. Changing any other file would
  be unnecessary scope creep and would not affect the output.
  Date/Author: 2026-03-10T00:00:00Z / GitHub Copilot

- Decision: When room is absent, preserve the original [class] - [teacher] order.
  Rationale: A title of " - L2a MA - ..." (leading separator from an empty room) would
  be ugly and confusing. Filtering with `[p for p in parts if p]` already handles this.
  Date/Author: 2026-03-10T00:00:00Z / GitHub Copilot


## Outcomes & Retrospective

M1 completed 2026-03-10. The single change to `_compose_title` in
`src/lectio_sync/html_parser.py` (reordering `parts` so room is prepended before the
class name) produced the desired title format. All 7 tests pass, including the 4 new
`ComposeTitleTests` cases covering every combination of room/teacher presence. No other
files were modified.
