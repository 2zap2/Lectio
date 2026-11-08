param([switch]$ReplaceCookieTask, [string]$PythonExecutable = '')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$launcher = Join-Path $PSScriptRoot 'run_sync_silently.pyw'
function Invoke-PythonProbe([string]$Executable, [string]$Code, [string]$Prefix = '') {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = $Prefix + ' -c "' + $Code + '"'
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($info)
    $output = $process.StandardOutput.ReadToEnd()
    $null = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    $result = @{ExitCode=$process.ExitCode; Output=$output.Trim()}
    $process.Dispose()
    return $result
}
$candidates = @()
if ($PythonExecutable) { $candidates += $PythonExecutable }
$candidates += Join-Path $repoRoot '.venv\Scripts\python.exe'
$py = Get-Command py.exe -ErrorAction SilentlyContinue
if ($py) {
    try {
        $resolvedPython = Invoke-PythonProbe $py.Source 'import sys; print(sys.executable)' '-3'
        if ($resolvedPython.ExitCode -eq 0) { $candidates += $resolvedPython.Output }
    } catch { }
}
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand) { $candidates += $pythonCommand.Source }
$pythonw = $null
foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    # A leftover venv can exist without Playwright; never select it blindly.
    try {
        $check = Invoke-PythonProbe $candidate "import playwright.sync_api, bs4, lxml, dateutil; from zoneinfo import ZoneInfo; ZoneInfo('Europe/Copenhagen')"
        if ($check.ExitCode -ne 0) { continue }
    } catch { continue }
    $quiet = Join-Path (Split-Path $candidate) 'pythonw.exe'
    if (Test-Path -LiteralPath $quiet) { $pythonw = $quiet; break }
}
if (-not $pythonw) { throw 'No Python with the Lectio browser dependencies and pythonw was found.' }
$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('"' + $launcher + '"') -WorkingDirectory $repoRoot
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$daily = New-ScheduledTaskTrigger -Daily -At '08:05'
$subscription = '<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[Provider[@Name=''Microsoft-Windows-Power-Troubleshooter''] and EventID=1]]</Select></Query></QueryList>'
$resume = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler |
    New-CimInstance -ClientOnly -Property @{Enabled=$true; Subscription=$subscription; Delay='PT30S'}
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable -RunOnlyIfNetworkAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -WakeToRun:$false `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
# Register and verify the replacement before disabling the previous task.
Register-ScheduledTask -TaskName 'LectioLocalSync' -Action $action -Trigger @($logon,$daily,$resume) `
    -Settings $settings -Principal $principal -Force `
    -Description 'Builds and publishes Lectio calendars locally at 08:05, logon and resume. Uses the saved browser login.' | Out-Null
$task = Get-ScheduledTask -TaskName 'LectioLocalSync'
if ($task.Actions.Execute -ne $pythonw -or $task.Triggers.Count -ne 3) {
    throw 'The replacement task could not be verified. The cookie task has not been disabled.'
}
if ($ReplaceCookieTask) {
    $old = Get-ScheduledTask -TaskName 'LectioCookieRefresh' -ErrorAction SilentlyContinue
    if ($old) { Disable-ScheduledTask -TaskName 'LectioCookieRefresh' | Out-Null }
}
Write-Output 'LectioLocalSync is registered: daily 08:05, logon and resume; no console window.'
