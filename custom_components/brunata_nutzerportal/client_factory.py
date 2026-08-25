from __future__ import annotations

from functools import partial

from homeassistant.core import HomeAssistant

from brunata_api import BrunataClient


async def async_create_brunata_client(
    hass: HomeAssistant,
    *,
    base_url: str,
    username: str,
    password: str,
    sap_client: str,
) -> BrunataClient:
    factory = partial(
        BrunataClient,
        base_url=base_url,
        username=username,
        password=password,
        sap_client=sap_client,
    )
    client: BrunataClient = await hass.async_add_executor_job(factory)

    # SAP "sap-usercontext" cookie is typically present in browser calls.
    try:
        client._client.cookies.set("sap-usercontext", f"sap-client={sap_client}")  # type: ignore[attr-defined]
    except Exception:
        pass

    # Avoid servers negotiating zstd unexpectedly; keep it simple.
    try:
        client._client.headers["Accept-Encoding"] = "gzip, deflate, br"  # type: ignore[attr-defined]
    except Exception:
        pass

    return client
