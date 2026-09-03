"""Standalone probe for the BRUdirekt SAP OData login flow."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin, urlparse

import dotenv
import requests

BASE = "https://nutzerportal.brunata-muenchen.de"
SAP_CLIENT = "201"
REQUEST_TIMEOUT = (10, 30)


def _logon_root(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/sap/opu/odata/bme/NP_REG_LOGON_SRV_01/"


def fetch_csrf(
    session: requests.Session,
    *,
    base_url: str = BASE,
    sap_client: str = SAP_CLIENT,
) -> str | None:
    """Fetch a CSRF token and establish the SAP session cookies."""
    response = session.head(
        f"{_logon_root(base_url)}?sap-client={sap_client}",
        headers={
            "Accept": "application/json",
            "x-csrf-token": "Fetch",
            "X-Requested-With": "XMLHttpRequest",
            "sap-contextid-accept": "header",
        },
        allow_redirects=False,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"Unexpected CSRF status {response.status_code}")
    return response.headers.get("x-csrf-token")


def build_batch_body(
    email: str, password_plain: str, sap_client: str
) -> tuple[str, str]:
    """Build the CRLF-sensitive SAP credential changeset."""
    batch_boundary = f"batch_{uuid.uuid4().hex}"
    changeset_boundary = f"changeset_{uuid.uuid4().hex}"
    pw_b64 = base64.b64encode(password_plain.encode()).decode("ascii")
    payload = {"Action": "validLCR", "Email": email, "Password": pw_b64}
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_len = len(payload_json.encode())

    crlf = "\r\n"
    body = (
        f"--{batch_boundary}{crlf}"
        f"Content-Type: multipart/mixed; boundary={changeset_boundary}{crlf}{crlf}"
        f"--{changeset_boundary}{crlf}"
        f"Content-Type: application/http{crlf}"
        f"Content-Transfer-Encoding: binary{crlf}{crlf}"
        f"POST CredentialSet?sap-client={sap_client} HTTP/1.1{crlf}"
        f"X-Requested-With: XMLHttpRequest{crlf}"
        f"sap-contextid-accept: header{crlf}"
        f"Accept: application/json{crlf}"
        f"Accept-Language: de{crlf}"
        f"DataServiceVersion: 2.0{crlf}"
        f"MaxDataServiceVersion: 2.0{crlf}"
        f"Content-Type: application/json{crlf}"
        f"Content-ID: 1{crlf}"
        f"Content-Length: {payload_len}{crlf}{crlf}"
        f"{payload_json}{crlf}"
        f"--{changeset_boundary}--{crlf}{crlf}"
        f"--{batch_boundary}--{crlf}"
    )
    return body, f"multipart/mixed; boundary={batch_boundary}"


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract independent JSON objects embedded in a multipart response."""
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    position = 0
    while (start := text.find("{", position)) >= 0:
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            position = start + 1
            continue
        if isinstance(value, dict):
            objects.append(value)
        position = end
    return objects


def extract_first_json(text: str) -> dict[str, Any]:
    objects = extract_json_objects(text)
    if not objects:
        raise RuntimeError("Batch response did not contain JSON data")
    return objects[0]


def extract_inner_http_statuses(text: str) -> list[int]:
    """Return HTTP status codes from application/http multipart sections."""
    return [
        int(match.group("code"))
        for match in re.finditer(
            r"HTTP/(?:1\.[01]|2)\s+(?P<code>\d{3})(?:\s|\r|\n)", text
        )
    ]


def normalize_service_url(raw: str, *, base_url: str = BASE) -> str:
    """Resolve a service URL returned by SAP."""
    if not raw or not raw.strip():
        return ""
    return urljoin(f"{base_url.rstrip('/')}/", raw.strip())


def safe_service_url(raw: str, *, base_url: str = BASE) -> str:
    """Allow Basic Auth only on HTTPS URLs belonging to the portal host."""
    resolved = normalize_service_url(raw, base_url=base_url)
    service = urlparse(resolved)
    portal = urlparse(base_url)
    if (
        service.scheme.casefold() != "https"
        or not service.hostname
        or service.hostname.casefold() != (portal.hostname or "").casefold()
    ):
        raise RuntimeError("Portal returned an unsafe service URL")
    return resolved


def _login_payloads(objects: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for value in objects:
        payload = value.get("d")
        if isinstance(payload, dict):
            yield payload


def run_probe(
    email: str,
    password: str,
    *,
    base_url: str = BASE,
    sap_client: str = SAP_CLIENT,
) -> None:
    """Perform the login probe without exposing credentials or response bodies."""
    portal = urlparse(base_url)
    if portal.scheme.casefold() != "https" or not portal.hostname:
        raise RuntimeError("Portal base URL must use HTTPS")

    logon_root = _logon_root(base_url)
    batch_url = f"{logon_root}$batch?sap-client={sap_client}"

    with requests.Session() as session:
        session.headers.update(
            {"User-Agent": "Mozilla/5.0", "Accept-Language": "de"}
        )
        session.cookies.set(
            "sap-usercontext", f"sap-client={sap_client}", domain=portal.hostname
        )
        landing = session.get(
            f"{base_url.rstrip('/')}/np_anmeldung/index.html?sap-language=DE",
            timeout=REQUEST_TIMEOUT,
        )
        landing.raise_for_status()
        csrf = fetch_csrf(session, base_url=base_url, sap_client=sap_client)
        body, content_type = build_batch_body(email, password, sap_client)

        headers = {
            "Accept": "multipart/mixed",
            "Content-Type": content_type,
            "X-Requested-With": "XMLHttpRequest",
            "sap-contextid-accept": "header",
            "Referer": (
                f"{base_url.rstrip('/')}/np_anmeldung/"
                "index.html?sap-language=DE"
            ),
            "Origin": base_url.rstrip("/"),
        }
        if csrf:
            headers["x-csrf-token"] = csrf

        response = session.post(
            batch_url,
            headers=headers,
            data=body.encode(),
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        response.raise_for_status()
        if response.status_code not in (200, 202):
            raise RuntimeError(f"Unexpected batch status {response.status_code}")

        statuses = extract_inner_http_statuses(response.text)
        if not statuses:
            raise RuntimeError("Batch response did not contain an inner HTTP status")
        if any(status < 200 or status >= 300 for status in statuses):
            raise RuntimeError("Credential request was rejected")

        payload = next(
            (
                item
                for item in _login_payloads(extract_json_objects(response.text))
                if item.get("Userid") and item.get("Password")
            ),
            None,
        )
        if payload is None:
            raise RuntimeError("Login response did not contain credentials")

        try:
            sap_password = base64.b64decode(
                payload["Password"], validate=True
            ).decode(errors="strict")
        except (binascii.Error, UnicodeDecodeError, TypeError) as exc:
            raise RuntimeError("Login response contained invalid credentials") from exc

        service_url = safe_service_url(
            str(payload.get("Serviceurl") or ""), base_url=base_url
        )
        finalized = session.get(
            service_url,
            auth=(str(payload["Userid"]), sap_password),
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        finalized.raise_for_status()
        if not 200 <= finalized.status_code < 300:
            raise RuntimeError(f"Unexpected service status {finalized.status_code}")

    print("SAP login probe succeeded")


def main() -> None:
    """Load local credentials and execute the standalone probe."""
    dotenv.load_dotenv()
    email = os.getenv("BRU_EMAIL")
    password = os.getenv("BRU_PASSWORD")
    if not email or not password:
        raise RuntimeError("BRU_EMAIL and BRU_PASSWORD must be set")
    run_probe(email, password)


if __name__ == "__main__":
    main()
