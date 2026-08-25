from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from brunata_api import BrunataClient, ReadingKind
from brunata_api.errors import LoginError

from .const import DEFAULT_UPDATE_INTERVAL_HOURS
from .debug_diag import diagnose_dashboard_batch

_LOGGER = logging.getLogger(__name__)
_DIAG_DONE = False

# LoginError texts that indicate the dashboard payload is broken rather than
# missing credentials; triggers the one-shot batch diagnostics.
_DIAG_NEEDLES = (
    "Dashboard batch response did not contain JSON data",
)


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
        hass,
        client: BrunataClient,
        update_hours: int = DEFAULT_UPDATE_INTERVAL_HOURS,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name="BRUdirekt",
            update_interval=timedelta(hours=update_hours),
        )
        self.client = client

    async def _maybe_diagnose(self, msg: str) -> None:
        global _DIAG_DONE
        if _DIAG_DONE or not any(n in msg for n in _DIAG_NEEDLES):
            return
        _DIAG_DONE = True
        try:
            diag = await diagnose_dashboard_batch(self.client)
            _LOGGER.warning("Dashboard batch diagnostics (sanitized): %s", diag)
        except Exception as diag_e:
            _LOGGER.warning("Dashboard batch diagnostics failed: %s", diag_e)

    async def _async_update_data(self) -> dict:
        # Login phase: any LoginError here means (re)authentication problems,
        # so map it to ConfigEntryAuthFailed and let HA trigger re-auth.
        try:
            await self.client.login()
        except LoginError as e:
            raise ConfigEntryAuthFailed(str(e)) from e

        data: dict = {}
        try:
            supported = await self.client.get_supported_cost_types()
        except LoginError as e:
            await self._maybe_diagnose(str(e))
            raise UpdateFailed(str(e)) from e

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
            try:
                data[f"{prefix}_ytd"] = await self.client.get_current_consumption(kind)
                data[f"{prefix}_monthly"] = await self.client.get_readings(kind)
            except Exception as e:
                _LOGGER.warning("Failed to fetch %s consumption: %s", prefix, e)
                data["errors"][prefix] = str(e)

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
                _LOGGER.debug("%s unavailable: %s", key, e)

        if not any(
            k in data
            for k in ("heating_ytd", "heating_monthly", "hotwater_ytd", "hotwater_monthly")
        ):
            first_err = next(iter(data["errors"].values()), "unknown error")
            await self._maybe_diagnose(first_err)
            raise UpdateFailed(f"No consumption data available: {first_err}") from None

        return data