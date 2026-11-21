from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
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
        client_factory: Callable[[], Awaitable[BrunataClient]] | None = None,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name="BRUdirekt",
            config_entry=entry,
            update_interval=timedelta(hours=update_hours),
        )
        self.client = client
        self._client_factory = client_factory
        self._client_used = False

    async def _async_fresh_client(self) -> None:
        """Replace a client that already attempted a login with a new one.

        The portal rejects a second login on a client that still carries the
        previous SAP session cookies, cached CSRF tokens and basic-auth state:
        the credentials are reported as wrong although they are fine, and only
        a reload (a new client) cures it. Every login therefore gets a new
        client, so no session state leaks from one poll into the next.
        """
        if self._client_factory is None or not self._client_used:
            return
        old = self.client
        self.client = await self._client_factory()
        try:
            await old.aclose()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Failed to close the previous client", exc_info=True)

    async def _async_login(self) -> None:
        """Log in with a clean session; retry once before giving up."""
        await self._async_fresh_client()
        self._client_used = True
        try:
            await self.client.login()
        except LoginError as first:
            if self._client_factory is None:
                raise
            _LOGGER.debug("Login rejected (%s), retrying with a new session", first)
            await self._async_fresh_client()
            await self.client.login()

    async def _async_update_data(self) -> dict:
        # Login phase: any LoginError here means (re)authentication problems,
        # so map it to ConfigEntryAuthFailed and let HA trigger re-auth.
        try:
            await self._async_login()
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
