from datetime import datetime
from email.message import Message
from io import BytesIO
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPCookieProcessor, HTTPSHandler, build_opener
from urllib.response import addinfourl

from dateutil import tz
import pytest

from lectio_sync.cli import main
from lectio_sync.lectio_fetch import LectioSession


def test_cli_builds_separate_student_feeds_and_persists_renewal(tmp_path, monkeypatch):
    requests = []
    today = datetime.now(tz.gettz("Europe/Copenhagen")).date()

    class ScheduleTransport(HTTPSHandler):
        def https_open(self, request):
            student_id = parse_qs(urlparse(request.full_url).query)["studentsel"][0]
            requests.append((student_id, request.get_header("Cookie")))
            headers = Message()
            headers.add_header("Set-Cookie", "auth=renewed; Domain=.lectio.dk; Path=/; Secure")
            title = "Original matematik" if student_id == "123" else "Ekstra fysik"
            tooltip = f"{title}\n{today:%d/%m-%Y} 08:15 til 09:15\nLokale: 1.59"
            html = (f'<table id="m_Content_SkemaMedNavigation_skema_skematabel"><tr><td data-date="{today}">'
                    f'<a class="s2skemabrik" data-brikid="{student_id}" data-tooltip="{tooltip}">{title}</a>'
                    '</td></tr></table>')
            response = addinfourl(BytesIO(html.encode()), headers, request.full_url, 200)
            response.msg = "OK"
            return response

    original_init = LectioSession.__init__

    def initialize(session, **kwargs):
        original_init(session, **kwargs)
        session.opener = build_opener(HTTPCookieProcessor(session.jar), ScheduleTransport())

    saved = []
    monkeypatch.setattr(LectioSession, "__init__", initialize)
    monkeypatch.setattr("lectio_sync.cookie_refresh._update_github_secret", lambda *args: saved.append(args) or True)
    monkeypatch.setenv("LECTIO_COOKIE_HEADER", "auth=original")
    monkeypatch.setattr("sys.argv", ["lectio-sync", "--fetch", "--schedule-url",
        "https://www.lectio.dk/lectio/681/SkemaAvanceret.aspx?studentsel=123",
        "--out", str(tmp_path / "calendar.ics"), "--additional-student-id", "67380948067",
        "--days-past", "0", "--days-future", "0", "--save-cookie-secret", "LECTIO_COOKIE_HEADER"])

    assert main() == 0
    primary = (tmp_path / "calendar.ics").read_text(encoding="utf-8")
    secondary = (tmp_path / "calendar-67380948067.ics").read_text(encoding="utf-8")
    assert "Original matematik" in primary and "Ekstra fysik" not in primary
    assert "Ekstra fysik" in secondary and "Original matematik" not in secondary
    assert "X-WR-CALNAME:Lectio - elev 67380948067" in secondary
    assert requests == [("123", "auth=original"), ("67380948067", "auth=renewed")]
    assert saved == [("LECTIO_COOKIE_HEADER", "auth=renewed", None)]


def test_renewal_is_saved_even_when_building_calendar_fails(tmp_path, monkeypatch):
    from lectio_sync import cli

    session = LectioSession(url="https://www.lectio.dk/lectio/681/SkemaAvanceret.aspx", cookie_header="auth=old")
    monkeypatch.setattr(cli, "LectioSession", lambda **kwargs: session)

    def fail(*args):
        seed = next(iter(session.jar))
        seed.value = "new"
        raise RuntimeError("bad schedule response")

    monkeypatch.setattr(cli, "_build_fetched_calendars", fail)
    saved = []
    monkeypatch.setattr("lectio_sync.cookie_refresh._update_github_secret", lambda *args: saved.append(args) or True)
    monkeypatch.setenv("LECTIO_COOKIE_HEADER", "auth=old")
    monkeypatch.setattr("sys.argv", ["lectio-sync", "--fetch", "--schedule-url",
        "https://www.lectio.dk/lectio/681/SkemaAvanceret.aspx", "--save-cookie-secret", "LECTIO_COOKIE_HEADER"])
    with pytest.raises(RuntimeError, match="bad schedule response"):
        main()
    assert saved == [("LECTIO_COOKIE_HEADER", "auth=new", None)]
