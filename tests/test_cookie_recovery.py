"""Exercise the real scheduler wrapper with fake Python and window launchers.

These tests do not open browsers, contact Lectio, or access real user profiles.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows scheduler wrapper')
SOURCE = Path(__file__).resolve().parents[1]


def run_scheduler(tmp_path, code):
    repo = tmp_path / 'repo'
    (repo / 'scripts').mkdir(parents=True, exist_ok=True)
    for name in ('auto_refresh_cookie.ps1', 'refresh_cookie.ps1'):
        shutil.copyfile(SOURCE / 'scripts' / name, repo / 'scripts' / name)
    wrapper = tmp_path / 'run.ps1'
    # Paths are fixture-owned; quote apostrophes for PowerShell literals.
    quoted = str(tmp_path).replace("'", "''")
    wrapper.write_text(f'''$env:LOCALAPPDATA = '{quoted}'
$env:LECTIO_SCHEDULE_URL = 'https://www.lectio.dk/lectio/123/SkemaAvanceret.aspx'
function global:py {{
    [IO.File]::WriteAllText('{quoted}\\arguments.txt', ($args -join ' '))
    Write-Output 'Fake refresh: no credentials'
    $global:LASTEXITCODE = {code}
}}
function global:Start-Process {{
    param($FilePath, $ArgumentList, $WindowStyle)
    Add-Content -LiteralPath '{quoted}\\windows.txt' -Value $WindowStyle
}}
& '{quoted}\\repo\\scripts\\auto_refresh_cookie.ps1'
exit $LASTEXITCODE
''', encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                             '-File', str(wrapper)], capture_output=True, timeout=30)
    return result


def test_expired_access_opens_one_visible_window_and_keeps_log_history(tmp_path):
    assert run_scheduler(tmp_path, 3).returncode == 3
    assert (tmp_path / 'windows.txt').read_text().strip() == 'Normal'
    assert run_scheduler(tmp_path, 3).returncode == 3
    assert (tmp_path / 'windows.txt').read_text().splitlines() == ['Normal']
    log = (tmp_path / 'lectio-sync' / 'auto-refresh.log').read_text(encoding='utf-8-sig')
    assert log.count('Starting auto cookie refresh') == 2
    assert '\x00' not in log
    assert '--require-remembered-login' in (tmp_path / 'arguments.txt').read_text()


def test_success_rearms_recovery_for_next_expiry(tmp_path):
    assert run_scheduler(tmp_path, 2).returncode == 2
    assert run_scheduler(tmp_path, 0).returncode == 0
    assert run_scheduler(tmp_path, 2).returncode == 2
    assert (tmp_path / 'windows.txt').read_text().splitlines() == ['Normal', 'Normal']


def test_network_error_does_not_open_login_window(tmp_path):
    assert run_scheduler(tmp_path, 1).returncode == 1
    assert not (tmp_path / 'windows.txt').exists()
