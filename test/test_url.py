"""Tests for portal URL normalization and config-entry identity."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components/brunata_nutzerportal/url.py"
)
_SPEC = importlib.util.spec_from_file_location("brunata_url", _PATH)
assert _SPEC and _SPEC.loader
url = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(url)


class PortalUrlTests(unittest.TestCase):
    def test_normalizes_https_url(self) -> None:
        self.assertEqual(
            url.normalize_portal_url(" HTTPS://Example.COM:443/path/// "),
            "https://example.com/path",
        )

    def test_rejects_insecure_and_malformed_urls(self) -> None:
        for value in (
            "http://example.com",
            "example.com",
            "https://user:password@example.com",
            "https://example.com/path?token=secret",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                url.normalize_portal_url(value)

    def test_unique_id_scopes_account_to_host_and_sap_client(self) -> None:
        self.assertEqual(
            url.config_entry_unique_id(
                "https://Portal.Example:443/tenant/", " 201 ", "USER@Example.COM"
            ),
            "portal.example|201|user@example.com",
        )
        self.assertNotEqual(
            url.config_entry_unique_id("https://one.example", "201", "user"),
            url.config_entry_unique_id("https://two.example", "201", "user"),
        )


if __name__ == "__main__":
    unittest.main()
