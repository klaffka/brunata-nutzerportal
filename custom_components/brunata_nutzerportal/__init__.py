from __future__ import annotations

import logging
from typing import cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

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
from .models import BrunataConfigEntry, BrunataRuntimeData
from .url import config_entry_unique_id, normalize_portal_url

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_UPDATE_COORDINATOR = "update_coordinator"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def _async_handle_update_service(call: ServiceCall) -> None:
        entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError("BRUdirekt config entry not found")
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError("BRUdirekt config entry is not loaded")

        runtime = cast(BrunataConfigEntry, entry).runtime_data
        await runtime.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_COORDINATOR,
        _async_handle_update_service,
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}),
    )
    return True


async def _async_update_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate existing entries to the host-scoped account unique ID."""
    if entry.version > 2:
        return False
    if entry.version < 2:
        data = dict(entry.data)
        try:
            data[CONF_BASE_URL] = normalize_portal_url(
                data[CONF_BASE_URL], require_https=False
            )
            unique_id = config_entry_unique_id(
                data[CONF_BASE_URL], data[CONF_SAP_CLIENT], data[CONF_USERNAME]
            )
        except (KeyError, TypeError, ValueError):
            _LOGGER.error("Unable to migrate malformed BRUdirekt config entry")
            return False
        hass.config_entries.async_update_entry(
            entry, data=data, unique_id=unique_id, version=2
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BrunataConfigEntry) -> bool:
    client = await async_create_brunata_client(
        hass,
        base_url=entry.data[CONF_BASE_URL],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        sap_client=entry.data[CONF_SAP_CLIENT],
    )

    update_hours = entry.options.get(CONF_UPDATE_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)
    coordinator = BrunataCoordinator(hass, entry, client, update_hours=update_hours)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        await client.aclose()
        raise
    except Exception as exc:
        await client.aclose()
        raise ConfigEntryNotReady(
            f"Unable to fetch Brunata data ({type(exc).__name__})"
        ) from exc

    entry.runtime_data = BrunataRuntimeData(client=client, coordinator=coordinator)

    entry.async_on_unload(entry.add_update_listener(_async_update_entry))

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await client.aclose()
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: BrunataConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        await entry.runtime_data.client.aclose()

    return unload_ok
