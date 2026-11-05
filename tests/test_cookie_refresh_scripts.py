from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "script_name",
    ["auto_refresh_cookie.ps1", "refresh_cookie.ps1"],
)
def test_cookie_refresh_script_runs_repository_package(script_name: str):
    script = (REPO_ROOT / "scripts" / script_name).read_text(encoding="utf-8")

    assert "$env:PYTHONPATH" in script
    assert 'Join-Path $repoRoot "src"' in script
