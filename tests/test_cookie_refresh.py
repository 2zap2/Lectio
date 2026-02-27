from __future__ import annotations

import unittest

from lectio_sync.cookie_refresh import (
    _cookies_to_header,
    _filter_cookies_for_host,
    _is_login_page,
    _is_schedule_page,
)


class CookiesToHeaderTests(unittest.TestCase):
    def test_basic_join(self) -> None:
        cookies = [
            {"name": "ASP.NET_SessionId", "value": "abc123"},
            {"name": "lectio_linked", "value": "1"},
        ]
        result = _cookies_to_header(cookies)
        self.assertEqual(result, "ASP.NET_SessionId=abc123; lectio_linked=1")

    def test_skips_empty_name(self) -> None:
        cookies = [
            {"name": "", "value": "orphan"},
            {"name": "valid", "value": "yes"},
        ]
        result = _cookies_to_header(cookies)
        self.assertEqual(result, "valid=yes")

    def test_skips_none_value(self) -> None:
        cookies = [{"name": "broken", "value": None}, {"name": "ok", "value": "1"}]
        result = _cookies_to_header(cookies)
        self.assertEqual(result, "ok=1")

    def test_empty_list(self) -> None:
        self.assertEqual(_cookies_to_header([]), "")


class FilterCookiesTests(unittest.TestCase):
    def test_keeps_lectio_dk_cookies(self) -> None:
        cookies = [
            {"name": "A", "value": "1", "domain": ".lectio.dk"},
            {"name": "B", "value": "2", "domain": ".google.com"},
            {"name": "C", "value": "3", "domain": "lectio.dk"},
        ]
        schedule_url = "https://www.lectio.dk/lectio/123/SkemaAvanceret.aspx"
        result = _filter_cookies_for_host(cookies, schedule_url)
        names = [c["name"] for c in result]
        self.assertIn("A", names)
        self.assertIn("C", names)
        self.assertNotIn("B", names)

    def test_fallback_returns_all_when_no_match(self) -> None:
        # If nothing matches the host, we return everything (better than nothing).
        cookies = [{"name": "X", "value": "v", "domain": ".other.com"}]
        result = _filter_cookies_for_host(cookies, "https://www.lectio.dk/lectio/1/Skema.aspx")
        self.assertEqual(result, cookies)


class PageClassifierTests(unittest.TestCase):
    def test_schedule_table_detected(self) -> None:
        html = "<table id='m_Content_SkemaMedNavigation_skema_skematabel'></table>"
        self.assertTrue(_is_schedule_page(html))

    def test_schedule_bricks_detected(self) -> None:
        html = "<a class='s2skemabrik'></a>"
        self.assertTrue(_is_schedule_page(html))

    def test_login_page_mitid(self) -> None:
        html = "<div>Log ind med MitID</div>"
        self.assertTrue(_is_login_page(html))
        self.assertFalse(_is_schedule_page(html))

    def test_login_page_log_ind(self) -> None:
        html = "<form id='loginform'><button>Log ind</button></form>"
        self.assertTrue(_is_login_page(html))

    def test_random_html_is_neither(self) -> None:
        html = "<html><body><p>Hello</p></body></html>"
        self.assertFalse(_is_schedule_page(html))
        self.assertFalse(_is_login_page(html))


if __name__ == "__main__":
    unittest.main()
