"""cookie_refresh.py

Opens a visible Chromium window (via Playwright), waits for the user to log in
to Lectio if needed, then captures the session cookies and updates the
LECTIO_COOKIE_HEADER GitHub Secret via the `gh` CLI.

Intended UX
-----------
1.  User double-clicks the desktop shortcut (scripts/refresh_cookie.ps1).
2.  A Chromium window opens showing the Lectio schedule URL.
    - If the session is still valid the schedule appears immediately.
    - If not, the user logs in with MitID as normal.
3.  Once the schedule page is visible the window closes automatically.
4.  The script updates the GitHub Secret and prints one confirmation line.

Session cookies are retained inside the dedicated local browser profile,
outside the repository. Cookie values are printed only when --print-cookie
or --no-gh is explicitly requested, including when a secret update fails.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

from bs4 import BeautifulSoup

from .cookie_store import load_session_cookies, save_session_cookies


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_profile_dir() -> Path:
    """Return an OS-appropriate persistent browser-profile location.

    Placing it outside the repo avoids any risk of accidental git-commit.
    """
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local_app) / "lectio-sync" / "playwright-profile"
    # macOS / Linux fallback
    return Path.home() / ".local" / "share" / "lectio-sync" / "playwright-profile"


def _profile_user_agent(profile: Path) -> str | None:
    """Keep the profile's browser identity consistent when running headlessly.

    Lectio's remembered login worked in visible Chrome but not with the default
    HeadlessChrome identity. A live one-variable check confirmed that using
    normal Chrome's identity restores access. Chromium itself records its version
    in the profile; do not hard-code the version or read the user's normal browser.
    """
    try:
        version = (profile / "Last Version").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    match = re.fullmatch(r"(\d+)\.\d+\.\d+\.\d+", version)
    if not match:
        return None
    platform = {"win32": "Windows NT 10.0; Win64; x64",
                "darwin": "Macintosh; Intel Mac OS X 10_15_7"}.get(sys.platform, "X11; Linux x86_64")
    return (f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{match[1]}.0.0.0 Safari/537.36")


def _require_playwright():
    """Import playwright.sync_api or exit with a helpful install message."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import]
        return sync_playwright
    except ImportError:
        print(
            "\nERROR: Playwright is not installed.\n"
            "Install it once with:\n"
            "    py -m pip install playwright\n"
            "    py -m playwright install chromium\n",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _is_schedule_page(html: str) -> bool:
    """Return True when the fetched HTML looks like the Lectio schedule page."""
    low = (html or "").lower()
    return (
        "m_content_skemamednavigation_skema_skematabel" in low
        or "s2skemabrik" in low
    )


def _is_login_page(html: str) -> bool:
    low = (html or "").lower()
    return "mitid" in low or "log ind" in low or "loginform" in low


def _is_authenticated_schedule(html: str) -> bool:
    """A public schedule table alone does not prove the login succeeded."""
    return _is_schedule_page(html) and _is_logged_in_page(html)


def _is_logged_in_page(html: str) -> bool:
    initialized = re.search(r"SessionHelper\s*\.\s*Initialize\s*\(\s*(true|false)", html, re.I)
    if initialized:
        return initialized.group(1).lower() == "true"
    return bool(re.search(r"(?:logout\.aspx|log\s+ud)", html, re.I))


def _school_login_url(schedule_url: str) -> str:
    parsed = urlparse(schedule_url)
    school = re.match(r"(/lectio/\d+/)", parsed.path, re.I)
    if not school:
        raise ValueError("The schedule URL must include /lectio/<school>/")
    relative = parsed.path[len(school.group(1)):] + ("?" + parsed.query if parsed.query else "")
    return f"{parsed.scheme}://{parsed.netloc}{school.group(1)}login.aspx?{urlencode({'prevurl': relative})}"


def _remembered_login_expiry(html: str, *, today: date | None = None) -> date | None:
    """Only Lectio's unexpired current-device entry proves remembered login.

    Cookie persistence alone is not evidence: Lectio also has persistent
    anonymous cookies. The account Log page is the server's source of truth.
    Expiry is at midnight, so an entry expiring today no longer qualifies.
    """
    if today is None:
        try:
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo("Europe/Copenhagen")).date()
        except (ImportError, KeyError):
            today = date.today()
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id=re.compile(r"(?:^|_)ForblivLoggetIndGV$"))
    if table is None:
        return None
    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 4 or not re.match(r"Denne\s+enhed\s*:", cells[3].get_text(" ", strip=True), re.I):
            continue
        match = re.fullmatch(r"(\d{1,2}/\d{1,2}-\d{4})(?:\s+00:00)?", cells[2].get_text(" ", strip=True))
        if match:
            try:
                expiry = datetime.strptime(match[1], "%d/%m-%Y").date()
            except ValueError:
                continue
            if expiry > today:
                return expiry
    return None


def _cookies_to_header(cookies: list) -> str:
    """Convert a list of Playwright cookie dicts to a Cookie header value."""
    parts = [
        f"{c['name']}={c['value']}"
        for c in cookies
        if c.get("name") and c.get("value") is not None
    ]
    return "; ".join(parts)


def _session_cookie_header(value: str) -> str:
    """Allow only the short Lectio session and its session-only UI flags.

    Keep remembered login, SSO, and newly introduced/unknown cookies local.
    Apply this at the upload boundary too, including the calendar-fetch path.
    """
    allowed = {"ASP.NET_SessionId", "isloggedin3", "BaseSchoolUrl", "LastAuthenticatedPageLoad2"}
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return ""
    selected = {}
    for part in value.split(";"):
        name, sep, cookie_value = part.strip().partition("=")
        if name in allowed and sep:
            if name in selected or not cookie_value:
                return ""
            selected[name] = cookie_value
    if "ASP.NET_SessionId" not in selected:
        return ""
    return "; ".join(f"{name}={v}" for name, v in selected.items())


def _filter_cookies_for_host(cookies: list, schedule_url: str) -> list:
    """Keep only cookies that match the target host and path; fail closed."""
    parsed = urlparse(schedule_url)
    hostname = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    return [
        c for c in cookies
        if _cookie_matches_host(c, hostname)
        and (not c.get("secure") or parsed.scheme == "https")
        and (path == c.get("path", "/")
             or path.startswith(c.get("path", "/").rstrip("/") + "/"))
        and (c.get("expires", -1) < 0 or c["expires"] > time.time())
    ]


def _cookie_matches_host(cookie: dict, hostname: str) -> bool:
    domain = cookie.get("domain", "").lower()
    return bool(domain) and (
        hostname == domain.lstrip(".")
        or (domain.startswith(".") and hostname.endswith(domain))
    )


def _restore_session_cookies(context, profile: Path) -> None:
    """Chromium may discard session cookies on exit, even with a saved profile."""
    try:
        saved = load_session_cookies(profile)
    except FileNotFoundError:
        return
    except (ValueError, OSError):
        print("WARNING: Saved session cookies could not be read; using the browser profile.", file=sys.stderr)
        return
    if not isinstance(saved, list):
        return
    existing = {(c["name"], c["domain"], c["path"]) for c in context.cookies()}
    missing = [c for c in saved if isinstance(c, dict)
               and all(k in c for k in ("name", "value", "domain", "path"))
               and isinstance(c.get("expires", -1), (int, float))
               and c.get("expires", -1) < 0
               and (c["name"], c["domain"], c["path"]) not in existing]
    if missing:
        context.add_cookies(missing)


def _save_session_cookies(context, profile: Path) -> None:
    """Retain session cookies for Lectio and its SSO flow without changing expiry."""
    cookies = [c for c in context.cookies() if c.get("expires", -1) < 0]
    save_session_cookies(profile, cookies)


def _update_github_secret(secret_name: str, value: str, repo: str | None) -> bool:
    """Shell out to ``gh secret set``.  Returns True on success."""
    value = _session_cookie_header(value)
    if not value:
        print("ERROR: No valid short Lectio session to export; the GitHub secret was not changed.", file=sys.stderr)
        return False
    cmd = ["gh", "secret", "set", secret_name]
    if repo:
        cmd += ["--repo", repo]
    try:
        result = subprocess.run(cmd, input=value, capture_output=True, text=True)
        if result.returncode == 0:
            return True
        print(
            f"ERROR: `gh secret set` failed (exit {result.returncode}). Check GitHub CLI authentication and Secrets permissions.",
            file=sys.stderr,
        )
        return False
    except FileNotFoundError:
        print(
            "\nERROR: GitHub CLI (`gh`) is not installed or not in PATH.\n"
            "Install it from https://cli.github.com/ and run `gh auth login`.",
            file=sys.stderr,
        )
        return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def refresh_cookie(
    *,
    schedule_url: str,
    profile_dir: Path | None = None,
    login_timeout_seconds: int = 300,
    secret_name: str = "LECTIO_COOKIE_HEADER",
    github_repo: str | None = None,
    print_cookie: bool = False,
    headless: bool = False,
    no_gh: bool = False,
    interactive: bool = True,
    require_remembered_login: bool = False,
) -> int:
    """Reuse Lectio/SSO state, capture renewed cookies, and update the secret.

    Session cookies are saved inside the dedicated browser profile, outside
    the repository. Their server-side validity and expiry are never extended
    locally. Only cookies matching the schedule URL are sent to GitHub.
    An unattended run never opens a window. Exit 2 means login is required,
    3 means remembered login is missing, and 4 means STIL security verification.
    The PowerShell scheduler can launch one visible recovery when needed.
    """
    parsed = urlparse(schedule_url)
    if parsed.scheme != "https" or not parsed.hostname or not (
        parsed.hostname == "lectio.dk" or parsed.hostname.endswith(".lectio.dk")
    ):
        print("ERROR: Cookie refresh requires an HTTPS Lectio URL.", file=sys.stderr)
        return 1
    if login_timeout_seconds <= 0:
        print("ERROR: Login timeout must be positive.", file=sys.stderr)
        return 1
    try:
        login_url = _school_login_url(schedule_url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    sync_playwright = _require_playwright()
    resolved_profile = (profile_dir or _default_profile_dir()).resolve()
    repository = Path(__file__).resolve().parents[2]
    if resolved_profile.is_relative_to(repository):
        print("ERROR: Browser profile must be outside the repository.", file=sys.stderr)
        return 1
    resolved_profile.mkdir(parents=True, exist_ok=True)
    print(f"Browser profile: {resolved_profile}")
    headless = headless or not interactive
    cookie_header = ""
    if require_remembered_login and interactive:
        print('Choose "Forbliv logget ind" in Lectio after signing in. '
              'The browser stays open until Lectio confirms this device and its expiry.')

    with sync_playwright() as p:
        while True:
            context = p.chromium.launch_persistent_context(
                str(resolved_profile), headless=headless,
                args=[] if headless else ["--disable-blink-features=AutomationControlled"],
                no_viewport=True,
                user_agent=_profile_user_agent(resolved_profile),
            )
            needs_visible_login = False
            missing_remembered_login = False
            saw_authenticated_schedule = False
            remember_setup_started = False
            try:
                _restore_session_cookies(context, resolved_profile)
                page = context.pages[0] if context.pages else context.new_page()
                print("Opening Lectio with the saved login...")
                page.goto(schedule_url, timeout=30_000)
                deadline = time.monotonic() + login_timeout_seconds
                # Allow redirects through the SSO provider before asking for login.
                silent_deadline = time.monotonic() + min(15, login_timeout_seconds)
                login_started = False
                returned_to_schedule = False
                while time.monotonic() < deadline:
                    try:
                        html = page.content()
                    except Exception:
                        time.sleep(1)
                        continue
                    page_url = page.url
                    if isinstance(page_url, str) and urlparse(page_url).hostname == "security-check.stil.dk":
                        if not interactive:
                            print("STIL security check required; this does not prove the login expired.", file=sys.stderr)
                            return 4
                    if _is_authenticated_schedule(html):
                        saw_authenticated_schedule = True
                        school_path = re.match(r"(/lectio/\d+/)", parsed.path, re.I).group(1)
                        status_url = f"{parsed.scheme}://{parsed.netloc}{school_path}indstillinger/AdgangIndstillinger.aspx"
                        page.goto(status_url, timeout=30_000)
                        expiry = _remembered_login_expiry(page.content())
                        if expiry:
                            print(f"Remembered login confirmed for this device; expires {expiry.isoformat()} (Lectio).")
                        elif require_remembered_login:
                            missing_remembered_login = True
                            if headless:
                                needs_visible_login = True
                                break
                            if not remember_setup_started:
                                print('No remembered login for this device yet. Sign in and choose "Forbliv logget ind".')
                                page.goto(login_url, timeout=30_000)
                                remember_setup_started = True
                                login_started = True
                                returned_to_schedule = False
                            else:
                                page.goto(schedule_url, timeout=30_000)
                                time.sleep(5)
                            continue
                        else:
                            print('WARNING: Only a short session is confirmed. Run scripts/refresh_cookie.ps1 '
                                  'to set up "Forbliv logget ind".', file=sys.stderr)
                        page.goto(schedule_url, timeout=30_000)
                        # Confirm that the schedule is still authenticated after
                        # the status-page round trip, before exporting cookies.
                        if not _is_authenticated_schedule(page.content()):
                            continue
                        relevant = _filter_cookies_for_host(context.cookies(), schedule_url)
                        cookie_header = _session_cookie_header(_cookies_to_header(relevant))
                        break
                    if login_started and not returned_to_schedule and _is_logged_in_page(html):
                        # The identity provider may return to the front page.
                        page.goto(schedule_url, timeout=30_000)
                        returned_to_schedule = True
                        continue
                    if not login_started and (_is_schedule_page(html) or _is_login_page(html)):
                        # A logged-out public schedule need not redirect by itself.
                        # Explicitly enter Lectio's ordinary login/SSO flow, which
                        # can reuse the identity provider's saved browser login.
                        page.goto(login_url, timeout=30_000)
                        login_started = True
                        silent_deadline = time.monotonic() + min(15, login_timeout_seconds)
                        continue
                    if headless and time.monotonic() >= silent_deadline:
                        needs_visible_login = True
                        break
                    time.sleep(1)
            finally:
                try:
                    # Also retain rotations/deletions during an unsuccessful
                    # login instead of restoring stale cookies on the next run.
                    _save_session_cookies(context, resolved_profile)
                finally:
                    context.close()
            if cookie_header:
                break
            if needs_visible_login:
                if not interactive:
                    if missing_remembered_login:
                        print('Remembered login missing. Run scripts/refresh_cookie.ps1 and choose "Forbliv logget ind".', file=sys.stderr)
                        return 3
                    print("Login required. Run scripts/refresh_cookie.ps1 once to sign in.", file=sys.stderr)
                    return 2
                print("Saved login could not be renewed silently. Opening Chromium for login.")
                headless = False
                continue
            if require_remembered_login and saw_authenticated_schedule:
                print('Remembered login was not confirmed before timeout; setup is incomplete.', file=sys.stderr)
                return 3
            print("ERROR: No authenticated schedule detected before the login timeout.", file=sys.stderr)
            return 1

    print("Authenticated schedule detected; cookies captured.")
    if print_cookie or no_gh:
        print(f"Cookie header value:\n{cookie_header}")
    if no_gh:
        return 0
    if _update_github_secret(secret_name, cookie_header, github_repo):
        print(f"GitHub Secret '{secret_name}' updated successfully.")
        return 0
    print("Secret update failed. Cookie values were not logged; retry after checking gh auth status.", file=sys.stderr)
    return 1
