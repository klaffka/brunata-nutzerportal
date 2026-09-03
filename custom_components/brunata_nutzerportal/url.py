"""Portal URL normalization and config-entry identity helpers."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_portal_url(raw_url: str, *, require_https: bool = True) -> str:
    """Return a canonical portal URL or raise ValueError."""
    parsed = urlsplit(raw_url.strip())
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Portal URL must contain only a host and optional path")
    if require_https and parsed.scheme.casefold() != "https":
        raise ValueError("Portal URL must use HTTPS")
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ValueError("Unsupported portal URL scheme")
    if parsed.query or parsed.fragment:
        raise ValueError("Portal URL must not contain a query or fragment")

    scheme = parsed.scheme.casefold()
    host = parsed.hostname.casefold()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid portal port") from exc
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port is None or (scheme == "https" and port == 443) else f"{host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def config_entry_unique_id(base_url: str, sap_client: str, username: str) -> str:
    """Build the stable account identity used to prevent duplicate entries."""
    parsed = urlsplit(normalize_portal_url(base_url, require_https=False))
    return f"{parsed.netloc.casefold()}|{sap_client.strip()}|{username.casefold()}"
