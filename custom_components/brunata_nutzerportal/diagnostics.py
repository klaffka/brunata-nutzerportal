from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_BASE_URL, CONF_PASSWORD, CONF_USERNAME
from .models import BrunataConfigEntry

_TO_REDACT = {CONF_BASE_URL, CONF_PASSWORD, CONF_USERNAME}
_CONSUMPTION_DATASETS = (
    "heating_ytd",
    "heating_monthly",
    "hotwater_ytd",
    "hotwater_monthly",
)
_OPTIONAL_DATASETS = ("meter_readings", "comparison", "forecast", "rooms")


def _object_count(key: str, value: Any) -> int:
    """Count objects without exposing their values or identifiers."""
    if key == "rooms" and isinstance(value, dict):
        return sum(len(items) for items in value.values() if isinstance(items, list))
    if isinstance(value, (dict, list, tuple, set)):
        return len(value)
    return int(value is not None)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: BrunataConfigEntry
) -> dict[str, Any]:
    """Return a local, serializable and privacy-preserving state summary."""
    coordinator = config_entry.runtime_data.coordinator
    data = coordinator.data or {}
    dataset_names = _CONSUMPTION_DATASETS + _OPTIONAL_DATASETS

    return {
        "entry_data": async_redact_data(dict(config_entry.data), _TO_REDACT),
        "options": dict(config_entry.options),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception_type": (
                type(coordinator.last_exception).__name__
                if coordinator.last_exception is not None
                else None
            ),
        },
        "data": {
            "datasets": [key for key in dataset_names if key in data],
            "cost_types": list(data.get("supported_cost_types") or []),
            "object_counts": {
                key: _object_count(key, data[key])
                for key in dataset_names
                if key in data
            },
            "errors": dict(data.get("errors") or {}),
        },
    }
