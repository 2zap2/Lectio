$ErrorActionPreference = 'Stop'

# Generates docs/calendar.ics (and optionally docs/assignments.ics and docs/free_classrooms.ics)
# and commits + pushes them.
# Usage:
#   .\scripts\update_ics_and_push.ps1 -HtmlPath "C:\path\to\lectio.html"
# Optional:
#   -AssignmentsHtmlPath "C:\path\to\opgaver.html"
#   -FreeClassroomsOut "docs\free_classrooms.ics"
#   -Branch "main" (default)

param(
  [Parameter(Mandatory = $true)]
  [string]$HtmlPath,

  [string]$AssignmentsHtmlPath = "",

  [string]$FreeClassroomsOut = "",

  [string]$Branch = "main"
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$splat = @{ HtmlPath = $HtmlPath }
if ($AssignmentsHtmlPath -ne "") { $splat["AssignmentsHtmlPath"] = $AssignmentsHtmlPath }
if ($FreeClassroomsOut -ne "")   { $splat["FreeClassroomsOut"]   = $FreeClassroomsOut }

.\scripts\update_ics.ps1 @splat

git add docs/calendar.ics
if ($AssignmentsHtmlPath -ne "") {
  git add docs/assignments.ics
}
if ($FreeClassroomsOut -ne "") {
  git add $FreeClassroomsOut
}
$changed = git status --porcelain
if (-not $changed) {
  Write-Host "No changes to commit."
  exit 0
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
git commit -m "Update calendars ($stamp)"
git push origin $Branch
