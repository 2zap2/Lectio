# Local calendar sync

Lectio is fetched by the PC through its existing remembered browser login. GitHub
receives only the four finished ICS feeds; their existing Pages URLs stay the same.
The PC does not need to be kept awake. Until it is available, the latest published
calendars remain accessible.

The task `LectioLocalSync` runs at 08:05 local Windows time, logon and resume.
Missed daily runs are caught up when the PC becomes available. A successful update
after 08:05 is reused for the rest of that day. Resume before 08:05 does not suppress
the daily refresh. Failed runs retry after 10 and 30 seconds, then Task Scheduler
retries up to three times at five-minute intervals. No half-hour cookie upload is
needed. The previous task is disabled only during the verified migration.

Every requested week, both students, assignments and classroom data must pass
validation before anything is uploaded. Real empty tables are accepted. Missing
tables, login/error pages, unexpected selections and missing weeks abort the entire
generation. A publication failure leaves a local `pending` generation; the next run
publishes it without opening a browser. GitHub receives one calendar-only commit
based on the latest branch head, without force-pushing or changing other files.
Unchanged content (including changes only to DTSTAMP) creates no new commit.

Ordinary runs use an invisible browser. If Lectio requires login or STIL verification,
the actual browser opens at most once per 24 hours, without a console window. Network
and unknown server errors do not trigger login windows. The browser profile and
encrypted session-cookie backup remain outside the repository.

## Setup and diagnosis

Use the existing `.env.local` with `LECTIO_SCHEDULE_URL`. `LECTIO_ASSIGNMENTS_URL`
can override the default school assignments page. Non-secret feed settings are in
`sync-config.json`. Install the existing optional `cookie-refresh` dependencies and
reuse the existing browser profile; there is no new daily setup.

```powershell
# Verify fetching without publishing or changing the active task:
python -m lectio_sync.local_sync --force --build-only --no-recovery
# Full manual update:
python -m lectio_sync.local_sync --force
# After a complete fetch/publication/Pages-link check, install the replacement:
.\scripts\register_local_sync_task.ps1 -ReplaceCookieTask
```

The installer selects a Python with the required dependencies and its matching
pythonw. It checks the repository venv first, then the installed Python.
GitHub CLI must have the existing user authentication and repository Contents write
access. Logs are rotated at `%LOCALAPPDATA%\lectio-sync\local-sync\sync.log`.
Task exit 0 means success/already updated/already running; 2 means login is required;
1 means an ordinary error. Complete queued calendars are in `local-sync\pending`.

GitHub's workflow validates the committed calendars and runs tests. It no longer
contacts Lectio or needs Lectio cookie secrets. The existing Pages deployment from
`main:/docs` continues to serve the calendars.

## Remaining real-world acceptance check

After a night in sleep/hibernate, resume after 08:05 and confirm that `LectioLocalSync`
finishes with exit 0, the log contains a new successful fetch and publication, the
same public calendar URLs serve the files, and no manual login or console appeared.
This check requires an actual overnight sleep/resume and cannot be inferred from a
manual daytime run. Lectio may still occasionally require a new login.
