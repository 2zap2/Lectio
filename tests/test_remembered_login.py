from datetime import date
from itertools import count
from unittest.mock import patch

import pytest

from lectio_sync import cookie_refresh as refresh
from test_cookie_refresh_headless import _make_mock_playwright, SCHEDULE_HTML, SCHEDULE_URL


def session_table(device='Denne enhed: Chrome - Windows', expiry='21/11-2026 00:00'):
    return f'''<table id="s_m_Content_Content_ForblivLoggetIndGV">
    <tr><th>Seneste login</th><th>Oprettet</th><th>Udløbsdato</th><th>Enhed</th></tr>
    <tr><td>7/11-2026 09:21</td><td>25/10-2026 08:09</td>
    <td>{expiry}</td><td>{device}</td><td><a>close</a></td></tr></table>'''


@pytest.mark.parametrize('device,expiry,expected', [
    ('Denne enhed: Chrome - Windows', '21/11-2026 00:00', date(2026, 11, 21)),
    ('M IPhone 18', '21/11-2026 00:00', None),
    ('Denne enhed: Chrome', '6/11-2026 00:00', None),
    ('Denne enhed: Chrome', '7/11-2026 00:00', None),
    ('Denne enhed: Chrome', 'ukendt', None),
])
def test_only_unexpired_current_device_confirms_remembered_login(device, expiry, expected):
    parser = getattr(refresh, '_remembered_login_expiry', None)
    assert parser is not None, 'Remembered login must be checked against Lectio account Log'
    assert parser(session_table(device, expiry), today=date(2026, 11, 7)) == expected


def test_unrelated_table_or_login_page_cannot_confirm_remembered_login():
    parser = getattr(refresh, '_remembered_login_expiry', None)
    assert parser is not None
    assert parser(session_table().replace('ForblivLoggetIndGV', 'OtherTable'), today=date(2026, 11, 7)) is None
    assert parser('<form>Log ind med MitID</form>', today=date(2026, 11, 7)) is None


def test_setup_does_not_upload_or_claim_success_for_short_session(tmp_path):
    playwright, chromium = _make_mock_playwright(SCHEDULE_HTML)
    with patch.object(refresh, '_require_playwright', return_value=playwright), \
         patch.object(refresh, '_restore_session_cookies'), \
         patch.object(refresh, '_save_session_cookies'), \
         patch.object(refresh, '_update_github_secret') as upload, \
         patch.object(refresh.time, 'monotonic', side_effect=count(0, 10)):
        # The explicit setup contract must exist, independently of old refresh.
        import inspect
        assert 'require_remembered_login' in inspect.signature(refresh.refresh_cookie).parameters
        result = refresh.refresh_cookie(schedule_url=SCHEDULE_URL, profile_dir=tmp_path,
                                        interactive=False, require_remembered_login=True)
    assert result == 3
    upload.assert_not_called()
    chromium.launch_persistent_context.return_value.close.assert_called_once()


def test_setup_waits_until_lectio_confirms_current_device_before_upload(tmp_path):
    playwright, chromium = _make_mock_playwright(SCHEDULE_HTML)
    page = chromium.launch_persistent_context.return_value.pages[0]
    # Schedule, account Log without registration, then after normal login:
    page.content.side_effect = [SCHEDULE_HTML, '<html></html>', SCHEDULE_HTML,
                               session_table(expiry='21/11-2099 00:00'), SCHEDULE_HTML]
    with patch.object(refresh, '_require_playwright', return_value=playwright), \
         patch.object(refresh, '_restore_session_cookies'), \
         patch.object(refresh, '_save_session_cookies'), \
         patch.object(refresh, '_update_github_secret', return_value=True) as upload:
        import inspect
        assert 'require_remembered_login' in inspect.signature(refresh.refresh_cookie).parameters
        result = refresh.refresh_cookie(schedule_url=SCHEDULE_URL, profile_dir=tmp_path,
                                        require_remembered_login=True)
    assert result == 0
    assert any('AdgangIndstillinger.aspx' in c.args[0] for c in page.goto.call_args_list)
    assert any('login.aspx' in c.args[0] for c in page.goto.call_args_list)
    upload.assert_called_once()


def test_security_check_is_not_reported_as_expired_login(tmp_path, capsys):
    playwright, chromium = _make_mock_playwright('<html>Security check</html>')
    page = chromium.launch_persistent_context.return_value.pages[0]
    page.url = 'https://security-check.stil.dk/NDBD/validate'
    with patch.object(refresh, '_require_playwright', return_value=playwright), \
         patch.object(refresh, '_restore_session_cookies'), \
         patch.object(refresh, '_save_session_cookies'), \
         patch.object(refresh, '_update_github_secret') as upload, \
         patch.object(refresh.time, 'monotonic', side_effect=count(0, 10)):
        result = refresh.refresh_cookie(schedule_url=SCHEDULE_URL, profile_dir=tmp_path, interactive=False)
    assert result == 4
    assert 'security check' in capsys.readouterr().err.lower()
    upload.assert_not_called()


def test_cookie_changes_are_saved_even_when_login_cannot_be_completed(tmp_path):
    playwright, _ = _make_mock_playwright('<form>Log ind med MitID</form>')
    with patch.object(refresh, '_require_playwright', return_value=playwright), \
         patch.object(refresh, '_restore_session_cookies'), \
         patch.object(refresh, '_save_session_cookies') as save, \
         patch.object(refresh.time, 'monotonic', side_effect=count(0, 10)), \
         patch.object(refresh.time, 'sleep'):
        assert refresh.refresh_cookie(schedule_url=SCHEDULE_URL, profile_dir=tmp_path, interactive=False) == 2
    save.assert_called_once()


def test_cli_requests_remembered_login_setup():
    from lectio_sync.cli import main
    with patch('sys.argv', ['lectio-sync', '--refresh-cookie', '--schedule-url', SCHEDULE_URL,
                            '--require-remembered-login']), \
         patch.object(refresh, 'refresh_cookie', return_value=0) as run:
        assert main() == 0
    assert run.call_args.kwargs['require_remembered_login'] is True


def test_remembered_login_flag_requires_cookie_mode():
    from lectio_sync.cli import main
    with patch('sys.argv', ['lectio-sync', '--require-remembered-login']), pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


@pytest.mark.parametrize('headless', [False, True])
def test_visible_and_background_use_same_normal_browser_identity(tmp_path, headless):
    (tmp_path / 'Last Version').write_text('145.0.7632.6', encoding='utf-8')
    playwright, chromium = _make_mock_playwright(SCHEDULE_HTML)
    with patch.object(refresh, '_require_playwright', return_value=playwright), \
         patch.object(refresh, '_restore_session_cookies'), \
         patch.object(refresh, '_save_session_cookies'), \
         patch.object(refresh, '_update_github_secret', return_value=True), \
         patch.object(refresh.sys, 'platform', 'win32'):
        assert refresh.refresh_cookie(schedule_url=SCHEDULE_URL, profile_dir=tmp_path,
                                      headless=headless) == 0
    kwargs = chromium.launch_persistent_context.call_args.kwargs
    assert kwargs.get('user_agent') == ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36')


def test_missing_or_invalid_profile_version_does_not_invent_browser_identity(tmp_path):
    helper = getattr(refresh, '_profile_user_agent', None)
    assert helper is not None
    assert helper(tmp_path) is None
    (tmp_path / 'Last Version').write_text('invalid\nInjected', encoding='utf-8')
    assert helper(tmp_path) is None
