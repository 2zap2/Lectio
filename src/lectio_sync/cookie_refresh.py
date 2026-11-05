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

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse


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


def _cookies_to_header(cookies: list) -> str:
    """Convert a list of Playwright cookie dicts to a Cookie header value."""
    parts = [
        f"{c['name']}={c['value']}"
        for c in cookies
        if c.get("name") and c.get("value") is not None
    ]
    return "; ".join(parts)


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
        saved = json.loads((profile / "session-cookies.json").read_text(encoding="utf-8"))
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
    target = profile / "session-cookies.json"
    temporary = target.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        if sys.platform != "win32":
            os.chmod(temporary, 0o600)
        json.dump(cookies, stream)
    temporary.replace(target)


def _update_github_secret(secret_name: str, value: str, repo: str | None) -> bool:
    """Shell out to ``gh secret set``.  Returns True on success."""
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
) -> int:
    """Reuse Lectio/SSO state, capture renewed cookies, and update the secret.

    Session cookies are saved inside the dedicated browser profile, outside
    the repository. Their server-side validity and expiry are never extended
    locally. Only cookies matching the schedule URL are sent to GitHub.
    An unattended run returns 2 when login is required; it never opens a window.
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

    with sync_playwright() as p:
        while True:
            context = p.chromium.launch_persistent_context(
                str(resolved_profile), headless=headless,
                args=[] if headless else ["--disable-blink-features=AutomationControlled"],
                no_viewport=True,
            )
            needs_visible_login = False
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
                    if _is_authenticated_schedule(html):
                        relevant = _filter_cookies_for_host(context.cookies(), schedule_url)
                        cookie_header = _cookies_to_header(relevant)
                        if cookie_header:
                            _save_session_cookies(context, resolved_profile)
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
                context.close()
            if cookie_header:
                break
            if needs_visible_login:
                if not interactive:
                    print("Login required. Run scripts/refresh_cookie.ps1 once to sign in.", file=sys.stderr)
                    return 2
                print("Saved login could not be renewed silently. Opening Chromium for login.")
                headless = False
                continue
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
