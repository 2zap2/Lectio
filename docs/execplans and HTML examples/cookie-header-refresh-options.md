---
title: "Cookie header refresh: desktop button approach"
author: "GitHub Copilot"
date: "2026-02-26"
status: "implemented"
estimated_effort: "done"
---

# Cookie header refresh: desktop button approach

This ExecPlan is a living document. The sections Progress, Surprises & Discoveries, Decision Log, and Outcomes & Retrospective must be kept up to date as work proceeds.

There is no PLANS.md in this repository at the time of writing; follow the conventions described in skills-repo/skills/planning/SKILL.md.

## Purpose / Big Picture

GitHub Actions can run the Lectio calendar sync automatically only when the `LECTIO_COOKIE_HEADER` secret contains a valid Lectio session cookie. That cookie is obtained after a MitID login, which cannot be automated. When the cookie expires, automated runs silently fetch a login page instead of the schedule.

After this change, refreshing the cookie is as simple as double-clicking a desktop shortcut. A controlled Chromium window opens, you log in with MitID if needed, the window closes, and the GitHub Secret is updated automatically. The cookie value is never printed to terminal history unless explicitly requested.

The success criteria are:

- Double-click the shortcut -> browser opens -> (login if needed) -> window closes -> GitHub Secret updated -> next scheduled run succeeds.
- The cookie value is never written to tracked files or printed by default.
- A novice with no prior knowledge of the codebase can refresh the cookie in under 2 minutes.

## Non-goals / constraints

- We do not attempt to bypass MitID or automate 2FA.
- We do not scrape cookies from the real browser's encrypted cookie store (Chrome/Edge encrypt at rest; this is brittle and security-sensitive).
- We do not commit cookie values to git.

## Why Playwright (not a "copy from DevTools" paste helper)

An earlier draft of this plan proposed a paste-based helper: the user copies request headers from DevTools, runs a command, and the tool parses the Cookie: value.

The user asked for an even easier UX: "press a button, log in, done."

Playwright solves this cleanly:

- It launches a Chromium window that it controls.
- The user logs in normally in that window.
- Playwright can read cookies from the browser context it manages without touching the real browser's encrypted cookie DB.
- With a persistent profile directory, a still-valid session means the window opens, immediately detects the schedule, and closes without any login step.

## Progress

- [x] (2026-02-26) Create src/lectio_sync/cookie_refresh.py with all Playwright logic.
- [x] (2026-02-26) Add --refresh-cookie flag group to src/lectio_sync/cli.py.
- [x] (2026-02-26) Create scripts/refresh_cookie.ps1 (desktop shortcut target).
- [x] (2026-02-26) Add playwright as optional dependency in pyproject.toml and requirements.txt.
- [x] (2026-02-26) Add .env.local to .gitignore (stores LECTIO_SCHEDULE_URL locally).
- [x] (2026-02-26) Add unit tests in tests/test_cookie_refresh.py (11 tests, all pass).
- [ ] One-time setup: user installs playwright + creates desktop shortcut.
- [ ] End-to-end validation: run shortcut, verify GitHub Secret updated, trigger workflow.

## One-time setup (do this once)

### 1. Install Playwright

Run in your existing Python environment:

    py -m pip install playwright
    py -m playwright install chromium

### 2. Log in to GitHub CLI (if not already)

    gh auth login

### 3. Create the desktop shortcut

Right-click your desktop -> New -> Shortcut.
Target (adjust path if your repo is elsewhere):

    powershell.exe -ExecutionPolicy Bypass -NoExit -File "C:\Users\Arthu\Lectio\scripts\refresh_cookie.ps1"

Name: Refresh Lectio Cookie

### 4. Save your schedule URL locally (done interactively the first run)

The first time you double-click the shortcut and no URL has been set, the script prompts you to paste the URL and offers to save it to .env.local in the repo root. That file is git-ignored so it will never be committed.

Alternatively, set it as a user environment variable:

    $env:LECTIO_SCHEDULE_URL = "https://www.lectio.dk/lectio/..."

## How the shortcut works (every subsequent use)

1. You double-click the desktop shortcut.
2. A PowerShell terminal appears briefly, then Chromium opens.
3. If your session is still valid (persisted profile), the schedule page is detected in seconds and the window closes automatically.
4. If your session has expired, you log in with MitID as you normally would.
5. Once the schedule page is detected, the terminal prints:

       Schedule detected - cookies captured.
       Updating GitHub Secret 'LECTIO_COOKIE_HEADER'...
       GitHub Secret 'LECTIO_COOKIE_HEADER' updated successfully.

6. GitHub Actions will use the new secret on the next scheduled run (or trigger one manually).

## Implementation details

### src/lectio_sync/cookie_refresh.py

Contains:

- `refresh_cookie(...)` - main entry point.
- `_require_playwright()` - import guard; prints install instructions if missing.
- `_is_schedule_page(html)` - True when the Lectio schedule table or bricks are present.
- `_is_login_page(html)` - True when a MitID/login form is detected.
- `_filter_cookies_for_host(cookies, schedule_url)` - keeps only cookies for the Lectio domain.
- `_cookies_to_header(cookies)` - formats `name=value; name=value; ...`.
- `_update_github_secret(name, value, repo)` - shells out to `gh secret set`.

### src/lectio_sync/cli.py additions

New flags, all active only when --refresh-cookie is used:

    --refresh-cookie            Enable this mode (skips all ICS generation).
    --schedule-url              Required: the Lectio Advanced Schedule URL.
    --cookie-profile-dir        Optional: custom persistent profile directory.
    --cookie-login-timeout      Seconds to wait (default 300).
    --cookie-secret-name        Secret name (default LECTIO_COOKIE_HEADER).
    --repo                      Optional: owner/name passed to gh.
    --print-cookie              Print cookie to stdout (off by default).
    --no-gh                     Skip gh; print cookie instead.

### scripts/refresh_cookie.ps1

Wrapper script intended as a desktop shortcut target.

- Loads .env.local if present.
- Prompts for schedule URL if not found; offers to save to .env.local.
- Calls `py -m lectio_sync --refresh-cookie ...`.
- Keeps the terminal open on completion with `Read-Host "Press Enter to close"`.

### Persistent browser profile

Default location (git-ignored, never committed):

    %LOCALAPPDATA%\lectio-sync\playwright-profile

The profile persists the Lectio session between runs, so a still-valid session means no login step is required.

## Test plan

### Unit tests (automated)

    Working directory: C:\Users\Arthu\Lectio
    Command: py -m pytest tests/test_cookie_refresh.py -v
    Expected outcome: 11 passed

All tests pass against the pure helper functions in cookie_refresh.py. Playwright itself is not exercised in unit tests (it requires a real display; that is verified manually).

### Full suite

    Command: py -m pytest -q
    Expected outcome: all tests pass

### Manual end-to-end test (requires valid Lectio account and gh login)

    Double-click shortcut OR run:
    py -m lectio_sync --refresh-cookie --schedule-url "<your url>"

    Expected terminal output:
      Browser profile: ...
      Opening Chromium - log into Lectio if prompted.
      ...
      Schedule detected - cookies captured.
      Updating GitHub Secret 'LECTIO_COOKIE_HEADER'...
      GitHub Secret 'LECTIO_COOKIE_HEADER' updated successfully.

Verify CI still works:

    gh workflow run update-calendar.yml

## Surprises & Discoveries

- Playwright persistent context reuses an existing Chromium session, which means no login is needed on most runs.
- The cookie value is never written to disk by our code; Playwright holds it in memory and passes it directly to `gh secret set --body`.

## Decision Log

- Decision: Use Playwright (controlled browser) rather than a paste-from-DevTools helper.
  Rationale: User asked for "press a button, log in, done" UX. Playwright opens a real Chromium window the user controls; it reads cookies from its own context without touching the real browser's encrypted cookie store. No new UX friction compared to normal login.
  Date/Author: 2026-02-26 / GitHub Copilot

- Decision: Use a persistent Playwright profile stored outside the repo (%LOCALAPPDATA%).
  Rationale: Avoids accidental git-commit of session data; allows session reuse so most runs require no login at all.
  Date/Author: 2026-02-26 / GitHub Copilot

- Decision: Do not print the cookie by default; only print if --print-cookie is set or gh fails.
  Rationale: Prevents cookie from appearing in terminal scroll-back, CI logs, or screenshots.
  Date/Author: 2026-02-26 / GitHub Copilot

## Outcomes & Retrospective

(Fill in after first real end-to-end run.)
