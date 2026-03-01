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

$ErrorActionPreference = 'Continue'

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

# Ensure Python can write unicode characters when output is piped/redirected
$env:PYTHONIOENCODING = 'utf-8'

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
