"""Shared local browser lifecycle; credentials never leave the profile."""
from contextlib import contextmanager
from pathlib import Path
import time
from urllib.parse import urlparse

from . import cookie_refresh as cookies


class LoginRequired(RuntimeError):
    pass


class InvalidLectioPage(RuntimeError):
    pass


def launch_context(playwright, profile: Path, *, headless: bool):
    return playwright.chromium.launch_persistent_context(
        str(profile), headless=headless,
        args=[] if headless else ["--disable-blink-features=AutomationControlled"],
        no_viewport=True, user_agent=cookies._profile_user_agent(profile),
    )


@contextmanager
def browser_context(profile: Path | None = None, *, interactive: bool = False):
    profile = (profile or cookies._default_profile_dir()).resolve()
    if profile.is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("The browser profile must be outside the repository")
    profile.mkdir(parents=True, exist_ok=True)
    with cookies._require_playwright()() as playwright:
        context = launch_context(playwright, profile, headless=not interactive)
        try:
            cookies._restore_session_cookies(context, profile)
            yield context
        finally:
            try:
                cookies._save_session_cookies(context, profile)
            finally:
                context.close()


def ensure_authenticated(page, schedule_url: str, *, interactive: bool = False,
                         timeout_seconds: int = 600) -> None:
    """Enter the ordinary Lectio SSO flow, allowing saved login to renew itself."""
    page.goto(schedule_url, timeout=30_000, wait_until="domcontentloaded")
    deadline = time.monotonic() + (timeout_seconds if interactive else 25)
    login_started = False
    while time.monotonic() < deadline:
        html = page.content()
        if cookies._is_authenticated_schedule(html):
            return
        host = urlparse(page.url).hostname
        if host == "security-check.stil.dk" and not interactive:
            raise LoginRequired("STIL requires verification in the local browser")
        if not login_started and (cookies._is_schedule_page(html) or cookies._is_login_page(html)):
            page.goto(cookies._school_login_url(schedule_url), timeout=30_000,
                      wait_until="domcontentloaded")
            login_started = True
            continue
        if cookies._is_logged_in_page(html):
            page.goto(schedule_url, timeout=30_000, wait_until="domcontentloaded")
            continue
        time.sleep(1)
    # An unknown error page is not evidence that the user must log in.
    if cookies._is_login_page(page.content()) or urlparse(page.url).hostname in {
        "security-check.stil.dk", "broker.unilogin.dk", "login.unilogin.dk",
        "idp.unilogin.dk", "login.mitid.dk",
    }:
        raise LoginRequired("Lectio needs login in the local browser")
    raise InvalidLectioPage("Lectio did not return an authenticated schedule")
