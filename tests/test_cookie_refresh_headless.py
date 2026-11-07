"""test_cookie_refresh_headless.py

Unit tests verifying that the ``headless`` parameter of ``refresh_cookie()``
is correctly forwarded to Playwright's ``launch_persistent_context``.

Both tests mock the entire Playwright stack so no real browser is launched.
"""
from __future__ import annotations

from itertools import count
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def isolate_saved_cookies():
    with patch("lectio_sync.cookie_refresh._restore_session_cookies"), patch("lectio_sync.cookie_refresh._save_session_cookies"):
        yield

SCHEDULE_HTML = "<html><body>m_content_skemamednavigation_skema_skematabel<script>Lectio.SessionHelper.Initialize(true, 123, 600, 1200);</script></body></html>"
SCHEDULE_URL = "https://www.lectio.dk/lectio/123/SkemaAvanceret.aspx"


def _make_mock_playwright(schedule_html: str):
    """Return ``(mock_sync_playwright_callable, mock_chromium)`` for patching
    ``_require_playwright``.

    The returned ``mock_sp`` mimics the ``sync_playwright`` context-manager
    factory:  ``mock_sp()`` returns a context manager whose ``__enter__``
    yields ``mock_p``, which has ``mock_p.chromium = mock_chromium``.
    ``mock_chromium.launch_persistent_context(...)`` returns ``mock_context``,
    which already has a page that reports the schedule HTML.
    """
    mock_page = MagicMock()
    mock_page.content.return_value = schedule_html

    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    mock_context.cookies.return_value = [
        {"name": "ASP.NET_SessionId", "value": "test", "domain": ".lectio.dk"}
    ]

    mock_chromium = MagicMock()
    mock_chromium.launch_persistent_context.return_value = mock_context

    mock_p = MagicMock()
    mock_p.chromium = mock_chromium

    mock_sp_ctx = MagicMock()
    mock_sp_ctx.__enter__ = MagicMock(return_value=mock_p)
    mock_sp_ctx.__exit__ = MagicMock(return_value=False)

    mock_sp = MagicMock(return_value=mock_sp_ctx)
    return mock_sp, mock_chromium


@patch("lectio_sync.cookie_refresh._update_github_secret", return_value=True)
@patch("pathlib.Path.mkdir")
def test_headless_true_passes_headless_flag(mock_mkdir, mock_gh):
    """``headless=True`` → launch_persistent_context receives headless=True and args=[]."""
    from lectio_sync.cookie_refresh import refresh_cookie

    mock_sp, mock_chromium = _make_mock_playwright(SCHEDULE_HTML)
    with patch("lectio_sync.cookie_refresh._require_playwright", return_value=mock_sp):
        result = refresh_cookie(schedule_url=SCHEDULE_URL, headless=True)

    assert result == 0
    _, kwargs = mock_chromium.launch_persistent_context.call_args
    assert kwargs["headless"] is True
    assert kwargs["args"] == []


@patch("lectio_sync.cookie_refresh._update_github_secret", return_value=True)
@patch("pathlib.Path.mkdir")
def test_headless_false_passes_visible_flag(mock_mkdir, mock_gh):
    """``headless=False`` (default) → launch_persistent_context receives headless=False
    and includes the AutomationControlled suppression flag."""
    from lectio_sync.cookie_refresh import refresh_cookie

    mock_sp, mock_chromium = _make_mock_playwright(SCHEDULE_HTML)
    with patch("lectio_sync.cookie_refresh._require_playwright", return_value=mock_sp):
        result = refresh_cookie(schedule_url=SCHEDULE_URL, headless=False)

    assert result == 0
    _, kwargs = mock_chromium.launch_persistent_context.call_args
    assert kwargs["headless"] is False
    assert "--disable-blink-features=AutomationControlled" in kwargs["args"]


@patch("lectio_sync.cookie_refresh._update_github_secret", return_value=True)
@patch("pathlib.Path.mkdir")
def test_unattended_login_required_never_opens_a_window(mock_mkdir, mock_gh):
    from lectio_sync.cookie_refresh import refresh_cookie

    mock_sp, chromium = _make_mock_playwright("<form>Log ind med MitID</form>")
    with patch("lectio_sync.cookie_refresh._require_playwright", return_value=mock_sp), patch(
        "lectio_sync.cookie_refresh.time.monotonic", side_effect=count(0, 10)
    ):
        result = refresh_cookie(schedule_url=SCHEDULE_URL, interactive=False)
    assert result == 2
    assert chromium.launch_persistent_context.call_count == 1
    assert chromium.launch_persistent_context.call_args.kwargs["headless"] is True
    chromium.launch_persistent_context.return_value.close.assert_called_once()
    mock_gh.assert_not_called()


@patch("lectio_sync.cookie_refresh._update_github_secret", return_value=True)
@patch("pathlib.Path.mkdir")
def test_manual_headless_refresh_can_relaunch_for_login(mock_mkdir, mock_gh):
    from lectio_sync.cookie_refresh import refresh_cookie

    mock_sp, chromium = _make_mock_playwright("<form>Log ind med MitID</form>")
    headless_context = chromium.launch_persistent_context.return_value
    _, visible_chromium = _make_mock_playwright(SCHEDULE_HTML)
    visible_context = visible_chromium.launch_persistent_context.return_value
    chromium.launch_persistent_context.side_effect = [headless_context, visible_context]
    with patch("lectio_sync.cookie_refresh._require_playwright", return_value=mock_sp), patch(
        "lectio_sync.cookie_refresh.time.monotonic", side_effect=count(0, 10)
    ):
        result = refresh_cookie(schedule_url=SCHEDULE_URL, headless=True)
    assert result == 0
    assert chromium.launch_persistent_context.call_args_list[1].kwargs["headless"] is False
    headless_context.close.assert_called_once()
    visible_context.close.assert_called_once()


@patch("pathlib.Path.mkdir")
def test_navigation_failure_always_closes_profile(mock_mkdir):
    from lectio_sync.cookie_refresh import refresh_cookie

    mock_sp, chromium = _make_mock_playwright(SCHEDULE_HTML)
    context = chromium.launch_persistent_context.return_value
    context.pages[0].goto.side_effect = RuntimeError("network unavailable")
    with patch("lectio_sync.cookie_refresh._require_playwright", return_value=mock_sp), pytest.raises(RuntimeError):
        refresh_cookie(schedule_url=SCHEDULE_URL)
    context.close.assert_called_once()


@patch("lectio_sync.cookie_refresh._update_github_secret", return_value=True)
@patch("pathlib.Path.mkdir")
def test_expired_lectio_session_reuses_sso_before_prompting(mock_mkdir, mock_gh):
    from lectio_sync.cookie_refresh import refresh_cookie

    mock_sp, chromium = _make_mock_playwright(SCHEDULE_HTML)
    page = chromium.launch_persistent_context.return_value.pages[0]
    public_schedule = SCHEDULE_HTML.replace("Initialize(true", "Initialize(false")
    page.content.side_effect = [public_schedule, '<a href="logout.aspx">Log ud</a>', SCHEDULE_HTML,
                                '<html>No remembered entry</html>', SCHEDULE_HTML]
    with patch("lectio_sync.cookie_refresh._require_playwright", return_value=mock_sp):
        result = refresh_cookie(schedule_url=SCHEDULE_URL, interactive=False)
    assert result == 0
    assert chromium.launch_persistent_context.call_count == 1
    assert page.goto.call_args_list[0].args[0] == SCHEDULE_URL
    assert "/lectio/123/login.aspx?prevurl=" in page.goto.call_args_list[1].args[0]
    assert page.goto.call_args_list[2].args[0] == SCHEDULE_URL
    mock_gh.assert_called_once()
