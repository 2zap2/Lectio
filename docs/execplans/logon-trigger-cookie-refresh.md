---
title: "Replace 20-hour interval trigger with logon + resume-from-sleep triggers"
author: "GitHub Copilot"
date: "2026-03-10T00:00:00Z"
status: draft
estimated_effort: "1h"
---

# Replace 20-hour interval trigger with logon + resume-from-sleep triggers

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.
There is no PLANS.md in this repository; this document follows the planning skill at
`.agents/skills/planning/SKILL.md` directly.

This plan builds on the prior `docs/execplans/auto-cookie-refresh.md`, which implemented
headless cookie refresh and the 20-hour Windows Scheduled Task. All code from that plan
is already in place. Read that document for background on why the cookie expires and why
the Playwright profile is used.


## Purpose / Big Picture

The Windows Scheduled Task that refreshes the Lectio session cookie currently fires every
20 hours regardless of whether the computer is actually on at that moment. Because the PC
is only used during the workday (roughly 08:00–17:00) and may be started multiple times
per day, the 20-hour interval can leave the cookie stale before it is next refreshed, or
can fire at inconvenient times.

After this change the task will fire in two situations that naturally align with "the PC
just became usable":

1. Every time the user logs in to Windows after a full start-up or reboot.
2. Every time the PC wakes from sleep or hibernate.

The user will be able to verify the change by opening Windows Task Scheduler, finding the
`LectioCookieRefresh` task, and seeing two triggers (one `At log on` trigger and one
`On an event` trigger) instead of the old `One time` repeating trigger.


## Background: why two triggers are needed

A "logon trigger" in Windows only fires when a new Windows session is opened — that is,
when the user types a password/PIN at the Welcome screen after a full boot or after a
complete sign-out. Simply waking the PC from sleep does not create a new session; the
screen is just unlocked, so no logon event fires.

To also catch wake-from-sleep, Task Scheduler supports "event-based triggers" that watch
the Windows event log. Every time Windows finishes resuming from sleep or hibernate it
writes an event with:

    Log:    System
    Source: Microsoft-Windows-Power-Troubleshooter
    ID:     1

A second, event-based trigger that listens for this event will fire the cookie refresh
on every resume. Together the two triggers cover all the cases the user cares about.


## Scope of changes

Only one file changes: `scripts/register_scheduled_task.ps1`. The trigger-building block
(currently lines ~34–38) is replaced with two triggers. The action, settings, and
registration logic remain identical. No Python code and no GitHub Actions workflow are
touched.


## Milestone 1 — Update `register_scheduled_task.ps1` and re-register the task

The goal of this milestone is to replace the old trigger block with two new triggers and
re-run the registration script so the live scheduled task is updated.

### What to change

In `scripts/register_scheduled_task.ps1`, locate the section that builds the trigger
(currently labelled `Build the trigger: repeat every 20 hours`). Replace it entirely with
the two-trigger block shown below. Nothing else in the file changes.

Old block (to remove):

    # ── Build the trigger: repeat every 20 hours, starting in 1 minute ───────
    # Omit -RepetitionDuration so Windows uses its default (indefinite).
    # [TimeSpan]::MaxValue is rejected on some Windows builds (HRESULT 0x80041318).
    $startTime = (Get-Date).AddMinutes(1)
    $trigger = New-ScheduledTaskTrigger `
        -Once `
        -At $startTime `
        -RepetitionInterval (New-TimeSpan -Hours 20)

New block (to add in its place):

    # ── Build triggers ────────────────────────────────────────────────────────
    # Trigger 1: fires every time THIS user logs on (after boot / reboot).
    $triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

    # Trigger 2: fires every time the PC wakes from sleep or hibernate.
    # Task Scheduler's New-ScheduledTaskTrigger does not expose event triggers
    # directly, so we build one using the CIM (WMI) layer.
    # The subscription below is an XPath query against the Windows System event log.
    # Power-Troubleshooter EventID 1 is written on every successful resume from sleep.
    $resumeXml = @'
    <QueryList>
      <Query Id="0" Path="System">
        <Select Path="System">
          *[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter']
            and EventID=1]]
        </Select>
      </Query>
    </QueryList>
    '@

    $cimClass   = Get-CimClass -ClassName MSFT_TaskEventTrigger `
                               -Namespace Root/Microsoft/Windows/TaskScheduler
    $triggerResume = $cimClass | New-CimInstance -ClientOnly -Property @{
        Enabled      = $true
        Subscription = $resumeXml
    }

    # Both triggers are passed as an array to Register-ScheduledTask below.
    $triggers = @($triggerLogon, $triggerResume)

Also update the `Register-ScheduledTask` call: change `-Trigger $trigger` to
`-Trigger $triggers`.

After making this edit, remove or update the `Write-Host "First run will occur at $startTime"`
line (the logon trigger has no fixed start time), replacing it with something like:

    Write-Host "Task will run at next logon and on every resume from sleep."

### How to apply the change

Edit the file as described, then run the registration script from the repository root:

    Working directory: C:\Users\Arthu\Lectio
    Command: .\scripts\register_scheduled_task.ps1
    Expected stdout (excerpt):
      Removing existing task 'LectioCookieRefresh'...
      Task 'LectioCookieRefresh' registered successfully.
      Task will run at next logon and on every resume from sleep.
    Expected exit code: 0

### How to verify the triggers are correct

Open Windows Task Scheduler (search "Task Scheduler" in the Start menu), navigate to
`Task Scheduler Library`, and open `LectioCookieRefresh`. Click the `Triggers` tab. You
should see two entries:

    At log on of <your username>    Enabled
    On an event (Power-Troubleshooter, ID 1)    Enabled

The old `One Time` repeating trigger should no longer be present.

### How to test immediately without waiting for a logon or sleep cycle

To trigger a manual run:

    Working directory: any
    Command: Start-ScheduledTask -TaskName "LectioCookieRefresh"

Then inspect the log:

    Command: notepad "$env:LOCALAPPDATA\lectio-sync\auto-refresh.log"
    Expected last lines:
      [YYYY-MM-DD HH:MM:SS] Starting auto cookie refresh...
      ...
      [YYYY-MM-DD HH:MM:SS] Auto refresh completed successfully (exit 0).

A non-zero exit code means the cookie refresh failed; the likely causes are that
`LECTIO_SCHEDULE_URL` is not set in `.env.local`, or the Playwright browser profile does
not have a valid Lectio session (in that case run `scripts/refresh_cookie.ps1`
interactively first).


## Progress

- [x] M1: Edit trigger block in `scripts/register_scheduled_task.ps1`
- [x] M1: Run `.\scripts\register_scheduled_task.ps1` and confirm "registered successfully"
- [ ] M1: Open Task Scheduler and verify two triggers are present
- [ ] M1: Run `Start-ScheduledTask -TaskName "LectioCookieRefresh"` and verify log shows exit 0
- [ ] M1: Put PC to sleep, wake it, and verify log shows a new refresh entry


## Surprises & Discoveries

(Fill in as work proceeds.)


## Decision Log

- Decision: Use both a logon trigger and an event-based Power-Troubleshooter (EventID 1)
  trigger instead of the logon trigger alone.
  Rationale: A logon trigger fires only on full session creation (boot/login). Wake from
  sleep resumes the existing session without creating a new logon event. Adding the
  event-based trigger for EventID 1 ensures the refresh also runs on every resume.
  Date: 2026-03-10 / GitHub Copilot

- Decision: Use `MSFT_TaskEventTrigger` via the CIM layer for the resume trigger, rather
  than XML-based task registration via `schtasks /Create`.
  Rationale: The existing script uses `New-ScheduledTaskTrigger` and
  `Register-ScheduledTask` PowerShell cmdlets throughout. Staying in the same API surface
  keeps the script consistent. `New-ScheduledTaskTrigger` does not natively expose event
  triggers, but the underlying CIM class `MSFT_TaskEventTrigger` is accessible via
  `Get-CimClass` and can be constructed with `New-CimInstance -ClientOnly`.
  Date: 2026-03-10 / GitHub Copilot


## Outcomes & Retrospective

(Fill in after completion.)
