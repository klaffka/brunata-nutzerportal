from __future__ import annotations

import logging
from datetime import timedelta

from brunata_api import BrunataClient, ReadingKind
from brunata_api.errors import LoginError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_UPDATE_INTERVAL_HOURS

_LOGGER = logging.getLogger(__name__)


def _flatten_supported(supported: dict) -> set[str]:
    out: set[str] = set()
    if isinstance(supported, dict):
        for v in supported.values():
            if isinstance(v, (set, list, tuple)):
                for ct in v:
                    if isinstance(ct, str):
                        out.add(ct)
    return out


class BrunataCoordinator(DataUpdateCoordinator[dict]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: BrunataClient,
        update_hours: int = DEFAULT_UPDATE_INTERVAL_HOURS,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name="BRUdirekt",
            config_entry=entry,
            update_interval=timedelta(hours=update_hours),
        )
        self.client = client

    async def _async_update_data(self) -> dict:
        # Login phase: any LoginError here means (re)authentication problems,
        # so map it to ConfigEntryAuthFailed and let HA trigger re-auth.
        try:
            await self.client.login()
        except LoginError as e:
            raise ConfigEntryAuthFailed("Portal rejected the stored credentials") from e
        except Exception as e:
            raise UpdateFailed(f"Unable to log in ({type(e).__name__})") from e

        data: dict = {}
        try:
            supported = await self.client.get_supported_cost_types()
        except Exception as e:
            raise UpdateFailed(
                f"Unable to determine supported cost types ({type(e).__name__})"
            ) from e

        all_types = _flatten_supported(supported)
        has_heating = any(ct.startswith("HZ") for ct in all_types)
        has_hotwater = any(ct.startswith("WW") for ct in all_types)

        data["supported_cost_types"] = sorted(all_types)
        data["has_heating"] = has_heating
        data["has_hotwater"] = has_hotwater
        data["errors"] = {}

        core_datasets: list[tuple[ReadingKind, bool, str]] = [
            (ReadingKind.heating, has_heating, "heating"),
            (ReadingKind.hot_water, has_hotwater, "hotwater"),
        ]

        for kind, enabled, prefix in core_datasets:
            if not enabled:
                continue
            for suffix, fetch in (
                ("ytd", self.client.get_current_consumption),
                ("monthly", self.client.get_readings),
            ):
                key = f"{prefix}_{suffix}"
                try:
                    data[key] = await fetch(kind)
                except Exception as e:
                    _LOGGER.warning(
                        "Failed to fetch %s data (%s)", key, type(e).__name__
                    )
                    data["errors"][key] = type(e).__name__

        # Optional datasets (best-effort)
        for key, fetch in (
            ("meter_readings", self.client.get_meter_readings),
            ("comparison", self.client.get_consumption_comparison),
            ("forecast", self.client.get_consumption_forecast),
            ("rooms", self.client.get_room_consumption),
        ):
            try:
                data[key] = await fetch()
            except Exception as e:
                _LOGGER.debug("%s unavailable (%s)", key, type(e).__name__)
                data["errors"][key] = type(e).__name__

        if not any(
            k in data
            for k in ("heating_ytd", "heating_monthly", "hotwater_ytd", "hotwater_monthly")
        ):
            error_types = sorted(set(data["errors"].values()))
            detail = ", ".join(error_types) if error_types else "no supported dataset"
            raise UpdateFailed(f"No consumption data available ({detail})")

        return data
