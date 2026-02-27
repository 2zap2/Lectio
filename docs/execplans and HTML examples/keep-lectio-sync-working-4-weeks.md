---
title: "Keep Lectio sync working for 4+ weeks"
author: "GitHub Copilot (GPT-5.2)"
date: "2026-02-26"
status: "draft"
estimated_effort: "2–5h"
---

# Keep Lectio sync working for 4+ weeks

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

There is no PLANS.md in this repository at the time of writing; follow the conventions described in skills-repo/skills/planning/SKILL.md.

## Purpose / Big Picture

Today, the fully automatic setup (GitHub Actions + `--fetch`) depends on a manually captured Lectio session cookie (MitID login is not automated by design). In practice, this cookie can expire at an unpredictable interval. When it expires, GitHub Actions will still run on schedule, but it will fetch a login/access-denied page instead of the schedule, and then the parse step fails.

After completing this plan, the system should be able to run unattended for weeks in the sense that:

1) When everything is healthy, it keeps publishing a fresh `docs/calendar.ics` daily.
2) When the cookie expires (or the schedule URL is wrong), the workflow fails fast with a clear reason, and it raises a visible alert (an auto-created GitHub Issue) that tells you exactly what to update.
3) A novice can refresh the cookie and update the secret in under 5 minutes using documented steps.

This plan does not attempt to bypass MitID or automate 2FA. The goal is operational reliability and minimal babysitting, not automated authentication.

## Progress

- [ ] (2026-02-26) Confirm current behavior on cookie expiry by running the workflow once with an intentionally invalid cookie and observing logs.
- [ ] (2026-02-26) Add a dedicated “preflight fetch” step that detects login/access-denied before parsing.
- [ ] (2026-02-26) Add an auto-issue notification path on scheduled failures (cookie expired / wrong URL), with spam prevention.
- [ ] (2026-02-26) Document cookie refresh procedure and how to validate the schedule URL.
- [ ] (2026-02-26) Add a small regression test (unit test) for the preflight classifier so future changes don’t regress diagnostics.

## Repository orientation (for a new contributor)

- Automated fetch+build runs in .github/workflows/update-calendar.yml.
- Fetch code is in src/lectio_sync/lectio_fetch.py.
- Parse code is in src/lectio_sync/html_parser.py.
- The CLI entry point used in workflows is src/lectio_sync/cli.py (`python -m lectio_sync ...`).

Key constraints:

- The repository intentionally does not automate MitID login.
- We should not print raw HTML to GitHub Actions logs, because it contains private schedule data.

## Milestones

### Milestone 1: Verify the failure modes we must handle

Goal

Produce an evidence-backed list of “what happens” when secrets are wrong.

Steps

1) Trigger a manual workflow_dispatch run of the update workflow with:

    - A valid schedule URL but an invalid cookie, and record the output of `--debug-fetch`.
    - A valid cookie but an intentionally wrong URL, and record the output.

2) Confirm that the fetch diagnostics already include a privacy-preserving “kind” classifier value (login, mitid/login, access-denied, schedule-table-present, etc.).

Acceptance

- We can reliably distinguish these cases from logs:
  - cookie expired / login page
  - access denied
  - wrong schedule URL
  - (rare) compressed/undecoded response

### Milestone 2: Add a preflight fetch step (fail fast, fail clear)

Problem

Right now, we only learn the fetch was wrong after the parser fails.

Approach

Add a small preflight path that fetches exactly one week page and checks it looks like a schedule page, before doing multi-week fetch + parse.

Implementation details

1) In src/lectio_sync/cli.py, introduce a helper that can be reused by both preflight and main fetch:

    - It fetches one week (e.g., the current ISO week) with diagnostics.
    - It classifies the HTML using the existing `_classify_fetched_page`.
    - If kind is not one of: schedule-table-present, schedule-bricks-present, it raises a RuntimeError with:
      - kind
      - HTTP status
      - redacted final URL
      - a short remediation hint (“update LECTIO_COOKIE_HEADER secret”, “verify LECTIO_SCHEDULE_URL points to SkemaAvanceret.aspx”, etc.)

2) Make sure this error path prints no private HTML and no cookie values.

3) Use this preflight in `--fetch` mode before iterating all weeks.

Acceptance

- With an invalid cookie, the run fails before parsing and the error message explicitly says “login/mitid/login/access-denied” (as applicable).
- With a valid cookie+URL, behavior is unchanged and calendar generation still succeeds.

### Milestone 3: Add GitHub Action alerting (auto-create an Issue)

Goal

When the scheduled job fails because the cookie or URL needs updating, a visible alert should be created automatically.

Approach

Update .github/workflows/update-calendar.yml with a failure handler step that runs only on schedule (not workflow_dispatch) and only when the failure matches the expected authentication/URL failures.

Implementation details

1) Add a step after “Fetch Lectio and build ICS” with `if: failure() && github.event_name == 'schedule'`.

2) Use `actions/github-script` (or plain `gh api` using `GITHUB_TOKEN`) to create or update an Issue titled something like:

    - "Lectio cookie expired (automation needs attention)"

3) Spam prevention:

    - Search for an existing open issue with that exact title.
    - If it exists, add a comment with the new run link and latest diagnostics.
    - Otherwise create it.

4) Ensure the issue body includes:

    - What to update: `LECTIO_COOKIE_HEADER` (and possibly `LECTIO_SCHEDULE_URL`)
    - Where to update it: Repo → Settings → Secrets and variables → Actions → Secrets
    - How to confirm fixed: re-run workflow_dispatch and look for “Wrote <N> events…”

Acceptance

- When a scheduled run fails due to cookie expiry, an Issue appears (or is commented on) within the same run.
- When a run fails for other reasons (code bug, dependency outage), it does not create the cookie-expired Issue.

### Milestone 4: Document the “refresh cookie” and “verify URL” playbook

Goal

Make the recovery path clear and fast even for someone who didn’t write the code.

Steps

1) Add a short section to README.md explaining:

    - `LECTIO_SCHEDULE_URL` should be the Advanced Schedule page (SkemaAvanceret.aspx).
    - `LECTIO_COOKIE_HEADER` is the value of the HTTP Cookie header (no leading "Cookie:").
    - The cookie may expire; this is expected.

2) Add step-by-step instructions for refreshing the cookie in a browser:

    - Log into Lectio normally.
    - Open Developer Tools → Network.
    - Reload the schedule page.
    - Click the request for SkemaAvanceret.aspx.
    - Copy the Request Header `Cookie:` value (value part only).
    - Update GitHub Secret `LECTIO_COOKIE_HEADER`.

3) Add a short “how to validate quickly” section:

    - Run the workflow manually (workflow_dispatch).
    - Confirm logs show kind=schedule-table-present (or schedule-bricks-present).

Acceptance

- A new user can fix an expired cookie without guessing which secret to update.

### Milestone 5: Add a regression test for the classifier/preflight

Goal

Lock in the “wrong page” detection behavior.

Steps

1) In tests/test_lectio_fetch.py (or a new test module), add a unit test that exercises `_classify_fetched_page` (or the new preflight helper) with small HTML stubs:

    - a minimal schedule-like HTML containing the expected table id
    - a minimal login-like HTML containing “MitID”
    - a minimal access denied page

2) Assert the classifier output matches the expected kind strings.

Acceptance

- `py -m pytest -q` passes.

## Test plan

Run unit tests locally:

    Working directory: C:\Users\Arthu\Lectio
    Command: py -m pytest -q
    Expected outcome: all tests pass

Run a manual workflow_dispatch with valid secrets:

    Expected outcome: “Wrote <N> events to docs/calendar.ics” and (if changed) a commit is pushed.

Run a manual workflow_dispatch with an invalid cookie:

    Expected outcome: fails fast and points to cookie refresh steps.

## Surprises & Discoveries

- (Leave blank; fill in as you test real failure cases.)

## Decision Log

- Decision: Do not attempt to automate MitID login.
  Rationale: 2FA automation is out of scope and fragile; instead we make cookie expiry detectable, actionable, and low-effort to fix.
  Date/Author: 2026-02-26 / GitHub Copilot (GPT-5.2)

## Outcomes & Retrospective

(Leave blank until implementation is completed.)
