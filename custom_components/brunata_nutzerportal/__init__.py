from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .client_factory import async_create_brunata_client
from .const import (
    CONF_BASE_URL,
    CONF_PASSWORD,
    CONF_SAP_CLIENT,
    CONF_UPDATE_HOURS,
    CONF_USERNAME,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
)
from .coordinator import BrunataCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


async def _async_update_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = await async_create_brunata_client(
        hass,
        base_url=entry.data[CONF_BASE_URL],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        sap_client=entry.data[CONF_SAP_CLIENT],
    )

    update_hours = entry.options.get(CONF_UPDATE_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)
    coordinator = BrunataCoordinator(hass, client, update_hours=update_hours)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        await client.aclose()
        raise
    except Exception as exc:
        await client.aclose()
        raise ConfigEntryNotReady(f"Unable to fetch Brunata data: {exc}") from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    entry.async_on_unload(entry.add_update_listener(_async_update_entry))

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        await client.aclose()
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, {})
        client = data.get("client")
        if client:
            await client.aclose()

    return unload_ok
