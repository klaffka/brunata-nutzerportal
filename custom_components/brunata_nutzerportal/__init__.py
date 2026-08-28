from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

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

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_UPDATE_COORDINATOR = "update_coordinator"


async def async_setup(hass: HomeAssistant) -> bool:
    hass.data.setdefault(DOMAIN, {})

    async def _async_handle_update_service(call: ServiceCall) -> None:
        target_entities = call.data.get(ATTR_ENTITY_ID)

        if not target_entities:
            entry_ids = {
                entry.entry_id for entry in hass.config_entries.async_entries(DOMAIN)
            }
        else:
            entry_ids = set()
            entity_registry = er.async_get(hass)
            for entity_id in target_entities:
                registered = entity_registry.async_get(entity_id)
                if registered and registered.platform == DOMAIN:
                    entry_ids.add(registered.config_entry_id)

        for entry_id in entry_ids:
            data: dict[str, Any] | None = hass.data[DOMAIN].get(entry_id)
            if data:
                data["coordinator"].async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_COORDINATOR,
        _async_handle_update_service,
        schema=vol.Schema({}),
    )
    return True


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
