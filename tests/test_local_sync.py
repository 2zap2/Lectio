import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from lectio_sync import browser_fetch, local_sync
from lectio_sync.browser_session import InvalidLectioPage, LoginRequired
from lectio_sync.lectio_fetch import LectioWeek
from lectio_sync.publish import (CALENDAR_FILES, GitHubError, load_calendars,
                                 publish_calendars, validate_calendar)


EMPTY = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
URL = "https://www.lectio.dk/lectio/681/SkemaAvanceret.aspx?studentsel=123&week=452026"
NOW = datetime(2026, 11, 8, 10, tzinfo=timezone.utc)
CONFIG = dict(repository="test/repo", branch="main", additional_student_ids=["67380948067"],
              rooms_url=URL.replace("studentsel=123", "lokalesel=456"), days_past=7, days_future=90)


def good_builder(directory, **kwargs):
    for name in CALENDAR_FILES:
        (directory / name).write_bytes(EMPTY)


def sync(tmp_path, **kwargs):
    return local_sync.run_sync(config=CONFIG, state_dir=tmp_path, schedule_url=URL,
                               now=NOW, retry_delays=(), **kwargs)


def test_missing_week_never_publishes_partial_generation(tmp_path):
    calls = []
    def incomplete(directory, **kwargs):
        (directory / "calendar.ics").write_bytes(EMPTY)
        raise InvalidLectioPage("Missing second student week")
    with pytest.raises(InvalidLectioPage):
        sync(tmp_path, builder=incomplete, publisher=lambda *a, **k: calls.append(a))
    assert not calls
    assert not (tmp_path / "pending").exists()
    assert not list(tmp_path.glob("generation-*"))


def test_publish_retry_uses_durable_generation_without_browser(tmp_path):
    def unavailable(*args, **kwargs):
        raise GitHubError(503)
    with pytest.raises(GitHubError):
        sync(tmp_path, builder=good_builder, publisher=unavailable)
    assert len(load_calendars(tmp_path / "pending")) == 4
    def no_browser(*args, **kwargs):
        pytest.fail("A queued publication must not open another browser")
    assert sync(tmp_path, builder=no_browser, publisher=lambda *a, **k: "commit") == 0
    assert not (tmp_path / "pending").exists()
    assert json.loads((tmp_path / "sync-state.json").read_text())["commit"] == "commit"


def test_empty_feeds_are_valid_and_publish_together(tmp_path):
    received = []
    def publish(directory, **kwargs):
        received.append(load_calendars(directory))
        return "commit"
    assert sync(tmp_path, builder=good_builder, publisher=publish) == 0
    assert len(received) == 1 and len(received[0]) == 4


def test_double_start_is_rejected_before_browser(tmp_path):
    with local_sync.sync_lock(tmp_path / "sync.lock"):
        with pytest.raises(local_sync.AlreadyRunning):
            sync(tmp_path, builder=lambda *a, **k: pytest.fail("Duplicate browser"))


def test_login_recovery_is_offered_once_in_24_hours(tmp_path):
    visible = []
    def expired(directory, **kwargs):
        visible.append(kwargs["interactive"])
        raise LoginRequired()
    with pytest.raises(LoginRequired):
        sync(tmp_path, builder=expired)
    assert sync(tmp_path, builder=expired) == 2
    assert visible == [False, True, False]


def test_network_failure_does_not_open_login(tmp_path):
    visible = []
    def offline(directory, **kwargs):
        visible.append(kwargs["interactive"])
        raise OSError("offline")
    with pytest.raises(OSError):
        sync(tmp_path, builder=offline)
    assert visible == [False]


def test_retry_delays_and_success():
    calls, waits = [], []
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise OSError()
        return "ok"
    assert local_sync.retry(flaky, sleep=waits.append) == "ok"
    assert waits == [10, 30]


def test_build_only_does_not_publish_or_change_success_state(tmp_path):
    assert sync(tmp_path, builder=good_builder, build_only=True,
                publisher=lambda *a, **k: pytest.fail("Dry run publication")) == 0
    assert not (tmp_path / "sync-state.json").exists()
    assert not (tmp_path / "pending").exists()
    assert len(list(tmp_path.glob("generation-*"))) == 1


@pytest.mark.parametrize("stamp,expected", [
    ("2026-11-08T06:00:00+00:00", False),  # Before 08:05 CET
    ("2026-11-08T07:06:00+00:00", True),
    ("2026-11-07T20:00:00+00:00", False),
    (None, False),
])
def test_daily_catchup_uses_copenhagen_time(stamp, expected):
    assert local_sync.same_school_day(stamp, NOW) is expected


def schedule_html():
    return '<script>SessionHelper.Initialize(true)</script><table id="m_Content_SkemaMedNavigation_skema_skematabel"></table>'


def test_empty_authenticated_schedule_is_accepted():
    browser_fetch.validate_page(schedule_html(), URL, URL)


@pytest.mark.parametrize("html,final,error", [
    ("<html>Error</html>", URL, InvalidLectioPage),
    ("<html>Log ind MitID</html>", URL, LoginRequired),
    (schedule_html(), URL.replace("452026", "462026"), InvalidLectioPage),
    (schedule_html(), URL.replace("123", "999"), InvalidLectioPage),
    (schedule_html(), "https://security-check.stil.dk/", LoginRequired),
])
def test_rejects_invalid_or_wrong_week_pages(html, final, error):
    with pytest.raises(error):
        browser_fetch.validate_page(html, URL, final)


def test_browser_build_requires_all_weeks_and_both_students(tmp_path, monkeypatch):
    visited = []
    class Response:
        status = 200
    class Page:
        def goto(self, url, **kwargs):
            self.url = url
            visited.append(url)
            return Response()
        def content(self):
            if "OpgaverElev" in self.url:
                return '<script>SessionHelper.Initialize(true)</script><table id="s_m_Content_Content_ExerciseGV"></table>'
            return schedule_html()
    class Context:
        pages = [Page()]
    @contextmanager
    def context(*args, **kwargs):
        yield Context()
    monkeypatch.setattr(browser_fetch, "browser_context", context)
    monkeypatch.setattr(browser_fetch, "ensure_authenticated", lambda *a, **k: None)
    monkeypatch.setattr(browser_fetch, "iter_weeks_for_window", lambda **k: [LectioWeek(45, 2026), LectioWeek(46, 2026)])
    browser_fetch.build_calendars(tmp_path, schedule_url=URL, rooms_url=CONFIG["rooms_url"],
                                  additional_student_ids=CONFIG["additional_student_ids"])
    assert len(load_calendars(tmp_path)) == 4
    assert len(visited) == 7  # 2 students * 2 weeks + assignments + 2 room weeks
    assert sum("studentsel=67380948067" in url for url in visited) == 2


class FakeAPI:
    def __init__(self, *, unchanged=False, conflict=False):
        self.calls, self.blobs = [], {}
        self.head = "old-head"
        self.unchanged = unchanged
        self.conflict = conflict

    def call(self, endpoint, data=None, method=None):
        self.calls.append((endpoint, data, method))
        if endpoint.startswith("ref/"):
            return {"object": {"sha": self.head}}
        if endpoint.startswith("commits/"):
            return {"tree": {"sha": self.head + "-tree"}}
        if endpoint.startswith("trees/"):
            return {"tree": [{"path": "README.md", "sha": "preserved", "type": "blob", "mode": "100644"}] +
                    ([{"path": "docs/" + name, "sha": "empty", "type": "blob", "mode": "100644"}
                      for name in CALENDAR_FILES] if self.unchanged else [])}
        if endpoint.startswith("blobs/"):
            return {"content": base64.b64encode(EMPTY).decode()}
        if endpoint == "blobs":
            return {"sha": "blob"}
        if endpoint == "trees":
            assert data["base_tree"] == self.head + "-tree"
            assert {e["path"] for e in data["tree"]} == {"docs/" + n for n in CALENDAR_FILES}
            return {"sha": "tree"}
        if endpoint == "commits":
            assert data["parents"] == [self.head]
            return {"sha": "commit"}
        if endpoint.startswith("refs/"):
            assert data["force"] is False
            if self.conflict:
                self.conflict = False
                self.head = "concurrent-head"
                raise GitHubError(422)
            return {}
        raise AssertionError(endpoint)


def test_atomic_publish_rebases_on_concurrent_update(tmp_path):
    good_builder(tmp_path)
    api = FakeAPI(conflict=True)
    assert publish_calendars(tmp_path, api=api) == "commit"
    assert len([c for c in api.calls if c[0] == "commits"]) == 2
    assert len([c for c in api.calls if c[0] == "blobs"]) == 4


def test_unchanged_calendar_does_not_create_commit(tmp_path):
    good_builder(tmp_path)
    api = FakeAPI(unchanged=True)
    assert publish_calendars(tmp_path, api=api) == "old-head"
    assert all(data is None for _, data, _ in api.calls)


def test_missing_feed_aborts_before_any_api_call(tmp_path):
    (tmp_path / "calendar.ics").write_bytes(EMPTY)
    api = FakeAPI()
    with pytest.raises(FileNotFoundError):
        publish_calendars(tmp_path, api=api)
    assert not api.calls


def test_duplicate_uid_rejected():
    event = b"BEGIN:VEVENT\r\nUID:duplicate\r\nDTSTART:20261108T120000\r\nEND:VEVENT\r\n"
    data = EMPTY.replace(b"END:VCALENDAR", event + event + b"END:VCALENDAR")
    with pytest.raises(ValueError):
        validate_calendar(data)


def test_timestamp_only_is_not_a_content_change(tmp_path):
    from lectio_sync.publish import canonical_calendar
    assert canonical_calendar(EMPTY.replace(b"END:VCALENDAR", b"DTSTAMP:20261108T000000Z\r\nEND:VCALENDAR")) == canonical_calendar(EMPTY)


def test_cli_routes_local_sync_options(monkeypatch):
    from lectio_sync import cli
    monkeypatch.setattr(sys, "argv", ["lectio-ics", "--local-sync", "--force", "--no-recovery"])
    received = []
    monkeypatch.setattr(local_sync, "main", lambda args: received.append(args) or 0)
    assert cli.main() == 0
    assert received == [["--force", "--no-recovery"]]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows hidden launcher")
def test_quiet_launcher_and_child_have_no_visible_console(tmp_path):
    import shutil
    scripts = tmp_path / "scripts"
    package = tmp_path / "src" / "lectio_sync"
    scripts.mkdir()
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    launcher = Path(__file__).resolve().parents[1] / "scripts" / "run_sync_silently.pyw"
    shutil.copyfile(launcher, scripts / launcher.name)
    marker = tmp_path / "window-state.json"
    probe = tmp_path / "probe.py"
    probe.write_text('import ctypes, json, os\nfrom pathlib import Path\n'
                     'w=ctypes.windll.kernel32.GetConsoleWindow()\n'
                     'Path(os.environ["QUIET_MARKER"]).write_text(json.dumps(bool(w and ctypes.windll.user32.IsWindowVisible(w))))\n')
    (package / "local_sync.py").write_text(
        'import subprocess,sys,os\n'
        'def main():\n'
        '    return subprocess.run([sys.executable, os.environ["QUIET_PROBE"]], creationflags=subprocess.CREATE_NO_WINDOW).returncode\n')
    result = subprocess.run([str(Path(sys.executable).with_name("pythonw.exe")), str(scripts / launcher.name)],
                            env=dict(os.environ, QUIET_MARKER=str(marker), QUIET_PROBE=str(probe)), timeout=30)
    assert result.returncode == 0
    assert json.loads(marker.read_text()) is False
