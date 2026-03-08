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

# ── Build the trigger: repeat every 20 hours, starting in 1 minute ───────
# Omit -RepetitionDuration so Windows uses its default (indefinite).
# [TimeSpan]::MaxValue is rejected on some Windows builds (HRESULT 0x80041318).
$startTime = (Get-Date).AddMinutes(1)
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $startTime `
    -RepetitionInterval (New-TimeSpan -Hours 20)

# ── Settings ──────────────────────────────────────────────────────────────
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -WakeToRun:$false

# ── Remove pre-existing task with same name if present ────────────────────
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$taskName'..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# ── Register as current user (no Administrator required) ─────────────────
Register-ScheduledTask `
    -TaskName   $taskName `
    -Action     $action `
    -Trigger    $trigger `
    -Settings   $settings `
    -RunLevel   Limited `
    -Force `
    -Description "Refreshes the Lectio session cookie every 20 hours using Playwright. Keeps the LECTIO_COOKIE_HEADER GitHub Secret current so the daily calendar sync never fails."

Write-Host ""
Write-Host "Task '$taskName' registered successfully." -ForegroundColor Green
Write-Host "First run will occur at $startTime"
Write-Host ""
Write-Host "To verify: open Task Scheduler, find '$taskName', and check 'Last Run Result'."
Write-Host "To view the log after the first run:"
Write-Host "  notepad `"$env:LOCALAPPDATA\lectio-sync\auto-refresh.log`""
