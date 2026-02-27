<#
.SYNOPSIS
Installs or links a centralized skills repo into the current workspace.

.DESCRIPTION
This script clones a remote repo (or copies a local folder) containing a `skills/` tree into a centralized location (default: $env:USERPROFILE\\.skills) and then either copies or symlinks the `skills/` folder into the current workspace under `.agents/skills` so agents and humans can find skills consistently.

USAGE
.
  .\scripts\install_skills.ps1 -RepoUrl 'https://github.com/your-user/skills-repo.git' [ -Symlink ]
  .\scripts\install_skills.ps1 -LocalPath 'C:\path\to\local\skills' -Copy

PARAMETERS
  -RepoUrl  : remote git repo to clone (optional if -LocalPath provided)
  -LocalPath: path to a local skills folder to use instead of cloning
  -Symlink  : attempt to create a symbolic link from workspace `.agents/skills` to the centralized copy
  -Force    : overwrite existing workspace `.agents/skills`

#>

param(
    [string]$RepoUrl = '',
    [string]$LocalPath = '',
    [switch]$Symlink,
    [switch]$Force
)

$central = Join-Path $env:USERPROFILE '.skills'
$workspace = (Get-Location).Path
$workspaceAgents = Join-Path $workspace '.agents'
$workspaceSkills = Join-Path $workspaceAgents 'skills'

if (-not (Test-Path $central)) {
    Write-Host "Creating central skills directory: $central"
    New-Item -ItemType Directory -Path $central -Force | Out-Null
}

if ($LocalPath) {
    Write-Host "Using local skills from: $LocalPath"
    if (-not (Test-Path $LocalPath)) { throw "LocalPath does not exist: $LocalPath" }
    Copy-Item -Path $LocalPath -Destination $central -Recurse -Force
} elseif ($RepoUrl) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is required to clone remote repos. Install git or provide -LocalPath instead."
    }
    if (Test-Path (Join-Path $central '.git')) {
        Write-Host "Updating existing central repo"
        Push-Location $central; git pull --ff-only; Pop-Location
    } else {
        Write-Host "Cloning $RepoUrl -> $central"
        git clone $RepoUrl $central
    }
} else {
    throw "Either -RepoUrl or -LocalPath must be provided."
}

if (Test-Path $workspaceSkills) {
    if ($Force) { Remove-Item -Recurse -Force $workspaceSkills }
    else { Write-Host "Workspace already has .agents/skills — use -Force to replace or remove it manually"; return }
}

# Ensure .agents exists
if (-not (Test-Path $workspaceAgents)) { New-Item -ItemType Directory -Path $workspaceAgents | Out-Null }

if ($Symlink) {
    try {
        New-Item -ItemType SymbolicLink -Path $workspaceSkills -Target (Join-Path $central 'skills') -Force | Out-Null
        Write-Host "Created symbolic link: $workspaceSkills -> $central\\skills"
    } catch {
        Write-Host "Symbolic link failed: $_. Attempting to copy instead."
        Copy-Item -Path (Join-Path $central 'skills') -Destination $workspaceSkills -Recurse -Force
    }
} else {
    Copy-Item -Path (Join-Path $central 'skills') -Destination $workspaceSkills -Recurse -Force
    Write-Host "Copied skills into workspace: $workspaceSkills"
}

Write-Host "Done. Skills are available at: $workspaceSkills"
