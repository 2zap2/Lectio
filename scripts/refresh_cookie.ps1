# refresh_cookie.ps1
#
# Opens a Chromium browser controlled by this script, waits for you to log
# into Lectio (if needed), captures the session cookie, and updates the
# LECTIO_COOKIE_HEADER GitHub Actions Secret automatically.
#
# HOW TO USE
# ----------
# 1. One-time setup (run once in a terminal):
#       py -m pip install playwright
#       py -m playwright install chromium
#       gh auth login          # if not already logged in to GitHub CLI
#
# 2. To refresh the cookie whenever it expires:
#       Double-click the desktop shortcut  (see "Create desktop shortcut" below)
#    OR run directly:
#       .\scripts\refresh_cookie.ps1
#
# CREATE DESKTOP SHORTCUT
# ------------------------
# Right-click your desktop → New → Shortcut
# Target:  powershell.exe -ExecutionPolicy Bypass -File "C:\Users\Arthu\Lectio\scripts\refresh_cookie.ps1"
# Name:    Refresh Lectio Cookie
#
# PARAMETERS (all optional)
# -ScheduleUrl   Your Lectio Advanced Schedule URL. Defaults to LECTIO_SCHEDULE_URL env var
#                or the value saved in .env.local in the repo root.
# -Repo          GitHub repository as "owner/name". Inferred from repo root when omitted.
# -LoginTimeout  Seconds to wait for login (default 300 = 5 min).
# -PrintCookie   Switch: print the cookie to the terminal (off by default).
# -NoGh          Switch: skip gh secret set and print the cookie instead.

param(
    [string]  $ScheduleUrl   = "",
    [string]  $Repo          = "",
    [int]     $LoginTimeout  = 300,
    [switch]  $PrintCookie,
    [switch]  $NoGh,
    [switch]  $Headless
)

$ErrorActionPreference = "Stop"

# ── Locate repo root ─────────────────────────────────────────────────────────
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

# ── Load .env.local if present ───────────────────────────────────────────────
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

# ── Resolve schedule URL ──────────────────────────────────────────────────────
if (-not $ScheduleUrl) {
    $ScheduleUrl = $env:LECTIO_SCHEDULE_URL
}
if (-not $ScheduleUrl) {
    Write-Host ""
    Write-Host "No Lectio schedule URL found."
    Write-Host "It should look like: https://www.lectio.dk/lectio/<school-id>/SkemaAvanceret.aspx?..."
    Write-Host ""
    $ScheduleUrl = Read-Host "Paste your Lectio Advanced Schedule URL"
    $ScheduleUrl = $ScheduleUrl.Trim()

    if (-not $ScheduleUrl) {
        Write-Host "ERROR: A schedule URL is required." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }

    # Offer to save for next time
    $save = Read-Host "Save this URL to .env.local so you don't have to enter it again? (y/n)"
    if ($save -match "^[Yy]") {
        Add-Content -Path $envLocal -Value "`nLECTIO_SCHEDULE_URL=$ScheduleUrl"
        Write-Host "Saved to $envLocal"
    }
}

# ── Build command ─────────────────────────────────────────────────────────────
$python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

$cmdArgs = @(
    "-m", "lectio_sync",
    "--refresh-cookie",
    "--schedule-url", $ScheduleUrl,
    "--cookie-login-timeout", $LoginTimeout
)
if ($Repo)          { $cmdArgs += @("--repo", $Repo) }
if ($PrintCookie)   { $cmdArgs += "--print-cookie" }
if ($NoGh)          { $cmdArgs += "--no-gh" }
if ($Headless)      { $cmdArgs += "--headless" }

# ── Run ───────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Lectio cookie refresh ===" -ForegroundColor Cyan
Write-Host ""

& $python @cmdArgs
$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "Done!  Cookie updated successfully." -ForegroundColor Green
} else {
    Write-Host "Something went wrong (exit code $exitCode). See details above." -ForegroundColor Red
}

Write-Host ""
Stop-Process -Id $PID
