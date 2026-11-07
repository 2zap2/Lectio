from email.message import Message
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener
from urllib.response import addinfourl

import pytest

from lectio_sync.cookie_refresh import (
    _filter_cookies_for_host, _is_authenticated_schedule,
    _restore_session_cookies, _save_session_cookies, _update_github_secret,
)
from lectio_sync.lectio_fetch import LectioSession, build_student_url, fetch_html_with_diagnostics
from lectio_sync.cookie_store import load_session_cookies


SCHEDULE_URL = "https://www.lectio.dk/lectio/681/SkemaAvanceret.aspx?studentsel=123"


class FakeHTTPS(HTTPSHandler):
    """Exercise urllib's real redirect/cookie handlers without network access."""

    def __init__(self, responses):
        super().__init__()
        self.responses = iter(responses)
        self.requests = []

    def https_open(self, request):
        self.requests.append(request)
        status, headers, body = next(self.responses)
        message = Message()
        for name, value in headers:
            message.add_header(name, value)
        response = addinfourl(BytesIO(body.encode()), message, request.full_url, status)
        response.msg = "test"
        return response


def transport(session, responses):
    fake = FakeHTTPS(responses)
    session.opener = build_opener(HTTPCookieProcessor(session.jar), fake)
    return fake


def test_renewed_cookie_on_redirect_replaces_import_and_is_used_next_time():
    session = LectioSession(url=SCHEDULE_URL, cookie_header="ASP.NET_SessionId=old")
    fake = transport(session, [
        (302, [("Location", "/lectio/681/renewed"),
               ("Set-Cookie", "ASP.NET_SessionId=fresh; Domain=.lectio.dk; Path=/lectio/; Secure")], ""),
        (200, [("Content-Type", "text/html")], "schedule"),
        (200, [("Content-Type", "text/html")], "next week"),
    ])
    fetch_html_with_diagnostics(url=SCHEDULE_URL, cookie_header="ASP.NET_SessionId=old", session=session)
    fetch_html_with_diagnostics(url=SCHEDULE_URL, cookie_header="ASP.NET_SessionId=old", session=session)
    assert fake.requests[0].get_header("Cookie") == "ASP.NET_SessionId=old"
    assert fake.requests[1].get_header("Cookie") == "ASP.NET_SessionId=fresh"
    assert fake.requests[2].get_header("Cookie") == "ASP.NET_SessionId=fresh"
    assert session.cookie_header(SCHEDULE_URL) == "ASP.NET_SessionId=fresh"


@pytest.mark.parametrize("scope", ["Path=/", "Domain=.lectio.dk; Path=/lectio/"])
def test_deleted_cookie_is_not_reused(scope):
    session = LectioSession(url=SCHEDULE_URL, cookie_header="auth=expired; preference=da")
    fake = transport(session, [
        (200, [("Set-Cookie", f"auth=; Max-Age=0; {scope}")], "expired"),
        (200, [], "next"),
    ])
    for _ in range(2):
        fetch_html_with_diagnostics(url=SCHEDULE_URL, cookie_header="old=snapshot", session=session)
    assert fake.requests[1].get_header("Cookie") == "preference=da"


def test_cookie_does_not_follow_cross_origin_redirect():
    session = LectioSession(url=SCHEDULE_URL, cookie_header="auth=private")
    fake = transport(session, [
        (302, [("Location", "https://broker.unilogin.dk/login")], ""),
        (200, [], "login"),
    ])
    fetch_html_with_diagnostics(url=SCHEDULE_URL, cookie_header="auth=private", session=session)
    assert fake.requests[1].get_header("Cookie") is None
    with pytest.raises(ValueError):
        session.open(Request("https://example.com"), timeout=5)


def test_session_profile_restores_only_missing_session_cookies(tmp_path):
    session_cookie = {"name": "auth", "value": "session", "domain": ".lectio.dk", "path": "/", "expires": -1}
    sso_cookie = {**session_cookie, "name": "sso", "domain": "broker.unilogin.dk"}
    persistent = {**session_cookie, "name": "remember", "expires": 4102444800}
    context = MagicMock()
    context.cookies.return_value = [session_cookie, sso_cookie, persistent]
    _save_session_cookies(context, tmp_path)
    saved = load_session_cookies(tmp_path)
    assert saved == [session_cookie, sso_cookie]
    context.cookies.return_value = [{**session_cookie, "value": "newer-in-profile"}]
    _restore_session_cookies(context, tmp_path)
    context.add_cookies.assert_called_once_with([sso_cookie])


def test_capture_cookie_scope_rejects_similar_domains_and_wrong_paths():
    def cookie(domain, path="/"):
        return {"name": "auth", "value": "secret", "domain": domain, "path": path}
    valid = cookie(".lectio.dk", "/lectio")
    cookies = [valid, cookie("evillectio.dk"), cookie("lectio.dk.evil.com"),
               cookie("other.lectio.dk"), cookie(".lectio.dk", "/lectio/68")]
    assert _filter_cookies_for_host(cookies, SCHEDULE_URL) == [valid]


def test_schedule_authentication_requires_more_than_a_public_table():
    table = '<table id="m_Content_SkemaMedNavigation_skema_skematabel"></table>'
    assert not _is_authenticated_schedule(table)
    assert not _is_authenticated_schedule(table + "SessionHelper.Initialize(false, 681)")
    assert _is_authenticated_schedule(table + "SessionHelper.Initialize(true, 681)")


def test_secret_is_supplied_on_stdin_and_never_printed_on_failure(capsys):
    with patch("lectio_sync.cookie_refresh.subprocess.run", return_value=SimpleNamespace(returncode=1, stderr="sensitive")) as run:
        assert not _update_github_secret("LECTIO_COOKIE_HEADER", "ASP.NET_SessionId=sensitive", "2zap2/Lectio")
    assert "sensitive" not in " ".join(run.call_args.args[0])
    assert run.call_args.kwargs["input"] == "ASP.NET_SessionId=sensitive"
    assert "sensitive" not in capsys.readouterr().err


def test_student_url_cannot_include_the_original_student_or_room_selection():
    url = build_student_url(SCHEDULE_URL + "&lokalesel=456&week=452026", "67380948067")
    assert "studentsel=67380948067" in url
    assert "studentsel=123" not in url
    assert "lokalesel" not in url
    assert "week=452026" in url
    with pytest.raises(ValueError):
        build_student_url(SCHEDULE_URL, "123&studentsel=456")
