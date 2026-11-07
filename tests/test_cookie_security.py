import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lectio_sync import cookie_refresh as refresh


def test_github_export_removes_remembered_sso_and_unknown_credentials():
    header = ('ASP.NET_SessionId=short; autologinkeyV2=long-lived; '
              'LectioTicket=legacy-long-lived; KEYCLOAK_IDENTITY=sso; unknown=secret; '
              'isloggedin3=Y; BaseSchoolUrl=681; LastAuthenticatedPageLoad2=123')
    with patch.object(refresh.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
        assert refresh._update_github_secret('LECTIO_COOKIE_HEADER', header, '2zap2/Lectio')
    exported = run.call_args.kwargs['input']
    assert exported == ('ASP.NET_SessionId=short; isloggedin3=Y; '
                        'BaseSchoolUrl=681; LastAuthenticatedPageLoad2=123')
    assert 'long-lived' not in exported and 'sso' not in exported and 'secret' not in exported


@pytest.mark.parametrize('header', [
    'autologinkeyV2=long-lived',
    'ASP.NET_SessionId=ok\nInjected: secret',
    'ASP.NET_SessionId=one; ASP.NET_SessionId=two',
])
def test_invalid_or_non_session_secret_is_rejected_without_transmission(header, capsys):
    with patch.object(refresh.subprocess, 'run') as run:
        assert not refresh._update_github_secret('LECTIO_COOKIE_HEADER', header, '2zap2/Lectio')
    run.assert_not_called()
    assert header not in capsys.readouterr().err


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI protection')
def test_session_file_is_encrypted_and_round_trips_without_extra_login(tmp_path):
    cookie = dict(name='ASP.NET_SessionId', value='test-private-session-9876',
                  domain='www.lectio.dk', path='/', expires=-1)
    sso = dict(cookie, name='KEYCLOAK_IDENTITY', value='test-sso-6543', domain='broker.unilogin.dk')
    context = MagicMock()
    context.cookies.return_value = [cookie, sso, dict(cookie, name='autologinkeyV2', expires=4102444800)]
    refresh._save_session_cookies(context, tmp_path)
    encrypted = tmp_path / 'session-cookies.dpapi'
    assert encrypted.exists(), 'Windows sessions must be protected with user-bound DPAPI'
    assert b'test-private-session-9876' not in encrypted.read_bytes()
    assert b'test-sso-6543' not in encrypted.read_bytes()
    assert not (tmp_path / 'session-cookies.json').exists()
    context.cookies.return_value = [dict(cookie, value='newer-cookie')]
    refresh._restore_session_cookies(context, tmp_path)
    context.add_cookies.assert_called_once_with([sso])


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI migration')
def test_legacy_cookie_file_is_migrated_and_plaintext_removed(tmp_path):
    cookie = dict(name='ASP.NET_SessionId', value='legacy-private-cookie',
                  domain='www.lectio.dk', path='/', expires=-1)
    legacy = tmp_path / 'session-cookies.json'
    legacy.write_text(json.dumps([cookie]), encoding='utf-8')
    (tmp_path / 'session-cookies.tmp').write_text(json.dumps([cookie]), encoding='utf-8')
    context = MagicMock()
    context.cookies.return_value = []
    refresh._restore_session_cookies(context, tmp_path)
    context.add_cookies.assert_called_once_with([cookie])
    assert not legacy.exists()
    assert not (tmp_path / 'session-cookies.tmp').exists()
    assert (tmp_path / 'session-cookies.dpapi').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI integrity')
def test_tampered_encrypted_file_never_falls_back_to_old_plaintext(tmp_path, capsys):
    context = MagicMock()
    cookie = dict(name='ASP.NET_SessionId', value='test-secret', domain='www.lectio.dk', path='/', expires=-1)
    context.cookies.return_value = [cookie]
    refresh._save_session_cookies(context, tmp_path)
    target = tmp_path / 'session-cookies.dpapi'
    assert target.exists(), 'Encrypted persistence is required'
    target.write_bytes(b'corrupted encrypted data')
    (tmp_path / 'session-cookies.json').write_text(json.dumps([cookie]), encoding='utf-8')
    refresh._restore_session_cookies(context, tmp_path)
    context.add_cookies.assert_not_called()
    assert 'test-secret' not in capsys.readouterr().err


def test_capture_does_not_print_or_export_long_lived_key(tmp_path, capsys):
    from test_cookie_refresh_headless import _make_mock_playwright, SCHEDULE_HTML, SCHEDULE_URL
    playwright, chromium = _make_mock_playwright(SCHEDULE_HTML)
    context = chromium.launch_persistent_context.return_value
    context.cookies.return_value.append(dict(name='autologinkeyV2', value='never-print-me',
                                             domain='.lectio.dk', path='/', expires=4102444800))
    with patch.object(refresh, '_require_playwright', return_value=playwright), \
         patch.object(refresh, '_restore_session_cookies'), \
         patch.object(refresh, '_save_session_cookies'):
        assert refresh.refresh_cookie(schedule_url=SCHEDULE_URL, profile_dir=tmp_path, no_gh=True) == 0
    out = capsys.readouterr().out
    assert 'ASP.NET_SessionId=test' in out
    assert 'never-print-me' not in out


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI fail-closed behavior')
def test_protection_failure_keeps_existing_legacy_cookie_intact(tmp_path):
    import importlib.util
    assert importlib.util.find_spec('lectio_sync.cookie_store') is not None, 'Protected persistence module is required'
    from lectio_sync import cookie_store
    legacy = tmp_path / 'session-cookies.json'
    payload = '[{"name":"test","value":"private"}]'
    legacy.write_text(payload, encoding='utf-8')
    with patch.object(cookie_store, '_dpapi', side_effect=OSError('protection unavailable')):
        with pytest.raises(OSError):
            cookie_store.load_session_cookies(tmp_path)
    assert legacy.read_text(encoding='utf-8') == payload
    assert not (tmp_path / 'session-cookies.dpapi').exists()
