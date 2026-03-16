$ErrorActionPreference = 'Stop'

# Usage:
#   .\scripts\update_ics.ps1 -HtmlPath "C:\path\to\lectio.html"
# Optional:
#   -OutPath "docs\calendar.ics" (default)
#   -Timezone "Europe/Copenhagen" (default)

param(
  [Parameter(Mandatory = $true)]
  [string]$HtmlPath,

  [string]$OutPath = "docs\\calendar.ics",

  [string]$Timezone = "Europe/Copenhagen"
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

# Requires dependencies installed in your current Python environment (venv optional):
#   py -m pip install -e .
$pythonLauncher = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
& $pythonLauncher -m lectio_sync --html $HtmlPath --out $OutPath --tz $Timezone
