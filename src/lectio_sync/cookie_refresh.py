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

The cookie value is NEVER written to files or committed to git.
It is printed to stdout only when `--print-cookie` is explicitly requested,
or when `gh` is unavailable and the user must paste it manually.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


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


def _cookies_to_header(cookies: list) -> str:
    """Convert a list of Playwright cookie dicts to a Cookie header value."""
    parts = [
        f"{c['name']}={c['value']}"
        for c in cookies
        if c.get("name") and c.get("value") is not None
    ]
    return "; ".join(parts)


def _filter_cookies_for_host(cookies: list, schedule_url: str) -> list:
    """Keep only cookies whose domain matches the Lectio host."""
    hostname = urlparse(schedule_url).hostname or ""
    host_suffix = ".".join(hostname.lower().split(".")[-2:])  # e.g. "lectio.dk"

    matching = [
        c for c in cookies
        if host_suffix in c.get("domain", "").lstrip(".").lower()
    ]
    # Fallback: if nothing matched (unusual), return everything
    return matching or cookies


def _update_github_secret(secret_name: str, value: str, repo: str | None) -> bool:
    """Shell out to ``gh secret set``.  Returns True on success."""
    cmd = ["gh", "secret", "set", secret_name, "--body", value]
    if repo:
        cmd += ["--repo", repo]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return True
        print(
            f"ERROR: `gh secret set` failed (exit {result.returncode}):\n"
            f"{result.stderr.strip()}",
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
) -> int:
    """
    Open a Playwright Chromium window, wait for the Lectio schedule page,
    capture session cookies, and update the configured GitHub Secret.

    Parameters
    ----------
    schedule_url:
        The Lectio Advanced Schedule URL (SkemaAvanceret.aspx).
    profile_dir:
        Directory for the persistent browser profile.  Defaults to
        ``%LOCALAPPDATA%\\lectio-sync\\playwright-profile`` on Windows.
        The profile is reused across runs so an active session means the
        browser can close without any manual login step.
    login_timeout_seconds:
        How long to wait for the schedule page to appear after launching the
        browser (default 5 minutes).  Increase if MitID takes longer.
    secret_name:
        GitHub Actions Secret name to update (default ``LECTIO_COOKIE_HEADER``).
    github_repo:
        Optional ``owner/repo`` string passed to ``gh``.  When omitted ``gh``
        infers the repo from the current working directory.
    print_cookie:
        Print the cookie header value to stdout even when `gh` succeeds.
        Off by default — avoids the value appearing in terminal history.
    headless:
        When True the Chromium window is hidden (suitable for unattended/scheduled runs).
        Requires that the persistent profile already holds a valid Lectio session so no
        login page is shown; if a login page appears the script will time-out.
        Default False keeps the existing interactive behaviour.
    no_gh:
        Skip the ``gh secret set`` step entirely.  Implies printing the
        cookie so the user can paste it manually.

    Returns
    -------
    int
        0 on success, 1 on failure.
    """
    sync_playwright = _require_playwright()
    resolved_profile = profile_dir or _default_profile_dir()
    resolved_profile.mkdir(parents=True, exist_ok=True)

    print(f"Browser profile: {resolved_profile}")
    if headless:
        print("Running headless Chromium — profile must have an active session.")
    else:
        print("Opening Chromium — log into Lectio if prompted.")
        print("The window will close automatically once the schedule is detected.")

    cookie_header: str | None = None

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(resolved_profile),
            headless=headless,
            args=([] if headless else ["--disable-blink-features=AutomationControlled"]),
            no_viewport=True,
        )

        # Reuse an existing tab if one is already open (persistent context).
        page = context.pages[0] if context.pages else context.new_page()

        print(f"Navigating to {schedule_url} ...")
        page.goto(schedule_url, timeout=30_000)

        deadline = time.monotonic() + login_timeout_seconds
        schedule_visible = False

        while time.monotonic() < deadline:
            try:
                html = page.content()
            except Exception:
                # Page may be mid-navigation; just retry.
                time.sleep(1)
                continue

            if _is_schedule_page(html):
                schedule_visible = True
                break

            if _is_login_page(html):
                # Only print this hint once.
                if not getattr(refresh_cookie, "_login_hint_shown", False):
                    print("Login page detected — please log in with MitID in the browser window.")
                    refresh_cookie._login_hint_shown = True  # type: ignore[attr-defined]

            time.sleep(1)

        if not schedule_visible:
            print(
                f"\nERROR: Timed out after {login_timeout_seconds}s waiting for the schedule page.\n"
                "Check that the URL points to SkemaAvanceret.aspx and that you are logged in.",
                file=sys.stderr,
            )
            context.close()
            return 1

        # Collect and filter cookies
        all_cookies = context.cookies()
        relevant = _filter_cookies_for_host(all_cookies, schedule_url)
        cookie_header = _cookies_to_header(relevant)
        context.close()

    if not cookie_header:
        print("ERROR: No cookies were captured after login.", file=sys.stderr)
        return 1

    print("Schedule detected — cookies captured.")

    if print_cookie:
        print(f"\nCookie header value:\n{cookie_header}\n")

    if no_gh:
        print("Skipping GitHub Secret update (--no-gh).")
        if not print_cookie:
            # User explicitly disabled gh; they need the value.
            print(f"\nCookie header value (copy this):\n{cookie_header}")
        return 0

    print(f"Updating GitHub Secret '{secret_name}'…")
    success = _update_github_secret(secret_name, cookie_header, github_repo)

    if success:
        print(f"GitHub Secret '{secret_name}' updated successfully.")
        print(
            "\nTo verify, trigger a manual workflow run:\n"
            "  gh workflow run update-calendar.yml\n"
            "or visit Actions → Update calendar.ics → Run workflow."
        )
        return 0

    # gh failed — print the value as a last-resort fallback.
    print(
        "\nAutomatic Secret update failed. Copy the value below and paste it at:\n"
        f"  GitHub → Settings → Secrets and variables → Actions → {secret_name}\n"
    )
    print(cookie_header)
    return 1
