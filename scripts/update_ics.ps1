$ErrorActionPreference = 'Stop'

# Usage:
#   .\scripts\update_ics.ps1 -HtmlPath "C:\path\to\lectio.html"
# Optional:
#   -OutPath "docs\calendar.ics" (default)
#   -Timezone "Europe/Copenhagen" (default)
#   -AssignmentsHtmlPath "C:\path\to\opgaver.html"
#   -AssignmentsOutPath "docs\assignments.ics" (default when AssignmentsHtmlPath is given)
#   -FreeClassroomsOut "docs\free_classrooms.ics" (when set, generates the free-rooms ICS)

param(
  [Parameter(Mandatory = $true)]
  [string]$HtmlPath,

  [string]$OutPath = "docs\\calendar.ics",

  [string]$Timezone = "Europe/Copenhagen",

  [string]$AssignmentsHtmlPath = "",

  [string]$AssignmentsOutPath = "docs\\assignments.ics",

  [string]$FreeClassroomsOut = ""
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

# Requires dependencies installed in your current Python environment (venv optional):
#   py -m pip install -e .
$pythonLauncher = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

$extraArgs = @()
if ($AssignmentsHtmlPath -ne "") {
  $extraArgs += "--assignments-html", $AssignmentsHtmlPath, "--assignments-out", $AssignmentsOutPath
}
if ($FreeClassroomsOut -ne "") {
  $extraArgs += "--free-classrooms-out", $FreeClassroomsOut
}

& $pythonLauncher -m lectio_sync --html $HtmlPath --out $OutPath --tz $Timezone @extraArgs
