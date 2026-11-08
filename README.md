# Lectio “Advanced Schedule” HTML → iCal (.ics) Feed

**Automatic updates run locally through the saved browser login.** The PC builds
and checks all four calendars, then publishes them together to the existing Pages
URLs. It catches up after logon/resume and no longer uploads cookies to GitHub.
See [local sync setup and recovery](docs/local-sync.md).

The original file conversion mode is described below.

A small daily sync tool that:
1) reads a **Lectio “Avanceret skema / Advanced Schedule” HTML** file, and
2) converts every schedule entry into a **valid iCalendar (.ics)** file.

You then **host the `.ics` on GitHub Pages** and subscribe to it from Apple Calendar.

---

## Goal
- **Input**: A local Lectio HTML file (the “print” / “advanced schedule” view).
- **Output**: A single `.ics` file containing all events.
- **Hosting**: Publish the `.ics` via GitHub Pages.
- **Apple Calendar**: Subscribe to the GitHub Pages URL (auto-updates).
- **Run cadence**: Regenerate daily at **08:00 Europe/Copenhagen**.
- **Idempotent**: Stable `UID` per event so changes overwrite old entries.

Non-goals (unless you ask):
- Building a UI
- Automating Lectio login / scraping behind 2FA
- Writing directly into iCloud via CalDAV (subscription feed is simpler)

---

## Getting Started

### Prerequisites
- Python 3.11+
- `beautifulsoup4`, `lxml`, `python-dateutil` — installed automatically with the package
- Optional: `playwright` for automated cookie refresh

### Install
```powershell
py -m pip install -e .
```

### Local run (file mode)
```powershell
.\scripts\update_ics.ps1 -HtmlPath path\to\lectio.html
```

### Subscribe URL
Once hosted on GitHub Pages:
```
https://<your-github-username>.github.io/<repo-name>/calendar.ics
```

### GitHub Actions setup
1. Set repository secrets: `LECTIO_SCHEDULE_URL` and `LECTIO_COOKIE_HEADER` (and optionally `LECTIO_ASSIGNMENTS_URL`).
2. Trigger `update-calendar.yml` via **Actions → Run workflow** to verify.
3. GitHub Pages serves updated `.ics` files from `docs/` daily at 08:05 Europe/Copenhagen.

---

## How the sync works (Apple Calendar)
Apple Calendar can subscribe to an online `.ics` feed (read-only). When the `.ics` changes, Apple Calendar updates.

This project generates the `.ics` file and publishes it on GitHub Pages.

Notes:
- Apple Calendar subscription refresh is controlled by Apple and may lag (minutes to hours).
- This repo can fetch Lectio HTML automatically only if you provide a valid logged-in session cookie (MitID login itself is not automated).

---

## Tech choice
### Language
- **Python 3.11+**

### Key libraries
- `beautifulsoup4` + `lxml` (HTML parsing)
- `python-dateutil` (timezone helpers)

We will implement iCalendar writing ourselves to meet the strict RFC5545 escaping and line-folding requirements.

## Project structure

- `src/lectio_sync/__init__.py`
- `src/lectio_sync/html_parser.py` — Lectio HTML → event list
- `src/lectio_sync/event_model.py` — `LectioEvent` dataclass
- `src/lectio_sync/ical_writer.py` — events → RFC 5545 iCalendar output
- `src/lectio_sync/free_classrooms.py` — derives free-classroom events from schedule
- `src/lectio_sync/cli.py` — argparse CLI; orchestrates fetch + parse + write
- `src/lectio_sync/config.py` — `Config` dataclass + environment-variable loaders
- `src/lectio_sync/lectio_fetch.py` — HTTP fetch with session cookie
- `src/lectio_sync/cookie_refresh.py` — Playwright-based cookie capture
- `tests/` — pytest unit tests
- `scripts/` — PowerShell helper scripts
- `docs/calendar.ics` — schedule feed (GitHub Pages)
- `docs/assignments.ics` — assignment deadline feed (GitHub Pages)
- `docs/free_classrooms.ics` — free classroom feed (GitHub Pages)
- `.github/workflows/update-calendar.yml` — daily CI build

---

## Configuration
We will support configuration via environment variables (and optionally a `.env` file).

Planned variables:
- `LECTIO_HTML_PATH` — full path to the Lectio HTML file
- `LECTIO_TIMEZONE` — default: `Europe/Copenhagen`
Optional filtering:
- `SYNC_DAYS_PAST` — include events starting from N days back (default: 7)
- `SYNC_DAYS_FUTURE` — include events up to N days forward (default: 90)
- `DELETE_MISSING` — default: `true`. Current implementation regenerates a full feed each run, so missing items are naturally removed.
- `EMIT_CANCELLED_EVENTS` — default: `false`. If `true`, cancelled entries are emitted as `STATUS:CANCELLED` instead of being dropped.

CLI overrides:
- `--days-past N`
- `--days-future N`
- `--delete-missing` / `--keep-missing` (compatibility flag; feed is still fully regenerated)
- `--emit-cancelled-events`
- `--debug` (prints parser stats plus window filter before/after counts)

## Environment

- This project does not create or manage Python virtual environments automatically. Do NOT run `python -m venv`, `py -m venv`, `virtualenv`, `conda create`, `pipenv`, or `poetry env` as part of development or automation in this repository. Assume you will use your preferred Python interpreter or activation method outside of this repo. Guidance for contributors and automation lives in `.github/copilot-instructions.md` and `scripts/bootstrap.ps1`.

---

## Lectio parsing and iCal rules (MUST FOLLOW)
This section is the authoritative parsing spec.

### 1) Locate the schedule table
All schedule data is contained in:
```html
<table id="m_Content_SkemaMedNavigation_skema_skematabel">
  ...
  <td data-date="YYYY-MM-DD">...</td>
</table>
```

Parser selection strategy:
- First try exact table id: `m_Content_SkemaMedNavigation_skema_skematabel`
- Fallback: first `<table>` that contains both `td[data-date]` and `a.s2skemabrik`

### 2) Locate date cells
Each day column is identified by:

```html
<td data-date="YYYY-MM-DD">
```

### 3) Identify all activities (schedule bricks)
Each activity is represented by:

```html
<a class="s2skemabrik ...">
```

Only these `<a>` elements represent real events.

Ignore all other elements in the same container, including:
- `<div class="s2module-bg">`
- `<div class="s2module-info">`
- decorative elements / time markers / layout backgrounds

For each activity, extract:
- the `data-tooltip` attribute (primary and most detailed data source)
- the content from `<div class="s2skemabrikcontent">` (fallback for title/room/etc.)

### 4) Text normalization (before parsing)
- trim whitespace (start/end)
- convert `\r\n` → `\n`
- remove duplicate blank lines
- remove leading `- ` from list items
- preserve category headers like `Homework:`, `Note:`, `Additional info:`
- remove any HTML tags if present
- normalize unicode (retain bullets like `•` if possible)

### 5) Tooltip extraction rules
Tooltip text contains several lines; format varies.

#### 5.1 Title
- The first meaningful line is the event title.
- If the first line is `Ændret!` or `Changed!`, ignore it and use the next line.
- If the first meaningful line matches the date/time pattern, the title is missing → use `.s2skemabrikcontent` text as title.

#### 5.2 Date and time
Look for a line matching:
- `DD/MM-YYYY HH:MM til HH:MM`
- `DD/MM-YYYY Hele dagen` / `DD/MM-YYYY All day`

Convert date `DD/MM-YYYY` → `YYYY-MM-DD`.

#### 5.3 All day events
If the line contains `Hele dagen` or `All day`:
- Use all-day iCal formatting:
  - `DTSTART;VALUE=DATE:YYYYMMDD`
  - `DTEND;VALUE=DATE:YYYYMMDD`
- `DTEND` must be the **same** date (do not add one day).

#### 5.4 Class/Group
Lines beginning with `Hold:` contain one or multiple class names.

#### 5.5 Teacher(s)
Lines starting with `Lærer:` / `Lærere:` may contain multiple teachers separated by commas.

#### 5.6 Room
Line starting with `Lokale:` contains the room (e.g. `2.03`, `X DVR`).

#### 5.7 Notes, homework, additional info
Everything after the `Lokale:` line belongs in `DESCRIPTION`.
Keep it exactly as written, including section headers.

### 6) Ignore the HTML layout
Do not use box heights / pixel positions / module background blocks / graphic separators.
Start/end time must come **solely** from tooltip text.

### 7) iCal UID and DTSTAMP
For stable identity:
- If `data-brikid="ABS123..."` exists → `UID` must be `ABS123@lectio.dk`
- Otherwise generate a stable hash from `(tooltip + date)`

`DTSTAMP` is the generation timestamp.

### 8) iCal escaping and line folding (RFC5545)
- Max line length: 75 characters
- Fold with: newline + single space (`\n `)
- Use `\n` for line breaks inside `DESCRIPTION`
- Keep commas and colons unescaped unless required by iCal standard
- `SUMMARY` and `LOCATION` are single-line (fold if needed)

### 9) VEVENT structure
Each event must be:

```
BEGIN:VEVENT
UID:<unique-id>
DTSTAMP:<timestamp>
SUMMARY:<title>
DTSTART:<YYYYMMDDTHHMMSS>    or DTSTART;VALUE=DATE:YYYYMMDD
DTEND:<YYYYMMDDTHHMMSS>      or DTEND;VALUE=DATE:YYYYMMDD
LOCATION:<room>
DESCRIPTION:<full tooltip text, including notes and categories>
END:VEVENT
```

### 10) VCALENDAR structure

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//LectioParser//Custom//EN
...events...
END:VCALENDAR
```

### Domain rules
- The schedule should include **subject + teacher + room** in title when available.
- Notes + homework must be included.
- Cancelled lessons must be removed.
- Changes should overwrite old schedule entries (achieved via stable `UID`).

---

## Timezone
- Default timezone: `Europe/Copenhagen`.
- Timed events will be written as local floating times (no `Z`) unless you ask to include `VTIMEZONE`.

---

## Running daily at 08:00
You have two realistic options:

### Option A: Run locally (recommended when HTML is local)
Use Windows Task Scheduler to run the CLI at 08:00.

This repo includes helper scripts:
- `scripts/update_ics.ps1` (generate `docs/calendar.ics`)
- `scripts/update_ics_and_push.ps1` (generate + `git commit` + `git push`)

### Option B: GitHub Actions (only if the HTML is in the repo)
GitHub Actions cannot log into Lectio with 2FA, so it can only regenerate the `.ics` automatically if the input HTML is already committed or otherwise available without login.

Important:
- For fully automatic updates without a computer running, use GitHub Actions + the `--fetch` mode (cookie-based).
- If you keep HTML local only, disable the scheduled workflow and use Task Scheduler + `scripts/update_ics_and_push.ps1`.
- Fully automatic fetch requires a valid Lectio session cookie stored as a GitHub Secret. Review privacy/security implications.

## Automatic cookie refresh (Windows Scheduled Task)

The HTTP fetcher now uses a cookie jar: renewed `Set-Cookie` values are used
for subsequent weeks, assignments, rooms and the additional student's feed.
The previous claim that every Lectio cookie has a fixed 24-hour lifetime was
not established; server expiry, browser session cookies and SSO are distinct.

The refresher reuses a dedicated browser profile and explicitly saves/restores
its session cookies (including SSO cookies). A persistent Chromium profile alone
does not guarantee that session cookies survive closing the browser. Server-side
expiry is still respected; no local expiry timestamps are extended. When the
Lectio session expires, the refresher first visits the normal Lectio login
endpoint so the identity provider can reuse its saved SSO login. An interactive
login is only needed when Lectio or its identity provider requires it.

Cookie values are kept inside `%LOCALAPPDATA%\lectio-sync\playwright-profile`,
never in the repository. Only cookies matching the Lectio URL are sent to GitHub;
SSO cookies stay in the local profile. Background runs never print cookies or open
a login window. Exit code 2 means a manual refresh/login is required.

See [the setup guide](docs/setup-student-calendar-and-session.md) for the new
student feed and optional server-side cookie persistence in GitHub Actions.

### Prerequisites (one-time setup)

1. Install Playwright and the Chromium browser:
   ```powershell
   py -m pip install playwright
   py -m playwright install chromium
   ```
2. Authenticate the GitHub CLI:
   ```powershell
   gh auth login
   ```
3. Run the interactive cookie refresh **at least once** so the browser profile has an active
   Lectio session (this is the only time you need MitID until the session fully expires):
   ```powershell
   .\scripts\refresh_cookie.ps1
   ```
4. Make sure `LECTIO_SCHEDULE_URL` is set (either in `.env.local` or as an environment
   variable).

### Register the scheduled task

Run once from any PowerShell window (no Administrator required):

```powershell
.\scripts\register_scheduled_task.ps1
```

The task (`LectioCookieRefresh`) runs at logon, after resume and every 30 minutes
while the computer and network are available. The first periodic run is one minute
after registration. Re-run registration to update an existing task.

### Verify the task is registered

```powershell
Get-ScheduledTask -TaskName "LectioCookieRefresh" | Select-Object TaskName, State
```

Expected output:
```
TaskName              State
--------              -----
LectioCookieRefresh   Ready
```

### View the log

```powershell
notepad "$env:LOCALAPPDATA\lectio-sync\auto-refresh.log"
```

A successful run ends with:
```
[2026-03-01 06:00:45] Auto refresh completed successfully (exit 0).
```

### Trigger a manual run

```powershell
Start-ScheduledTask -TaskName "LectioCookieRefresh"
```

### Remove the task

```powershell
Unregister-ScheduledTask -TaskName "LectioCookieRefresh" -Confirm:$false
```

### What to do if the task fails

If the log shows `ERROR: Timed out … waiting for the schedule page`, the Lectio session in
the browser profile has expired and Lectio is requiring a full MitID re-login.

Fix: run `.\scripts\refresh_cookie.ps1` interactively (the visible browser will open and
let you log in with MitID). After that succeeds, the profile holds a fresh session and
headless runs can reuse that login until Lectio or SSO requires authentication again.

---

## Assignments feed (Opgaver)

In addition to the schedule feed, this repo generates a second iCalendar feed containing only upcoming
Lectio assignment deadlines, sourced from the **OpgaverElev.aspx** page.

### Output files

| File | Description |
|---|---|
| `docs/calendar.ics` | Timetable / schedule events |
| `docs/assignments.ics` | Upcoming assignment deadlines (calendar name: *lectio opgaver*) |

Both files are published via GitHub Pages and updated on the same schedule.

### Assignment event format

Each assignment becomes an **all-day event** on its *Frist* (due date):

- **SUMMARY** — `{Status} • {Opgavetitel} • {Hold} • {Elevtid}`
- **DESCRIPTION** — the *Opgavenote* text from Lectio
- **DTSTART/DTEND** — the due date (all-day; DTEND is the following day per RFC 5545)
- **UID** — `{exerciseid}@lectio.dk` (stable; updates overwrite, removed items disappear)

Only assignments whose due date is **≥ today** (Europe/Copenhagen) are included.

### Subscribing

Once hosted, subscribe in your calendar client to:
- `https://<your-github-username>.github.io/<repo-name>/assignments.ics`

You can also use the `webcal://` equivalent.

### Building locally (file mode)

```powershell
# Schedule + assignments in one run
py -m lectio_sync `
  --html path\to\lectio.html `
  --out docs\calendar.ics `
  --assignments-html path\to\opgaver.html `
  --assignments-out docs\assignments.ics `
  --tz Europe/Copenhagen
```

```powershell
# Using the PowerShell helper script
.\scripts\update_ics.ps1 `
  -HtmlPath path\to\lectio.html `
  -AssignmentsHtmlPath path\to\opgaver.html
```

### Fetching via CI (GitHub Actions)

Set the GitHub secret `LECTIO_ASSIGNMENTS_URL` to your `OpgaverElev.aspx` URL.
The `update-calendar.yml` workflow will then fetch and commit both ICS feeds automatically.

---

## Free classroom finder (`free_classrooms.ics`)

A third optional feed highlights up to **4 free classrooms** at any time during the school day.

### How it works

1. The existing schedule events for **today** are scanned for room occupation.
2. Only the six fixed module windows are considered:

   | # | Start | End |
   |---|-------|-----|
   | 1 | 08:15 | 09:15 |
   | 2 | 09:20 | 10:20 |
   | 3 | 10:30 | 11:30 |
   | 4 | 12:10 | 13:10 |
   | 5 | 13:20 | 14:20 |
   | 6 | 14:30 | 15:30 |

3. For each module slot, all univese rooms that are **not busy** are ranked by how many consecutive modules they remain free (longer = higher rank). The **top 4** are selected.
4. If the same room stays in the top 4 for adjacent modules it is merged into a single VEVENT.
5. Multi-room events (`Lokaler: X, Y`) correctly mark **each** listed room as busy.

### Classroom universe

Rooms tracked: `0.75`, `0.76`, `0.77`, `1.02`, `1.03a`, `1.07`, `1.09`, `1.10`,
`1.59`, `1.60`, `1.61`, `1.62`, `1.64`, `1.65`, `2.01`, `2.03`, `2.04`, `2.05`,
`2.27`, `2.29`, `2.31`.

### Output

- **Summary**: `Free: <room>` (e.g. `Free: 1.07`)
- **LOCATION**: room name
- **DTSTART/DTEND**: start and end of the merged free window
- **UID**: deterministic (`free-YYYYMMDD-<room>-<HHMM>-<HHMM>@lectio-sync`)

Maximum 4 events overlap at any point in time.

### Building locally (file mode)

```powershell
py -m lectio_sync `
  --html path\to\lectio.html `
  --out docs\calendar.ics `
  --free-classrooms-out docs\free_classrooms.ics `
  --tz Europe/Copenhagen
```

```powershell
.\scripts\update_ics.ps1 `
  -HtmlPath path\to\lectio.html `
  -FreeClassroomsOut docs\free_classrooms.ics
```

### Fetching via CI

```powershell
py -m lectio_sync `
  --fetch `
  --schedule-url "%LECTIO_SCHEDULE_URL%" `
  --out docs\calendar.ics `
  --free-classrooms-out docs\free_classrooms.ics
```

### Subscribing

Once hosted on GitHub Pages, subscribe to:
```
https://<your-github-username>.github.io/<repo-name>/free_classrooms.ics
```

---

## Publish on GitHub Pages
We will write the output to `docs/calendar.ics`. Configure GitHub Pages to serve from the `docs/` folder.

Apple Calendar subscription URL will be:
- `https://<your-github-username>.github.io/<repo-name>/calendar.ics`

In Apple Calendar:
- File → New Calendar Subscription…
- Paste the URL (or `webcal://...` equivalent)
- Set auto-refresh to a reasonable interval.

Tip: Apple Calendar subscriptions are read-only. This is expected.

