---
title: "Automatic headless cookie refresh via Windows Task Scheduler"
author: "GitHub Copilot"
date: "2026-03-01T00:00:00Z"
status: draft
estimated_effort: "3-4h"
---

# Automatic headless cookie refresh via Windows Task Scheduler

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.
There is no PLANS.md in this repository; this document follows the planning skill at
`.agents/skills/planning/SKILL.md` directly.


## Purpose / Big Picture

Lectio uses a **fixed-expiry session cookie** — the cookie ceases to work roughly 24 hours
after it was issued, regardless of how recently it was used. This means the GitHub Actions
workflow (`update-calendar.yml`), which fetches the schedule once a day, must have a fresh
cookie on every run. Currently the user must manually open a browser, log in, and push the
new cookie every day. This is unsustainable.

The Playwright browser profile used by `scripts/refresh_cookie.ps1` stores the full
Lectio session (not just the cookie value). Because Lectio only forces a full MitID
re-login every few days — not on every page visit — the profile retains a valid long-lived
session even after the cookie-header string itself expires. This means the script can
navigate silently to the schedule page, capture a *fresh* cookie from the session, and push
it to GitHub Secrets, all without displaying any browser window and without requiring MitID.

After this change the user's machine will automatically re-run the Playwright cookie capture
every 20 hours via a Windows Scheduled Task, keeping the GitHub Secret fresh before the
daily workflow fires at 08:05 Copenhagen time. The user only needs to intervene when Lectio
forces a full MitID re-login (expected once every few days rather than daily).


## Progress

- [x] M1: Add `--headless` flag to Python layer (`cookie_refresh.py` + `cli.py`)
- [x] M1: Add `--Headless` switch to `scripts/refresh_cookie.ps1`
- [x] M1: Tests pass (existing + new headless smoke test with a mocked page)
- [x] M2: Create `scripts/auto_refresh_cookie.ps1` (silent, logs to file)
- [x] M2: Create `scripts/register_scheduled_task.ps1` (registers 20-hour Task Scheduler entry)
- [ ] M3: End-to-end verification (run auto script manually, observe log, observe Secret update)
- [x] M3: Update README with setup instructions


## Surprises & Discoveries

(Fill in as work proceeds.)

- Observation: `headless=False` is currently hard-coded in `refresh_cookie()`.
  Evidence: `src/lectio_sync/cookie_refresh.py` line ~157:
  `context = p.chromium.launch_persistent_context(str(resolved_profile), headless=False, ...)`


## Decision Log

- Decision: Add `headless` as a keyword argument to `refresh_cookie()` with default `False`
  so existing behaviour (visible browser for manual runs) is completely unchanged.
  The scheduled task uses the new `--headless` flag.
  Rationale: Zero regression risk; the manual desktop-shortcut flow still pops a real browser window.
  Date/Author: 2026-03-01 / GitHub Copilot

- Decision: Use Windows Task Scheduler (`schtasks.exe`) rather than a Service or a
  polling loop in Python. The task only needs to run once every 20 hours while the user is
  logged in, which is precisely the budget `schtasks` was designed for.
  Rationale: No new runtime dependencies; reversible; survives reboots automatically.
  Date/Author: 2026-03-01 / GitHub Copilot

- Decision: Log the auto-refresh output to
  `%LOCALAPPDATA%\lectio-sync\auto-refresh.log` (overwrite each run, keep last run only).
  Rationale: Keeps log size bounded; one-run history is enough for debugging.
  Date/Author: 2026-03-01 / GitHub Copilot

- Decision: The scheduled task runs `powershell.exe` in a hidden window (WindowStyle Hidden)
  and calls `scripts/auto_refresh_cookie.ps1`, which in turn calls the Python module with
  `--refresh-cookie --headless`. This keeps the logic in one place (Python) and the
  scheduling/logging glue in PowerShell.
  Rationale: Avoids duplicating Playwright logic outside Python; the PowerShell wrapper
  already handles `.env.local` loading and `py` vs `python` detection.
  Date/Author: 2026-03-01 / GitHub Copilot


## Outcomes & Retrospective

Implementation completed 2026-03-01.

All 62 tests pass (60 pre-existing + 2 new headless unit tests).

Changes made:
- `src/lectio_sync/cookie_refresh.py` — added `headless: bool = False` parameter,
  updated docstring, conditional print, and conditional `args` in `launch_persistent_context`.
- `src/lectio_sync/cli.py` — added `--headless` argparse flag; passed to `refresh_cookie()`.
- `scripts/refresh_cookie.ps1` — added `-Headless` switch forwarded to `--headless`.
- `scripts/auto_refresh_cookie.ps1` — new silent wrapper for the scheduled task.
- `scripts/register_scheduled_task.ps1` — new one-time Task Scheduler setup script.
- `tests/test_cookie_refresh_headless.py` — two new unit tests (mocked Playwright).
- `README.md` — new "Automatic cookie refresh" section.

Remaining: M3 end-to-end verification (run `auto_refresh_cookie.ps1` manually and confirm
the GitHub Secret is updated; register the task and confirm it fires).


---

## Context and Orientation

### Repository layout (relevant files)

    src/lectio_sync/cookie_refresh.py   — Playwright login logic (the core to change)
    src/lectio_sync/cli.py              — argparse entry point; routes --refresh-cookie here
    scripts/refresh_cookie.ps1          — interactive PowerShell wrapper (desktop shortcut)
    scripts/auto_refresh_cookie.ps1     — NEW: silent wrapper for the scheduled task
    scripts/register_scheduled_task.ps1 — NEW: one-time setup of the Windows task
    .github/workflows/update-calendar.yml — the daily GH Actions job that needs a fresh cookie

### Key concepts defined

**Cookie header** — a string of `name=value` pairs (e.g. `ASP.NET_SessionId=abc; LectioTicket=xyz`)
that the browser sends with every request to identify itself as the logged-in user. The GitHub
Actions workflow sends this string in an HTTP `Cookie:` header when fetching the schedule.

**Playwright persistent context** — a Chromium browser instance whose cookies, local storage,
and session data are saved to a folder on disk (the "profile directory") so the next launch of
the same profile resumes the previous session. On this machine the profile lives at
`%LOCALAPPDATA%\lectio-sync\playwright-profile`.

**Fixed-expiry cookie** — Lectio sets a concrete `Expires` or `Max-Age` on the session
cookie (~24 h) that is not reset by activity. Compare to a *sliding* expiry that resets on
every request. Because Lectio's expiry is fixed, fetching the calendar daily does not keep
the cookie alive.

**Windows Task Scheduler** — a built-in Windows service (`Task Scheduler` / `schtasks.exe`)
that runs programs on a recurring schedule, even when no console window is open. Tasks are
stored as XML in `C:\Windows\System32\Tasks\` and survive reboots.

**`gh` CLI** — the official GitHub command-line tool (`gh.exe`). The cookie capture script
calls `gh secret set LECTIO_COOKIE_HEADER --body <value>` to update the Actions Secret
without opening a browser. Requires a one-time `gh auth login`.

### How the pieces fit together

    User machine (Task Scheduler, every 20 h)
      └─ auto_refresh_cookie.ps1
           └─ py -m lectio_sync --refresh-cookie --headless --schedule-url <URL>
                └─ cookie_refresh.py: refresh_cookie(headless=True)
                     └─ Playwright (headless Chromium, reuses profile)
                          └─ navigates to SkemaAvanceret.aspx
                               └─ schedule page detected → cookies captured
                                    └─ gh secret set LECTIO_COOKIE_HEADER
                                         └─ GitHub Secret updated ✓

    GitHub Actions (daily 08:05 Copenhagen)
      └─ update-calendar.yml uses LECTIO_COOKIE_HEADER (now always fresh)


---

## Plan of Work

### Milestone 1 — Add `--headless` flag throughout the Python + PowerShell layer

**Scope:** Three small, additive edits. No behaviour changes unless `--headless` is passed.

**1a. `src/lectio_sync/cookie_refresh.py` — add `headless` parameter to `refresh_cookie()`**

Locate the function signature (around line 123):

    def refresh_cookie(
        *,
        schedule_url: str,
        profile_dir: Path | None = None,
        login_timeout_seconds: int = 300,
        secret_name: str = "LECTIO_COOKIE_HEADER",
        github_repo: str | None = None,
        print_cookie: bool = False,
        no_gh: bool = False,
    ) -> int:

Add `headless: bool = False` as the last keyword argument before `no_gh`:

    def refresh_cookie(
        *,
        schedule_url: str,
        profile_dir: Path | None = None,
        login_timeout_seconds: int = 300,
        secret_name: str = "LECTIO_COOKIE_HEADER",
        github_repo: str | None = None,
        print_cookie: bool = False,
        headless: bool = False,
        no_gh: bool = False,
    ) -> int:

Update the docstring to document the new `headless` parameter:

    headless:
        When True the Chromium window is hidden (suitable for unattended/scheduled runs).
        Requires that the persistent profile already holds a valid Lectio session so no
        login page is shown; if a login page appears the script will time-out.
        Default False keeps the existing interactive behaviour.

Find the `launch_persistent_context` call (around line 157):

    context = p.chromium.launch_persistent_context(
        str(resolved_profile),
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
        no_viewport=True,
    )

Replace with:

    context = p.chromium.launch_persistent_context(
        str(resolved_profile),
        headless=headless,
        args=([] if headless else ["--disable-blink-features=AutomationControlled"]),
        no_viewport=True,
    )

The `AutomationControlled` banner suppression is cosmetic; omitting it in headless mode
avoids a runtime warning on some Chromium builds.

Also adjust the opening print statement so it doesn't say "Opening Chromium" when headless:

Find (around line 148):

    print("Opening Chromium — log into Lectio if prompted.")

Replace with:

    if headless:
        print("Running headless Chromium — profile must have an active session.")
    else:
        print("Opening Chromium — log into Lectio if prompted.")

**1b. `src/lectio_sync/cli.py` — expose `--headless` argparse flag**

In the "Cookie refresh" argument block (after `--no-gh`, around line 239), add:

    parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Run the Playwright browser in headless (invisible) mode. "
            "The persistent profile must already hold an active Lectio session; "
            "if the session is expired a full MitID login will be required "
            "(which cannot be completed headlessly). "
            "Use --headless for automated/scheduled runs."
        ),
    )

In the `if args.refresh_cookie:` block (around line 260), pass the new flag:

    return refresh_cookie(
        schedule_url=schedule_url,
        profile_dir=args.cookie_profile_dir,
        login_timeout_seconds=args.cookie_login_timeout,
        secret_name=args.cookie_secret_name,
        github_repo=args.repo,
        print_cookie=args.print_cookie,
        headless=args.headless,
        no_gh=args.no_gh,
    )

**1c. `scripts/refresh_cookie.ps1` — add `-Headless` switch**

At the top of the param block, add the new switch alongside the existing ones:

    [switch]  $Headless

In the command-args section, add:

    if ($Headless)      { $cmdArgs += "--headless" }

Remove the `Read-Host "Press Enter to close"` line only when running headlessly — but since
this is the interactive script that is fine to leave; headless runs go through
`auto_refresh_cookie.ps1` instead.

**Validation for M1:**

Run the existing test suite from the repo root:

    Working directory: C:\Users\Arthu\Lectio
    Command: py -m pytest tests/ -v
    Expected: all previously passing tests still pass; 0 new failures.

Then do a CLI help smoke test:

    Working directory: C:\Users\Arthu\Lectio
    Command: py -m lectio_sync --help
    Expected stdout contains: --headless

Then write a new unit test `tests/test_cookie_refresh_headless.py` that mocks
`playwright.sync_api.sync_playwright` and confirms `launch_persistent_context` is called
with `headless=True` when `headless=True` is passed, and `headless=False` otherwise. The
test must fail before the change and pass after.


### Milestone 2 — Create the silent wrapper and Task Scheduler registration scripts

**Scope:** Two new PowerShell files. No changes to existing files.

**2a. `scripts/auto_refresh_cookie.ps1`**

This is the script the scheduled task calls. It must:
- Never prompt the user (no `Read-Host`)
- Load `.env.local` to get `LECTIO_SCHEDULE_URL`
- Call `py -m lectio_sync --refresh-cookie --headless --schedule-url <URL>`
- Write all output (stdout + stderr) to `%LOCALAPPDATA%\lectio-sync\auto-refresh.log`
  (overwriting on each run so the file stays small)
- Exit with the Python process exit code

Full file content:

    # auto_refresh_cookie.ps1
    #
    # Silent cookie refresh for the Windows Scheduled Task.
    # Called automatically every ~20 hours; never prompts the user.
    # Output is logged to %LOCALAPPDATA%\lectio-sync\auto-refresh.log
    #
    # Prerequisites (one-time, manual):
    #   py -m pip install playwright
    #   py -m playwright install chromium
    #   gh auth login
    #   Run scripts\refresh_cookie.ps1 once interactively so the browser
    #   profile has an active Lectio session.

    $ErrorActionPreference = 'Stop'

    $repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
    Set-Location $repoRoot

    # ── Set up log file ───────────────────────────────────────────────────────
    $logDir = Join-Path $env:LOCALAPPDATA "lectio-sync"
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
    $logFile = Join-Path $logDir "auto-refresh.log"

    # ── Load .env.local ───────────────────────────────────────────────────────
    $envLocal = Join-Path $repoRoot ".env.local"
    if (Test-Path $envLocal) {
        Get-Content $envLocal | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#")) {
                $idx = $line.IndexOf("=")
                if ($idx -gt 0) {
                    $key = $line.Substring(0, $idx).Trim()
                    $val = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
                    if (-not [System.Environment]::GetEnvironmentVariable($key)) {
                        [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
                    }
                }
            }
        }
    }

    $scheduleUrl = $env:LECTIO_SCHEDULE_URL
    if (-not $scheduleUrl) {
        "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR: LECTIO_SCHEDULE_URL is not set. " +
        "Add it to .env.local or set the environment variable." | Tee-Object -FilePath $logFile
        exit 1
    }

    $python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

    $cmdArgs = @(
        "-m", "lectio_sync",
        "--refresh-cookie",
        "--headless",
        "--schedule-url", $scheduleUrl
    )

    # ── Run and capture output ────────────────────────────────────────────────
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] Starting auto cookie refresh..." | Set-Content -Path $logFile

    try {
        & $python @cmdArgs 2>&1 | Tee-Object -FilePath $logFile -Append
        $exitCode = $LASTEXITCODE
    } catch {
        "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] EXCEPTION: $_" | Add-Content -Path $logFile
        $exitCode = 1
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    if ($exitCode -eq 0) {
        "[$timestamp] Auto refresh completed successfully (exit 0)." | Add-Content -Path $logFile
    } else {
        "[$timestamp] Auto refresh FAILED (exit $exitCode). Check log above." | Add-Content -Path $logFile
    }

    exit $exitCode

**2b. `scripts/register_scheduled_task.ps1`**

One-time setup script the user runs once from an elevated (Administrator) PowerShell, or as
a standard user if they only need per-user tasks. The task is registered under the current
user so it does not need Administrator rights.

Full file content:

    # register_scheduled_task.ps1
    #
    # Registers a Windows Scheduled Task that silently refreshes the Lectio
    # session cookie every 20 hours so the GitHub Actions workflow always has
    # a fresh cookie without any manual intervention.
    #
    # HOW TO USE (one-time setup)
    # ----------------------------
    # 1. Complete the prerequisites in scripts\auto_refresh_cookie.ps1 first.
    # 2. Open PowerShell (no Administrator needed for a per-user task) and run:
    #       .\scripts\register_scheduled_task.ps1
    # 3. You will be asked for your Windows password to store the task credentials.
    #
    # To remove the task later:
    #       Unregister-ScheduledTask -TaskName "LectioCookieRefresh" -Confirm:$false
    #
    # To trigger a manual run of the task immediately:
    #       Start-ScheduledTask -TaskName "LectioCookieRefresh"
    #
    # To view the log after a run:
    #       notepad "$env:LOCALAPPDATA\lectio-sync\auto-refresh.log"

    $ErrorActionPreference = 'Stop'

    $taskName   = "LectioCookieRefresh"
    $repoRoot   = Resolve-Path (Join-Path $PSScriptRoot "..")
    $scriptPath = Join-Path $repoRoot "scripts\auto_refresh_cookie.ps1"

    # ── Build the action ──────────────────────────────────────────────────────
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -NonInteractive -File `"$scriptPath`""

    # ── Build the trigger: repeat every 20 hours, starting now ───────────────
    # We create a "once" trigger starting now and attach a RepetitionInterval.
    $startTime = (Get-Date).AddMinutes(1)   # first run in 1 minute so the user can see it works
    $trigger = New-ScheduledTaskTrigger -Once -At $startTime `
        -RepetitionInterval (New-TimeSpan -Hours 20) `
        -RepetitionDuration ([TimeSpan]::MaxValue)

    # ── Settings ──────────────────────────────────────────────────────────────
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable `
        -WakeToRun:$false

    # ── Register as current user (no Administrator required) ─────────────────
    $principal = New-ScheduledTaskPrincipal `
        -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Limited

    # Remove pre-existing task with same name if present
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Removing existing task '$taskName'..."
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }

    Register-ScheduledTask `
        -TaskName  $taskName `
        -Action    $action `
        -Trigger   $trigger `
        -Settings  $settings `
        -Principal $principal `
        -Description "Refreshes the Lectio session cookie every 20 hours using Playwright. Keeps the LECTIO_COOKIE_HEADER GitHub Secret current so the daily calendar sync never fails."

    Write-Host ""
    Write-Host "Task '$taskName' registered successfully." -ForegroundColor Green
    Write-Host "First run will occur at $startTime"
    Write-Host ""
    Write-Host "To verify: open Task Scheduler, find '$taskName', and check 'Last Run Result'."
    Write-Host "To view the log after the first run:"
    Write-Host "  notepad `"$env:LOCALAPPDATA\lectio-sync\auto-refresh.log`""

**Validation for M2:**

Run the auto script manually to prove it works before the task fires:

    Working directory: C:\Users\Arthu\Lectio
    Command: .\scripts\auto_refresh_cookie.ps1
    Expected: Chromium runs headlessly; the schedule page is detected; gh secret set succeeds;
              exit code 0; log file written to %LOCALAPPDATA%\lectio-sync\auto-refresh.log

Then register the task:

    Working directory: C:\Users\Arthu\Lectio
    Command: .\scripts\register_scheduled_task.ps1
    Expected stdout:
      Task 'LectioCookieRefresh' registered successfully.
      First run will occur at ...

Then confirm the task exists:

    Command: Get-ScheduledTask -TaskName "LectioCookieRefresh" | Select-Object TaskName, State
    Expected:
      TaskName              State
      --------              -----
      LectioCookieRefresh   Ready


### Milestone 3 — End-to-end verification and README update

**Scope:** No code changes. Verify the full chain and document setup for future users.

**3a. End-to-end verification**

Wait for the scheduled task to fire (or trigger it manually):

    Command: Start-ScheduledTask -TaskName "LectioCookieRefresh"

After ~60 seconds, read the log:

    Command: Get-Content "$env:LOCALAPPDATA\lectio-sync\auto-refresh.log"
    Expected final line: "[<timestamp>] Auto refresh completed successfully (exit 0)."

Confirm the GitHub Secret was updated:

    Command: gh secret list
    Expected: LECTIO_COOKIE_HEADER appears in the list (updated timestamp or simply present).

Trigger the GH Actions workflow manually to prove the fresh cookie works:

    Command: gh workflow run update-calendar.yml
    Then:    gh run list --workflow=update-calendar.yml --limit 1
    Expected: status "completed", conclusion "success".

**3b. README update**

In `README.md`, add a section after the existing "Cookie refresh" documentation.
Title it "Automatic cookie refresh (Windows Scheduled Task)" and include:

- Why it is needed (fixed-expiry cookies).
- Prerequisites (Playwright installed, `gh auth login` done, profile has at least one manual login).
- The one-time setup command (`.\scripts\register_scheduled_task.ps1`).
- How to verify the task is running (Task Scheduler UI or `Get-ScheduledTask`).
- How to view the log.
- How to remove the task.
- What to do if the task fails (run `scripts\refresh_cookie.ps1` interactively to top up the session).


---

## Concrete Steps

### Step 1 — Edit `src/lectio_sync/cookie_refresh.py`

Open `src/lectio_sync/cookie_refresh.py`.

**Change 1a** — add `headless: bool = False` to the function signature of `refresh_cookie`
(the last keyword argument before `no_gh`).

**Change 1b** — update the docstring to describe `headless`.

**Change 1c** — replace the hard-coded `headless=False` in `launch_persistent_context` with
`headless=headless` and make `--disable-blink-features=AutomationControlled` conditional:

    context = p.chromium.launch_persistent_context(
        str(resolved_profile),
        headless=headless,
        args=([] if headless else ["--disable-blink-features=AutomationControlled"]),
        no_viewport=True,
    )

**Change 1d** — update the "Opening Chromium" print near line 148 to be conditional on `not headless`.

### Step 2 — Edit `src/lectio_sync/cli.py`

**Change 2a** — add the `--headless` argparse argument after `--no-gh`.

**Change 2b** — pass `headless=args.headless` into the `refresh_cookie(...)` call.

### Step 3 — Edit `scripts/refresh_cookie.ps1`

**Change 3a** — add `[switch] $Headless` to the param block.

**Change 3b** — add `if ($Headless) { $cmdArgs += "--headless" }` just before the `# -- Run` section.

### Step 4 — Create `scripts/auto_refresh_cookie.ps1`

See the full file content in Milestone 2a above. Create the file exactly as shown.

### Step 5 — Create `scripts/register_scheduled_task.ps1`

See the full file content in Milestone 2b above. Create the file exactly as shown.

### Step 6 — Write unit test `tests/test_cookie_refresh_headless.py`

The test mocks `playwright.sync_api.sync_playwright` so it does not launch a real browser.
It verifies that `refresh_cookie(schedule_url="https://example.com", headless=True)` calls
`launch_persistent_context` with `headless=True` and `args=[]`, and that calling with
`headless=False` calls it with `headless=False` and `args=["--disable-blink-features=AutomationControlled"]`.

A minimal sketch:

    import pytest
    from unittest.mock import MagicMock, patch, call

    def _make_mock_playwright(schedule_html: str):
        """Return a mock sync_playwright context manager."""
        mock_page = MagicMock()
        mock_page.content.return_value = schedule_html
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = [
            {"name": "ASP.NET_SessionId", "value": "test", "domain": ".lectio.dk"}
        ]
        mock_browser = MagicMock()
        mock_browser.launch_persistent_context.return_value.__enter__ = lambda s: mock_context
        mock_browser.launch_persistent_context.return_value = mock_context
        mock_p = MagicMock()
        mock_p.chromium = mock_browser
        mock_sp = MagicMock()
        mock_sp.__enter__ = lambda s: mock_p
        mock_sp.__exit__ = MagicMock(return_value=False)
        return mock_sp, mock_browser

    SCHEDULE_HTML = "<html><body>m_content_skemamednavigation_skema_skematabel</body></html>"

    @patch("lectio_sync.cookie_refresh._update_github_secret", return_value=True)
    def test_headless_true_passes_headless_flag(mock_gh):
        from lectio_sync.cookie_refresh import refresh_cookie
        mock_sp, mock_browser = _make_mock_playwright(SCHEDULE_HTML)
        with patch("lectio_sync.cookie_refresh._require_playwright", return_value=lambda: mock_sp):
            refresh_cookie(schedule_url="https://www.lectio.dk/lectio/123/SkemaAvanceret.aspx", headless=True)
        _, kwargs = mock_browser.launch_persistent_context.call_args
        assert kwargs["headless"] is True
        assert kwargs["args"] == []

    @patch("lectio_sync.cookie_refresh._update_github_secret", return_value=True)
    def test_headless_false_passes_visible_flag(mock_gh):
        from lectio_sync.cookie_refresh import refresh_cookie
        mock_sp, mock_browser = _make_mock_playwright(SCHEDULE_HTML)
        with patch("lectio_sync.cookie_refresh._require_playwright", return_value=lambda: mock_sp):
            refresh_cookie(schedule_url="https://www.lectio.dk/lectio/123/SkemaAvanceret.aspx", headless=False)
        _, kwargs = mock_browser.launch_persistent_context.call_args
        assert kwargs["headless"] is False
        assert "--disable-blink-features=AutomationControlled" in kwargs["args"]

### Step 7 — Run tests

    Working directory: C:\Users\Arthu\Lectio
    Command: py -m pytest tests/ -v
    Expected: all tests pass; the two new headless tests appear and pass.

### Step 8 — Run `auto_refresh_cookie.ps1` manually

Before registering the scheduled task, confirm the script works:

    Working directory: C:\Users\Arthu\Lectio
    Command: .\scripts\auto_refresh_cookie.ps1
    Expected exit code: 0
    Expected log tail: "Auto refresh completed successfully (exit 0)."

If this fails with "Login page detected" it means the browser profile's Lectio session has
already expired. Fix: first run `.\scripts\refresh_cookie.ps1` interactively (which opens
the visible browser and lets you log in with MitID). After that, re-run
`auto_refresh_cookie.ps1`.

### Step 9 — Register the scheduled task

    Working directory: C:\Users\Arthu\Lectio
    Command: .\scripts\register_scheduled_task.ps1
    Expected: success message with first-run timestamp.

Confirmed with:

    Command: Get-ScheduledTask -TaskName "LectioCookieRefresh" | Format-List TaskName, State, Description
    Expected State: Ready

### Step 10 — Update README.md

Add the new "Automatic cookie refresh" section as described in Milestone 3b.


---

## Validation and Acceptance

The feature is working when all of the following are true:

1. `py -m pytest tests/ -v` passes with the two new headless tests included.
2. Running `.\scripts\auto_refresh_cookie.ps1` manually produces exit code 0 and writes a
   success entry to `%LOCALAPPDATA%\lectio-sync\auto-refresh.log`.
3. `Get-ScheduledTask -TaskName "LectioCookieRefresh"` shows `State: Ready`.
4. After `Start-ScheduledTask -TaskName "LectioCookieRefresh"` runs and finishes (within
   ~60 s), the log file ends with "Auto refresh completed successfully (exit 0)."
5. `gh workflow run update-calendar.yml` completes with conclusion "success" (uses the freshly
   pushed cookie).


## Idempotence and Recovery

Running `register_scheduled_task.ps1` more than once is safe — the script removes any
existing task with the same name before registering the new one.

Re-running `auto_refresh_cookie.ps1` any number of times is safe — it is a read-then-write
operation with no side-effects beyond updating the GitHub Secret and overwriting the log.

If the headless run fails because the Lectio session has expired (MitID required):
1. Run `.\scripts\refresh_cookie.ps1` interactively (the visible browser will open and
   prompt for MitID login).
2. After that succeeds, the profile holds a fresh session and headless runs will work again
   for several more days.

To remove the scheduled task entirely:

    Unregister-ScheduledTask -TaskName "LectioCookieRefresh" -Confirm:$false


## Artifacts and Notes

Expected `auto-refresh.log` after a successful headless run:

    [2026-03-01 06:00:01] Starting auto cookie refresh...
    Browser profile: C:\Users\Arthu\AppData\Local\lectio-sync\playwright-profile
    Running headless Chromium — profile must have an active session.
    Navigating to https://www.lectio.dk/lectio/.../SkemaAvanceret.aspx ...
    Schedule detected — cookies captured.
    Updating GitHub Secret 'LECTIO_COOKIE_HEADER'...
    GitHub Secret 'LECTIO_COOKIE_HEADER' updated successfully.
    [2026-03-01 06:00:45] Auto refresh completed successfully (exit 0).

Expected `auto-refresh.log` when the session has expired (action needed):

    [2026-03-01 06:00:01] Starting auto cookie refresh...
    Browser profile: C:\Users\Arthu\AppData\Local\lectio-sync\playwright-profile
    Running headless Chromium — profile must have an active session.
    Navigating to https://www.lectio.dk/lectio/.../SkemaAvanceret.aspx ...
    ERROR: Timed out after 300s waiting for the schedule page.
    Check that the URL points to SkemaAvanceret.aspx and that you are logged in.
    [2026-03-01 06:05:02] Auto refresh FAILED (exit 1). Check log above.
    → FIX: run .\scripts\refresh_cookie.ps1 interactively to log in with MitID.


## Interfaces and Dependencies

No new Python packages are required. All changes use the existing:
- `playwright.sync_api` (already a dependency, used by `cookie_refresh.py`)
- `subprocess`, `pathlib`, `os`, `sys`, `time`, `urllib.parse` (all stdlib)

PowerShell cmdlets used in the new scripts are all built into Windows PowerShell 5.1+:
- `New-ScheduledTaskAction`, `New-ScheduledTaskTrigger`, `New-ScheduledTaskSettingsSet`,
  `New-ScheduledTaskPrincipal`, `Register-ScheduledTask`, `Get-ScheduledTask`,
  `Unregister-ScheduledTask`, `Start-ScheduledTask` (all in the `ScheduledTasks` module,
  available on Windows 8 / Server 2012 and later).

External tools required (already used by the project):
- `gh` CLI — for `gh secret set`. Must be authenticated (`gh auth login`).
- `py` or `python` — the Python interpreter. Uses the currently selected VS Code interpreter.
