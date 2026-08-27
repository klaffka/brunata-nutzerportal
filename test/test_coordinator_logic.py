"""Logic test for BrunataCoordinator with a mocked client (no portal, no HA install).

Run:  venv/bin/python test/test_coordinator_logic.py
"""
import asyncio
import sys
import types
from datetime import datetime
from pathlib import Path

# --- stub homeassistant modules before importing the coordinator ---
ha = types.ModuleType("homeassistant")
ha_exc = types.ModuleType("homeassistant.exceptions")
ha_helpers = types.ModuleType("homeassistant.helpers")
ha_uc = types.ModuleType("homeassistant.helpers.update_coordinator")
ha_ce = types.ModuleType("homeassistant.config_entries")
ha_core = types.ModuleType("homeassistant.core")
ha_const = types.ModuleType("homeassistant.const")
ha_dr = types.ModuleType("homeassistant.helpers.device_registry")
ha_er = types.ModuleType("homeassistant.helpers.entity_registry")
vol = types.ModuleType("voluptuous")


class ConfigEntry:
    pass


class HomeAssistant:
    pass


class ServiceCall:
    pass


class _Schema:
    def __init__(self, schema=None):
        self.schema = schema


ha_const.ATTR_ENTITY_ID = "entity_id"
ha_const.ATTR_DEVICE_ID = "device_id"
ha_dr.async_get = lambda hass: None
ha_er.async_get = lambda hass: None
vol.Schema = _Schema
ha_ce.ConfigEntry = ConfigEntry
ha_core.HomeAssistant = HomeAssistant
ha_core.ServiceCall = ServiceCall
ha.config_entries = ha_ce
ha.core = ha_core
ha.const = ha_const
sys.modules["homeassistant.config_entries"] = ha_ce
sys.modules["homeassistant.core"] = ha_core
sys.modules["homeassistant.const"] = ha_const
sys.modules["homeassistant.helpers.device_registry"] = ha_dr
sys.modules["homeassistant.helpers.entity_registry"] = ha_er
sys.modules["voluptuous"] = vol


class ConfigEntryAuthFailed(Exception):
    pass


class ConfigEntryNotReady(Exception):
    pass


class UpdateFailed(Exception):
    pass


class DataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = False


ha_exc.ConfigEntryAuthFailed = ConfigEntryAuthFailed
ha_exc.ConfigEntryNotReady = ConfigEntryNotReady
ha_helpers.update_coordinator = ha_uc
ha_uc.DataUpdateCoordinator = DataUpdateCoordinator
ha_uc.UpdateFailed = UpdateFailed
ha.exceptions = ha_exc
ha.helpers = ha_helpers
sys.modules["homeassistant"] = ha
sys.modules["homeassistant.exceptions"] = ha_exc
sys.modules["homeassistant.helpers"] = ha_helpers
sys.modules["homeassistant.helpers.update_coordinator"] = ha_uc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))
import importlib

from brunata_api.errors import LoginError

mod = importlib.import_module("brunata_nutzerportal.coordinator")
mod._DIAG_DONE = False  # reset for each run


class FakeClient:
    def __init__(self, supported=None, login_exc=None, ytd_exc=None, monthly_exc=None,
                 optional_exc=None):
        self.supported = {"1": {"HZ01"}} if supported is None else supported
        self.login_exc = login_exc
        self.ytd_exc = ytd_exc
        self.monthly_exc = monthly_exc
        self.optional_exc = optional_exc
        self.sap_client = "201"

    async def login(self):
        if self.login_exc:
            raise self.login_exc

    async def get_supported_cost_types(self):
        if self.login_exc:  # reuse as "data phase failure"
            raise self.login_exc
        return self.supported

    async def get_current_consumption(self, kind):
        if self.ytd_exc:
            raise self.ytd_exc
        from brunata_api.models import CurrentConsumption
        return CurrentConsumption(
            as_of=datetime(2026, 7, 31), value=2163.0, unit="kWh",
            kind=kind, cost_type="HZ01",
        )

    async def get_readings(self, kind):
        if self.monthly_exc:
            raise self.monthly_exc
        from brunata_api.models import Reading
        return [Reading(timestamp=datetime(2026, 7, 31), value=1.0, unit="kWh", kind=kind)]

    async def get_meter_readings(self):
        if self.optional_exc:
            raise self.optional_exc
        return {}

    async def get_consumption_comparison(self):
        if self.optional_exc:
            raise self.optional_exc
        return {}

    async def get_consumption_forecast(self):
        if self.optional_exc:
            raise self.optional_exc
        return {}

    async def get_room_consumption(self):
        if self.optional_exc:
            raise self.optional_exc
        return {}


def make_coordinator(client):
    return mod.BrunataCoordinator(object(), client)


results = []


def check(name, cond, extra=""):
    results.append((name, cond, extra))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {extra}")


async def main():
    # 1. login LoginError -> ConfigEntryAuthFailed
    c = make_coordinator(
        FakeClient(login_exc=LoginError("Empty UserContextSet results (login likely failed)."))
    )
    try:
        await c._async_update_data()
        check("login LoginError -> ConfigEntryAuthFailed", False)
    except ConfigEntryAuthFailed:
        check("login LoginError -> ConfigEntryAuthFailed", True)
    except Exception as e:
        check("login LoginError -> ConfigEntryAuthFailed", False, repr(e))

    # 2. all data fetch fail -> UpdateFailed
    c = make_coordinator(FakeClient(ytd_exc=LoginError("No dashboard period found."),
                                    optional_exc=LoginError("Nope.")))
    try:
        await c._async_update_data()
        check("all data fail -> UpdateFailed", False)
    except UpdateFailed as e:
        check("all data fail -> UpdateFailed", "No dashboard period found" in str(e), str(e))
    except Exception as e:
        check("all data fail -> UpdateFailed", False, repr(e))

    # 3. partial: ytd ok, monthly fails, optional fails -> data with heating_ytd
    c = make_coordinator(FakeClient(monthly_exc=LoginError("boom"),
                                    optional_exc=LoginError("opt boom")))
    try:
        data = await c._async_update_data()
        check("partial fetch -> keeps ytd", "heating_ytd" in data and "heating_monthly" not in data,
              f"keys={sorted(data.keys())}")
    except Exception as e:
        check("partial fetch -> keeps ytd", False, repr(e))

    # 4. happy path
    c = make_coordinator(FakeClient())
    data = await c._async_update_data()
    check("happy path -> all keys",
          all(k in data for k in ("supported_cost_types", "heating_ytd", "heating_monthly",
                                  "meter_readings", "comparison", "forecast", "rooms")),
          f"keys={sorted(data.keys())}")
    check("happy path -> has_heating True / has_hotwater False",
          data["has_heating"] is True and data["has_hotwater"] is False)

    # 5. no cost types at all -> UpdateFailed
    c = make_coordinator(FakeClient(supported={}))
    try:
        await c._async_update_data()
        check("no cost types -> UpdateFailed", False)
    except UpdateFailed as e:
        check("no cost types -> UpdateFailed", True, str(e))

    # 6. hot water path
    c = make_coordinator(FakeClient(supported={"1": {"WW01"}}))
    data = await c._async_update_data()
    check("hotwater path -> hotwater keys", "hotwater_ytd" in data and data["has_hotwater"] is True)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)


asyncio.run(main())
