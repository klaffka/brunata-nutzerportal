"""Regression tests for the standalone SAP login helpers."""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ProbeHelperTests(unittest.TestCase):
    def test_import_does_not_require_credentials(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            module = importlib.import_module("main")
        self.assertTrue(callable(module.main))

    def test_extracts_multiple_json_objects(self) -> None:
        from main import extract_json_objects

        text = 'headers\r\n{"error":{"message":"first"}}\r\n--part\r\n{"d":{"ok":true}}'
        self.assertEqual(
            extract_json_objects(text),
            [{"error": {"message": "first"}}, {"d": {"ok": True}}],
        )

    def test_extracts_inner_http_statuses(self) -> None:
        from main import extract_inner_http_statuses

        text = "HTTP/1.1 401 Unauthorized\r\n...HTTP/2 204 No Content\r\n"
        self.assertEqual(extract_inner_http_statuses(text), [401, 204])

    def test_rejects_cross_host_and_insecure_service_urls(self) -> None:
        from main import safe_service_url

        for value in (
            "https://attacker.example/steal",
            "http://nutzerportal.brunata-muenchen.de/service",
            "//attacker.example/steal",
        ):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                safe_service_url(value)

        self.assertEqual(
            safe_service_url("/sap/service"),
            "https://nutzerportal.brunata-muenchen.de/sap/service",
        )

    def test_csrf_request_has_timeout_and_checks_status(self) -> None:
        from main import REQUEST_TIMEOUT, fetch_csrf

        response = Mock()
        response.status_code = 200
        response.headers = {"x-csrf-token": "token"}
        session = Mock()
        session.head.return_value = response

        self.assertEqual(fetch_csrf(session), "token")
        self.assertEqual(session.head.call_args.kwargs["timeout"], REQUEST_TIMEOUT)
        self.assertFalse(session.head.call_args.kwargs["allow_redirects"])
        response.raise_for_status.assert_called_once_with()

    def test_batch_body_remains_crlf_only(self) -> None:
        from main import build_batch_body

        body, _ = build_batch_body("user@example.invalid", "secret", "201")
        self.assertNotIn("\n", body.replace("\r\n", ""))
        self.assertIn("POST CredentialSet?sap-client=201 HTTP/1.1\r\n", body)


if __name__ == "__main__":
    unittest.main()
