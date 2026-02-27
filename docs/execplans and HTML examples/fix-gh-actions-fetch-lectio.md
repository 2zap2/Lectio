---
title: "Fix GitHub Actions: Fetch Lectio and build ICS"
author: "GitHub Copilot (GPT-5.2)"
date: "2026-02-25"
status: "draft (partially implemented)"
estimated_effort: "2–6h"
---

# Fix GitHub Actions: Fetch Lectio and build ICS

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

There is no PLANS.md in this repository at the time of writing; follow the conventions described in .agents/skills/planning/SKILL.md.

## Purpose / Big Picture

The scheduled GitHub Actions job fails in the “Fetch Lectio and build ICS” step with:

    ValueError: Could not locate Lectio schedule table ... No <table> elements found

After this change, the workflow should reliably fetch the Lectio Advanced Schedule HTML and produce docs/calendar.ics, or fail with a clear, actionable diagnostic that distinguishes:

- “Cookie/URL returned the wrong page (login/403/etc.)”
- “Response was compressed and not decoded correctly”
- “Lectio changed the schedule page HTML structure”

The success signal is that the GitHub Actions job prints “Wrote <N> events to docs/calendar.ics” and commits the updated file when it changes.

## Progress

- [x] (2026-02-25) Identify failure location: parser cannot find any <table> in fetched HTML.
- [x] (2026-02-25) Implement robust HTTP Content-Encoding handling (gzip/deflate) in src/lectio_sync/lectio_fetch.py.
- [x] (2026-02-25) Add unit test covering gzip decompression: tests/test_lectio_fetch.py.
- [x] (2026-02-25) Add fetch-time diagnostics (status/content-type/encoding, redacted URL, page classification) without printing HTML.
- [x] (2026-02-25) Normalize cookie header input (strip accidental 'Cookie:' prefix and surrounding quotes).
- [x] (2026-02-25) Update GitHub Actions workflow to enable safe diagnostics via --debug-fetch.
- [ ] Optional: add debug HTML dump + artifact upload gated behind workflow_dispatch input.
- [ ] Document secret setup + how to verify the fetched page is actually the Advanced Schedule.
- [ ] Validate the fix by re-running the workflow with valid secrets.

## Repository orientation (for a new contributor)

- The GitHub Actions workflow that fails is .github/workflows/update-calendar.yml. It runs:

      python -m lectio_sync --fetch --schedule-url ...

- The fetch implementation is in src/lectio_sync/lectio_fetch.py:
  - iter_weeks_for_window computes which ISO weeks to request.
  - fetch_weeks_html calls fetch_html for each week.
  - fetch_html uses urllib and injects the Cookie header.

- The parser is in src/lectio_sync/html_parser.py. It expects the Advanced Schedule page to contain a table with id:

      m_Content_SkemaMedNavigation_skema_skematabel

  and it errors if it cannot find it.

## Likely root causes (ranked)

1) HTTP response compression not handled

In CI, many servers return compressed responses. urllib does not automatically decompress gzip/deflate. If the code decodes compressed bytes as UTF-8, BeautifulSoup may see no HTML tags at all, leading to “No <table> elements found”.

Status: mitigated by the change in src/lectio_sync/lectio_fetch.py.

Additional note: Some servers may return Brotli (Content-Encoding=br). We now request identity encoding to avoid this; if we still see br, we need either a Brotli decoder or different headers.

2) Invalid/expired cookie or wrong schedule URL

If LECTIO_COOKIE_HEADER is expired/invalid, or LECTIO_SCHEDULE_URL is not the Advanced Schedule page (SkemaAvanceret.aspx), Lectio may return a login page, an access denied page, or a redirect target that does not include the expected table.

This is still possible even after (1).

3) Lectio changed their HTML structure

If the Advanced Schedule is no longer a table-based layout, the parser selection strategy described in README.md will need updating.

## Milestones

### Milestone 1: Make fetch resilient to compressed responses (DONE)

Scope

- Decode gzip/deflate responses in src/lectio_sync/lectio_fetch.py.
- Add a unit test so the behavior is locked in.

Proof

    Working directory: C:\Users\Arthu\Lectio
    Command: py -m pytest -q
    Expected outcome: all tests pass

### Milestone 2: Add safe, actionable diagnostics on fetch+parse failures

Goal

When parsing fails in GitHub Actions, the logs should answer: “What page did we fetch?” without dumping private schedule contents.

Implementation steps

1) Extend fetch_html (or fetch_weeks_html) to optionally return metadata:
   - final URL after redirects (resp.geturl())
   - HTTP status code
   - Content-Type and Content-Encoding
   - byte length and decoded length

2) Update src/lectio_sync/cli.py to include the metadata in the error path for --fetch.

Implementation status: DONE. The CLI now supports --debug-fetch and emits a privacy-preserving summary on failure even without HTML dumping.

3) Add an opt-in “dump” mode for manual debugging:
   - New CLI flag: --debug-dump-html-dir <path>
   - On failure (or always when enabled), write the fetched HTML for the failing week to that directory.
   - Do not print the HTML to stdout/stderr.

Implementation status: DONE (CLI flag exists). Artifact upload remains optional work.

Acceptance

- Running with invalid secrets produces an error that mentions status/final URL/content-type/encoding and suggests “cookie expired / wrong URL”.
- Running with valid secrets still succeeds and writes calendar.

### Milestone 3: Improve GitHub Actions workflow for debugging

Goal

Make it easy to debug failures without modifying code every time.

Workflow changes in .github/workflows/update-calendar.yml

- Add --debug to the lectio_sync invocation (safe: current --debug only prints parser stats).
- Optionally, on workflow_dispatch, allow enabling dump mode and uploading artifacts.

Example approach

- Add an input in workflow_dispatch:
  - debug_dump_html: boolean

- If enabled:
  - pass --debug-dump-html-dir "debug-html"
  - add actions/upload-artifact step to upload "debug-html" on failure

Acceptance

- A workflow_dispatch run with debug enabled uploads an artifact when the job fails.
- Scheduled runs remain privacy-preserving by default (no HTML artifacts).

### Milestone 4: Document secrets and verification steps

Update README.md (or a short docs page) with:

- LECTIO_SCHEDULE_URL must point to SkemaAvanceret.aspx (Advanced Schedule)
- LECTIO_COOKIE_HEADER must be the literal HTTP Cookie header value (name=value; name2=value2; ...)
- How to verify the fetched response is correct:
  - Save fetched HTML (dump mode) and confirm it contains the expected table id
  - Confirm that the page is not a login/access-denied page

Acceptance

- A new contributor can set secrets correctly without guesswork.

## Test plan

Unit tests

    Working directory: C:\Users\Arthu\Lectio
    Command: py -m pytest -q
    Expected outcome: N passed, 0 failed

Manual smoke test (requires valid secrets)

    Working directory: C:\Users\Arthu\Lectio
    Set env:
      LECTIO_SCHEDULE_URL=<your url>
      LECTIO_COOKIE_HEADER=<your cookie header>
    Command:
      py -m lectio_sync --fetch --schedule-url "%LECTIO_SCHEDULE_URL%" --tz "Europe/Copenhagen" --days-past 7 --days-future 90 --out docs/calendar.ics --debug
    Expected outcome:
      - exits 0
      - prints “Wrote <N> events to docs/calendar.ics”

## Surprises & Discoveries

- Observation: The failure reported “No <table> elements found”, which can happen not only when Lectio HTML structure changes, but also when the fetched HTTP payload is compressed and decoded without decompression.
  Evidence: urllib does not automatically decompress gzip/deflate; adding decompression is a low-risk hardening change.

## Decision Log

- Decision: Fix compression handling using the Python standard library (gzip/zlib) rather than adding a new dependency such as requests.
  Rationale: Keep the project lightweight and avoid changing dependency management; the needed behavior is small and testable.
  Date/Author: 2026-02-25 / GitHub Copilot (GPT-5.2)

## Outcomes & Retrospective

(Leave blank until Milestones 2–4 are complete.)
