from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import gzip
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
import zlib
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


@dataclass(frozen=True)
class FetchDiagnostics:
    requested_url: str
    final_url: str
    status_code: int | None
    content_type: str
    content_encoding: str
    raw_bytes_len: int
    decoded_chars_len: int


@dataclass(frozen=True)
class LectioWeek:
    week: int
    year: int

    @property
    def week_param(self) -> str:
        # Observed Lectio format: WWYYYY (e.g. 062026)
        return f"{self.week:02d}{self.year}"


def iter_weeks_for_window(*, timezone_name: str, days_past: int, days_future: int) -> list[LectioWeek]:
    """Return ISO weeks (week/year pairs) that overlap the date window.

    We use ISO week numbering because Lectio URLs in the captured HTML look like:
      week=062026
    which matches ISO week 6 in year 2026.
    """

    try:
        from zoneinfo import ZoneInfo

        tzinfo = ZoneInfo(timezone_name)
        today = datetime.now(tzinfo).date()
    except Exception:
        # Fallback: local time; should not happen on Python 3.11+.
        today = date.today()

    window_start = today - timedelta(days=days_past)
    window_end = today + timedelta(days=days_future)

    weeks: list[LectioWeek] = []
    seen: set[tuple[int, int]] = set()

    d = window_start
    while d <= window_end:
        iso_year, iso_week, _ = d.isocalendar()
        key = (iso_week, iso_year)
        if key not in seen:
            seen.add(key)
            weeks.append(LectioWeek(week=iso_week, year=iso_year))
        d += timedelta(days=7)

    # Ensure the end week is included even if the window is < 7 days
    iso_year, iso_week, _ = window_end.isocalendar()
    key = (iso_week, iso_year)
    if key not in seen:
        weeks.append(LectioWeek(week=iso_week, year=iso_year))

    return weeks


def build_week_url(schedule_url: str, week: LectioWeek) -> str:
    """Return schedule_url with its querystring's week= set/overwritten."""

    parsed = urlparse(schedule_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs["week"] = [week.week_param]

    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def build_student_url(schedule_url: str, student_id: str) -> str:
    """Select one student, removing room/teacher/group selections."""
    if not student_id.isascii() or not student_id.isdecimal():
        raise ValueError("student_id must contain only digits")
    parsed = urlparse(schedule_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs = {key: value for key, value in qs.items() if key.lower() in {"type", "week"}}
    qs["studentsel"] = [student_id]
    return urlunparse(parsed._replace(query=urlencode(qs, doseq=True), fragment=""))


def _normalize_cookie_header(cookie_header: str) -> str:
    v = (cookie_header or "").strip()
    if not v:
        return ""

    # Common mistake: user pastes the full header line.
    # GitHub Secret should contain only the value part.
    if v.lower().startswith("cookie:"):
        v = v.split(":", 1)[1].strip()

    # Another common mistake: secrets wrapped in quotes.
    if (len(v) >= 2) and ((v[0] == v[-1]) and v[0] in {"\"", "'"}):
        v = v[1:-1].strip()

    return v


class _OriginCookiePolicy(DefaultCookiePolicy):
    def __init__(self, origin: tuple[str, str]) -> None:
        super().__init__(strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain)
        self.origin = origin

    def return_ok(self, cookie, request) -> bool:
        parsed = urlparse(request.full_url)
        return ((parsed.scheme.lower(), parsed.netloc.lower()) == self.origin
                and super().return_ok(cookie, request))


class _SessionCookieJar(CookieJar):
    """Replace imported cookies when the server supplies their actual scope."""

    def __init__(self, *, url: str, policy: DefaultCookiePolicy) -> None:
        super().__init__(policy=policy)
        self.seeded: dict[str, Cookie] = {}
        self.path = urlparse(url).path or "/"
        self.origin = (urlparse(url).scheme.lower(), urlparse(url).netloc.lower())
        self.hostname = urlparse(url).hostname or ""
        self._extracting_request = None

    def extract_cookies(self, response, request) -> None:
        self._extracting_request = request
        try:
            super().extract_cookies(response, request)
        finally:
            self._extracting_request = None

    def clear(self, domain=None, path=None, name=None) -> None:
        # CookieJar processes expired Set-Cookie by calling clear directly,
        # without calling set_cookie. Also remove an imported value when the
        # server deletes it using its original Domain/Path metadata.
        seed = self.seeded.get(name)
        if seed is not None and domain and path and self._extracting_request:
            source = urlparse(self._extracting_request.full_url)
            domain_matches = (self.hostname == domain.lstrip(".") or (
                domain.startswith(".") and "." in domain.lstrip(".")
                and self.hostname.endswith(domain)))
            if ((source.scheme.lower(), source.netloc.lower()) == self.origin
                    and domain_matches
                    and (self.path == path or self.path.startswith(path.rstrip("/") + "/"))):
                self.seeded.pop(name, None)
                if (domain, path) != (seed.domain, seed.path):
                    try:
                        super().clear(seed.domain, seed.path, seed.name)
                    except KeyError:
                        pass
        super().clear(domain, path, name)

    def set_cookie(self, cookie, *args, **kwargs) -> None:
        seed = self.seeded.get(cookie.name)
        if seed is not None and (
            self.path == cookie.path or self.path.startswith(cookie.path.rstrip("/") + "/")
        ):
            # A raw Cookie header has no Domain/Path metadata. Do not send both
            # the imported value and its correctly scoped replacement.
            try:
                self.clear(seed.domain, seed.path, seed.name)
            except KeyError:
                pass
            self.seeded.pop(cookie.name, None)
        super().set_cookie(cookie, *args, **kwargs)


class LectioSession:
    """Keep server-issued cookie changes, including those on redirects.

    A copied Cookie header is only a snapshot. A cookie jar also processes
    Set-Cookie, scopes cookies to their host/path, and honours deletions.
    This object never writes credentials to disk or logs.
    """

    def __init__(self, *, url: str, cookie_header: str) -> None:
        parsed = urlparse(url)
        self.origin = (parsed.scheme.lower(), parsed.netloc.lower())
        hostname = parsed.hostname or ""
        if not hostname or parsed.scheme not in {"http", "https"}:
            raise ValueError("A valid HTTP(S) schedule URL is required")
        self.jar = _SessionCookieJar(url=url, policy=_OriginCookiePolicy(self.origin))
        for part in _normalize_cookie_header(cookie_header).split(";"):
            name, sep, value = part.strip().partition("=")
            if name and sep:
                seed = Cookie(
                    version=0, name=name, value=value, port=None,
                    port_specified=False, domain=hostname,
                    domain_specified=False, domain_initial_dot=False,
                    path="/", path_specified=True,
                    secure=parsed.scheme == "https", expires=None,
                    discard=True, comment=None, comment_url=None, rest={},
                )
                self.jar.set_cookie(seed)
                self.jar.seeded[name] = seed
        self.opener = build_opener(HTTPCookieProcessor(self.jar))

    def cookie_header(self, url: str) -> str:
        request = Request(url)
        self.jar.add_cookie_header(request)
        return request.get_header("Cookie", "")

    def open(self, request: Request, *, timeout: int):
        parsed = urlparse(request.full_url)
        if (parsed.scheme.lower(), parsed.netloc.lower()) != self.origin:
            raise ValueError("A Lectio session can only fetch its configured origin")
        return self.opener.open(request, timeout=timeout)


def fetch_html_with_diagnostics(*, url: str, cookie_header: str, timeout_seconds: int = 30,
                                session: LectioSession | None = None) -> tuple[str, FetchDiagnostics]:
    """Fetch a Lectio HTML page and return both HTML and non-sensitive response diagnostics."""

    cookie_value = _normalize_cookie_header(cookie_header)
    if not cookie_value:
        raise ValueError("cookie_header is required")

    headers = {
        # Make it look like a normal browser request.
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "da,en-US;q=0.9,en;q=0.8",
        # Avoid Brotli (br) which we do not decode without extra deps.
        "Accept-Encoding": "identity",
    }

    req = Request(url, headers=headers, method="GET")
    session = session or LectioSession(url=url, cookie_header=cookie_value)
    try:
        with session.open(req, timeout=timeout_seconds) as resp:
            raw = resp.read()

            content_type = (resp.headers.get("Content-Type") or "").strip()
            content_encoding = (resp.headers.get("Content-Encoding") or "").strip().lower()
            status_code = getattr(resp, "status", None)
            if status_code is None:
                try:
                    status_code = resp.getcode()
                except Exception:
                    status_code = None
            final_url = ""
            try:
                final_url = resp.geturl() or ""
            except Exception:
                final_url = ""

            if "br" in content_encoding:
                raise RuntimeError(
                    "Server returned Content-Encoding=br (Brotli), which this tool does not decode. "
                    "Try again; if it persists, we need to add Brotli decoding or adjust request headers."
                )

            # Some servers send compressed responses even when clients don't
            # explicitly ask. urllib does not automatically decompress.
            if "gzip" in content_encoding:
                raw = gzip.decompress(raw)
            elif "deflate" in content_encoding:
                try:
                    raw = zlib.decompress(raw)
                except zlib.error:
                    # Raw DEFLATE stream (no zlib header)
                    raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            elif raw[:2] == b"\x1f\x8b":
                # Heuristic: gzip magic bytes.
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass

            # lectio.dk pages are typically UTF-8
            charset = "utf-8"
            try:
                content_charset = resp.headers.get_content_charset()
                if content_charset:
                    charset = content_charset
            except Exception:
                pass

            html = raw.decode(charset, errors="replace")
            diag = FetchDiagnostics(
                requested_url=url,
                final_url=final_url or url,
                status_code=status_code,
                content_type=content_type,
                content_encoding=content_encoding,
                raw_bytes_len=len(raw),
                decoded_chars_len=len(html),
            )
            return html, diag
    except HTTPError as exc:
        raise RuntimeError(f"HTTP error fetching Lectio HTML: {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error fetching Lectio HTML: {exc.reason}") from exc


def fetch_html(*, url: str, cookie_header: str, timeout_seconds: int = 30) -> str:
    """Fetch a Lectio HTML page using an existing authenticated session cookie.

    This does NOT perform MitID login. It relies on you providing a valid cookie header.
    """

    html, _diag = fetch_html_with_diagnostics(url=url, cookie_header=cookie_header, timeout_seconds=timeout_seconds)
    return html


def fetch_weeks_html(
    *,
    schedule_url: str,
    cookie_header: str,
    weeks: Iterable[LectioWeek],
    timeout_seconds: int = 30,
) -> list[tuple[LectioWeek, str]]:
    session = LectioSession(url=schedule_url, cookie_header=cookie_header)
    out: list[tuple[LectioWeek, str]] = []
    for wk in weeks:
        url = build_week_url(schedule_url, wk)
        html, _ = fetch_html_with_diagnostics(url=url, cookie_header=cookie_header, timeout_seconds=timeout_seconds, session=session)
        out.append((wk, html))
    return out


def fetch_weeks_html_with_diagnostics(
    *,
    schedule_url: str,
    cookie_header: str,
    weeks: Iterable[LectioWeek],
    timeout_seconds: int = 30,
    session: LectioSession | None = None,
) -> list[tuple[LectioWeek, str, FetchDiagnostics]]:
    session = session or LectioSession(url=schedule_url, cookie_header=cookie_header)
    out: list[tuple[LectioWeek, str, FetchDiagnostics]] = []
    for wk in weeks:
        url = build_week_url(schedule_url, wk)
        html, diag = fetch_html_with_diagnostics(url=url, cookie_header=cookie_header, timeout_seconds=timeout_seconds, session=session)
        out.append((wk, html, diag))
    return out
