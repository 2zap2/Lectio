# auto_refresh_cookie.ps1
#
# Automatic cookie refresh for the Windows Scheduled Task.
# Reuses Lectio's remembered login headlessly. When login/setup needs attention,
# opens a visible recovery window at most once per day until access is restored.
# Network failures do not open login windows. Cookie values are never logged.
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
$srcPath = Join-Path $repoRoot "src"
$env:PYTHONPATH = if ($env:PYTHONPATH) {
    "$srcPath$([IO.Path]::PathSeparator)$env:PYTHONPATH"
} else {
    $srcPath
}

# ── Set up log file ───────────────────────────────────────────────────────
$logDir = Join-Path $env:LOCALAPPDATA "lectio-sync"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "auto-refresh.log"
$recoveryNotice = Join-Path $logDir "login-recovery-notified.txt"

# Preserve the former mixed UTF-8/UTF-16 log before switching to UTF-8 history.
if (Test-Path -LiteralPath $logFile) {
    $previousBytes = [IO.File]::ReadAllBytes($logFile)
    if (($previousBytes -contains 0) -or $previousBytes.Length -gt 2MB) {
        Move-Item -LiteralPath $logFile -Destination ($logFile + "." + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".bak")
    }
}
function Write-RefreshLog([string] $Text) {
    [IO.File]::AppendAllText($logFile, $Text + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Write-Output $Text
}

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
    "Add it to .env.local or set the environment variable." | ForEach-Object { Write-RefreshLog $_ }
    exit 1
}

$python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

# Ensure Python can write unicode characters when output is piped/redirected
$env:PYTHONIOENCODING = 'utf-8'

$cmdArgs = @(
    "-m", "lectio_sync",
    "--refresh-cookie",
    "--headless",
    "--unattended",
    "--require-remembered-login",
    "--schedule-url", $scheduleUrl
)

# ── Run and capture output ────────────────────────────────────────────────
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-RefreshLog "[$timestamp] Starting auto cookie refresh..."

try {
    & $python @cmdArgs 2>&1 | ForEach-Object { Write-RefreshLog $_.ToString() }
    $exitCode = $LASTEXITCODE
} catch {
    Write-RefreshLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] EXCEPTION during cookie refresh."
    $exitCode = 1
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
if ($exitCode -eq 0) {
    Write-RefreshLog "[$timestamp] Auto refresh completed successfully (exit 0)."
    if (Test-Path -LiteralPath $recoveryNotice) { Remove-Item -LiteralPath $recoveryNotice }
} else {
    Write-RefreshLog "[$timestamp] Auto refresh FAILED (exit $exitCode). Check log above."
    if ($exitCode -in @(2, 3, 4)) {
        $showRecovery = $true
        if (Test-Path -LiteralPath $recoveryNotice) {
            $lastNotice = (Get-Item -LiteralPath $recoveryNotice).LastWriteTimeUtc
            $showRecovery = ([DateTime]::UtcNow - $lastNotice).TotalHours -ge 24
        }
        if ($showRecovery) {
            $refreshScript = Join-Path $PSScriptRoot 'refresh_cookie.ps1'
            Write-RefreshLog "[$timestamp] Opening visible login recovery. Choose Forbliv logget ind."
            try {
                Start-Process -FilePath 'powershell.exe' -WindowStyle Normal -ArgumentList @(
                    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $refreshScript + '"'),
                    '-LoginTimeout', '600'
                ) -ErrorAction Stop
                [IO.File]::WriteAllText($recoveryNotice, [DateTime]::UtcNow.ToString('o'))
            } catch {
                Write-RefreshLog "[$timestamp] Could not open login recovery; retry on the next scheduled run."
            }
        } else {
            Write-RefreshLog "[$timestamp] Login recovery already offered; suppressing repeated windows for 24 hours."
        }
    }
}

exit $exitCode
