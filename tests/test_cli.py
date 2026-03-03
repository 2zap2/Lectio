from __future__ import annotations

import unittest

from lectio_sync.cli import _is_auth_redirect


class AuthRedirectTests(unittest.TestCase):
    def test_security_check_stil_dk_detected(self) -> None:
        self.assertTrue(
            _is_auth_redirect("https://security-check.stil.dk/NDBD/validate")
        )

    def test_logind_lectio_dk_detected(self) -> None:
        self.assertTrue(
            _is_auth_redirect("https://logind.lectio.dk/login")
        )

    def test_normal_lectio_url_not_detected(self) -> None:
        self.assertFalse(
            _is_auth_redirect(
                "https://www.lectio.dk/lectio/123/SkemaAvanceret.aspx?week=092026"
            )
        )

    def test_empty_url_not_detected(self) -> None:
        self.assertFalse(_is_auth_redirect(""))

    def test_whitespace_only_url_not_detected(self) -> None:
        self.assertFalse(_is_auth_redirect("   "))


if __name__ == "__main__":
    unittest.main()
