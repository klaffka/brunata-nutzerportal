from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.diagnostics import redact
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD, DOMAIN
from .debug_diag import diagnose_dashboard_batch

_LOGGER = logging.getLogger(__name__)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    data = hass.data[DOMAIN].get(config_entry.entry_id, {})
    coordinator = data.get("coordinator")

    diag: dict[str, Any] = {
        "entry": redact(config_entry, {CONF_PASSWORD}),
        "options": dict(config_entry.options),
    }

    if coordinator is not None:
        diag["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "last_update": coordinator.last_update.isoformat()
            if coordinator.last_update
            else None,
        }
        if coordinator.data:
            diag["data"] = coordinator.data

    client = data.get("client")
    if client is not None:
        try:
            diag["dashboard_batch"] = await diagnose_dashboard_batch(client)
        except Exception as exc:  # noqa: BLE001 - diagnostics must not fail the export
            diag["dashboard_batch"] = f"unavailable: {exc}"

    return diag
