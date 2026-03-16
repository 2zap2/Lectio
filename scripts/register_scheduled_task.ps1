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

# ── Build triggers ────────────────────────────────────────────────────────
# Trigger 1: fires every time THIS user logs on (after boot / reboot).
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

# Trigger 2: fires every time the PC wakes from sleep or hibernate.
# Task Scheduler's New-ScheduledTaskTrigger does not expose event triggers
# directly, so we build one using the CIM (WMI) layer.
# The subscription below is an XPath query against the Windows System event log.
# Power-Troubleshooter EventID 1 is written on every successful resume from sleep.
# A 30-second delay is added so the network adapter has time to reconnect before
# Playwright tries to reach Lectio (without this, the task starts ~5 s after wake
# and fails because the network is still down).
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
    Delay        = 'PT30S'   # wait 30 s after wake for the network to reconnect
}

# Both triggers are passed as an array to Register-ScheduledTask below.
$triggers = @($triggerLogon, $triggerResume)

# ── Settings ──────────────────────────────────────────────────────────────
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
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
    -Trigger    $triggers `
    -Settings   $settings `
    -RunLevel   Limited `
    -Force `
    -Description "Refreshes the Lectio session cookie every 20 hours using Playwright. Keeps the LECTIO_COOKIE_HEADER GitHub Secret current so the daily calendar sync never fails."

Write-Host ""
Write-Host "Task '$taskName' registered successfully." -ForegroundColor Green
Write-Host "Task will run at next logon and on every resume from sleep."
Write-Host ""
Write-Host "To verify: open Task Scheduler, find '$taskName', and check the Triggers tab for two entries."
Write-Host "To view the log after the first run:"
Write-Host "  notepad `"$env:LOCALAPPDATA\lectio-sync\auto-refresh.log`""
