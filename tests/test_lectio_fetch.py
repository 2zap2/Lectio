from __future__ import annotations

import unittest
from unittest.mock import patch
import gzip

from lectio_sync.lectio_fetch import fetch_html


class _FakeHeaders:
    def __init__(self, *, content_encoding: str | None, charset: str | None = "utf-8") -> None:
        self._content_encoding = content_encoding
        self._charset = charset

    def get(self, name: str, default=None):
        if name.lower() == "content-encoding":
            return self._content_encoding
        return default

    def get_content_charset(self):
        return self._charset


class _FakeResponse:
    def __init__(self, *, body: bytes, headers: _FakeHeaders) -> None:
        self._body = body
        self.headers = headers

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class LectioFetchTests(unittest.TestCase):
    def test_fetch_html_decompresses_gzip(self) -> None:
        html = "<html><body><table id='m_Content_SkemaMedNavigation_skema_skematabel'></table></body></html>"
        gz = gzip.compress(html.encode("utf-8"))

        def _fake_urlopen(req, timeout=30):
            return _FakeResponse(body=gz, headers=_FakeHeaders(content_encoding="gzip"))

        with patch("lectio_sync.lectio_fetch.urlopen", _fake_urlopen):
            out = fetch_html(url="https://example.invalid/", cookie_header="a=b", timeout_seconds=5)

        self.assertIn("<table", out)
        self.assertIn("m_Content_SkemaMedNavigation_skema_skematabel", out)

    def test_fetch_html_strips_cookie_prefix_and_sets_identity_encoding(self) -> None:
        html = "<html><body>ok</body></html>"
        captured = {"cookie": None, "accept_encoding": None}

        def _fake_urlopen(req, timeout=30):
            # urllib's Request stores headers in a case-insensitive mapping,
            # but the exact key casing is not guaranteed.
            hdrs = {k.lower(): v for k, v in dict(req.header_items()).items()}
            captured["cookie"] = hdrs.get("cookie")
            captured["accept_encoding"] = hdrs.get("accept-encoding")
            return _FakeResponse(body=html.encode("utf-8"), headers=_FakeHeaders(content_encoding=None))

        with patch("lectio_sync.lectio_fetch.urlopen", _fake_urlopen):
            out = fetch_html(url="https://example.invalid/", cookie_header="Cookie: a=b; c=d", timeout_seconds=5)

        self.assertEqual(out, html)
        self.assertEqual(captured["cookie"], "a=b; c=d")
        self.assertEqual(captured["accept_encoding"], "identity")


if __name__ == "__main__":
    unittest.main()
