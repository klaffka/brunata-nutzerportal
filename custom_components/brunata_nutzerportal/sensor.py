from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.sensor.const import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


def _latest(series):
    return max(series, key=lambda r: r.timestamp) if series else None


def _safe_unit(v) -> str | None:
    try:
        u = getattr(v, "unit", None)
        return str(u) if u else None
    except Exception:
        return None


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    data = coordinator.data or {}

    has_heating = bool(data.get("has_heating", False))
    has_hotwater = bool(data.get("has_hotwater", False))

    entities: list[SensorEntity] = []

    # Basic
    if has_heating:
        entities += [
            BrunataYtdSensor(coordinator, entry, "Heizung (YTD)", "heating_ytd"),
            BrunataLatestMonthlySensor(
                coordinator, entry, "Heizung (letzter Monat)", "heating_monthly"
            ),
        ]
    if has_hotwater:
        entities += [
            BrunataYtdSensor(coordinator, entry, "Warmwasser (YTD)", "hotwater_ytd"),
            BrunataLatestMonthlySensor(
                coordinator, entry, "Warmwasser (letzter Monat)", "hotwater_monthly"
            ),
        ]

    # Meter readings: one per cost_type
    meter = data.get("meter_readings") or {}
    if isinstance(meter, dict):
        for ct in sorted(meter.keys()):
            v = meter.get(ct)
            if v is None:
                continue
            entities.append(BrunataMeterSensor(coordinator, entry, f"Zählerstand {ct}", ct))

    # Comparison: state = your_value
    comp = data.get("comparison") or {}
    if isinstance(comp, dict):
        for ct in sorted(comp.keys()):
            entities.append(BrunataComparisonSensor(coordinator, entry, f"Vergleich {ct}", ct))

    # Forecast: state = forecast
    fc = data.get("forecast") or {}
    if isinstance(fc, dict):
        for ct in sorted(fc.keys()):
            entities.append(BrunataForecastSensor(coordinator, entry, f"Prognose {ct}", ct))

    # Rooms: one per (cost_type, room_id)
    rooms = data.get("rooms") or {}
    if isinstance(rooms, dict):
        for ct, lst in rooms.items():
            if not isinstance(lst, list):
                continue
            for r in lst:
                room_id = getattr(r, "room_id", None)
                room_name = getattr(r, "room_name", None)
                if not room_id or not room_name:
                    continue
                entities.append(
                    BrunataRoomSensor(
                        coordinator,
                        entry,
                        name=f"Raum {room_name} ({ct})",
                        cost_type=str(ct),
                        room_id=str(room_id),
                    )
                )

    async_add_entities(entities)


class _BrunataBase(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, name: str, key: str):
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="BRUdirekt",
            manufacturer="BRUNATA-METRONA (Portal)",
            model="Nutzerportal (München)",
        )

    @property
    def available(self) -> bool:
        return super().available and (self._key in (self.coordinator.data or {}))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "supported_cost_types": (self.coordinator.data or {}).get("supported_cost_types"),
        }


class BrunataYtdSensor(_BrunataBase):
    _attr_entity_category = None
    @property
    def native_value(self):
        obj = (self.coordinator.data or {}).get(self._key)
        return None if obj is None else obj.value

    @property
    def native_unit_of_measurement(self):
        obj = (self.coordinator.data or {}).get(self._key)
        u = _safe_unit(obj)
        return u or "kWh"

    @property
    def state_class(self) -> SensorStateClass | None:
        return SensorStateClass.TOTAL

    @property
    def device_class(self) -> SensorDeviceClass | None:
        u = _safe_unit((self.coordinator.data or {}).get(self._key))
        if u == "kWh":
            return SensorDeviceClass.ENERGY
        if u == "m³":
            return SensorDeviceClass.VOLUME
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        base = super().extra_state_attributes
        obj = (self.coordinator.data or {}).get(self._key)
        if obj is None:
            return base
        base.update({
            "as_of": obj.as_of.isoformat(),
            "cost_type": obj.cost_type,
            "kind": getattr(obj, "kind", None),
        })
        return base


class BrunataLatestMonthlySensor(_BrunataBase):
    _attr_entity_category = None
    @property
    def native_value(self):
        series = (self.coordinator.data or {}).get(self._key) or []
        last = _latest(series)
        return None if last is None else last.value

    @property
    def native_unit_of_measurement(self):
        series = (self.coordinator.data or {}).get(self._key) or []
        last = _latest(series)
        u = _safe_unit(last)
        return u or "kWh"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        base = super().extra_state_attributes
        series = (self.coordinator.data or {}).get(self._key) or []
        last = _latest(series)
        if last is None:
            return base
        base.update({
            "timestamp": last.timestamp.isoformat(),
            "kind": getattr(last, "kind", None),
            "months": [
                {"timestamp": r.timestamp.isoformat(), "value": r.value}
                for r in sorted(series, key=lambda r: r.timestamp)
            ],
        })
        return base


class BrunataMeterSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, name: str, cost_type: str):
        super().__init__(coordinator)
        self._ct = cost_type
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_meter_{cost_type}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="BRUdirekt",
            manufacturer="BRUNATA-METRONA (Portal)",
            model="Nutzerportal (München)",
        )

    @property
    def _obj(self):
        return ((self.coordinator.data or {}).get("meter_readings") or {}).get(self._ct)

    @property
    def available(self) -> bool:
        return super().available and self._obj is not None

    @property
    def native_value(self):
        o = self._obj
        return None if o is None else o.value

    @property
    def native_unit_of_measurement(self):
        o = self._obj
        return _safe_unit(o)

    @property
    def state_class(self) -> SensorStateClass | None:
        return SensorStateClass.TOTAL_INCREASING

    @property
    def device_class(self) -> SensorDeviceClass | None:
        u = _safe_unit(self._obj)
        if u == "kWh":
            return SensorDeviceClass.ENERGY
        if u == "m³":
            return SensorDeviceClass.VOLUME
        return None

    @property
    def extra_state_attributes(self):
        o = self._obj
        if o is None:
            return {}
        return {
            "timestamp": o.timestamp.isoformat(),
            "cost_type": o.cost_type,
            "kind": getattr(o, "kind", None),
        }


class BrunataComparisonSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, name: str, cost_type: str):
        super().__init__(coordinator)
        self._ct = cost_type
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_comparison_{cost_type}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="BRUdirekt",
            manufacturer="BRUNATA-METRONA (Portal)",
            model="Nutzerportal (München)",
        )

    @property
    def _obj(self):
        return ((self.coordinator.data or {}).get("comparison") or {}).get(self._ct)

    @property
    def available(self) -> bool:
        return super().available and self._obj is not None

    @property
    def native_value(self):
        o = self._obj
        return None if o is None else o.your_value

    @property
    def native_unit_of_measurement(self):
        o = self._obj
        return _safe_unit(o)

    @property
    def extra_state_attributes(self):
        o = self._obj
        if o is None:
            return {}
        return {
            "building_average": o.building_average,
            "national_average": o.national_average,
            "cost_type": o.cost_type,
            "kind": getattr(o, "kind", None),
        }


class BrunataForecastSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, name: str, cost_type: str):
        super().__init__(coordinator)
        self._ct = cost_type
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_forecast_{cost_type}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="BRUdirekt",
            manufacturer="BRUNATA-METRONA (Portal)",
            model="Nutzerportal (München)",
        )

    @property
    def _obj(self):
        return ((self.coordinator.data or {}).get("forecast") or {}).get(self._ct)

    @property
    def available(self) -> bool:
        return super().available and self._obj is not None

    @property
    def native_value(self):
        o = self._obj
        return None if o is None else o.forecast

    @property
    def native_unit_of_measurement(self):
        o = self._obj
        return _safe_unit(o)

    @property
    def extra_state_attributes(self):
        o = self._obj
        if o is None:
            return {}
        return {
            "current": o.current,
            "previous_year": o.previous_year,
            "difference": o.difference,
            "cost_type": o.cost_type,
            "kind": getattr(o, "kind", None),
        }


class BrunataRoomSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, *, name: str, cost_type: str, room_id: str):
        super().__init__(coordinator)
        self._ct = cost_type
        self._room_id = room_id
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_room_{cost_type}_{room_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="BRUdirekt",
            manufacturer="BRUNATA-METRONA (Portal)",
            model="Nutzerportal (München)",
        )

    @property
    def _obj(self):
        rooms = (self.coordinator.data or {}).get("rooms") or {}
        lst = rooms.get(self._ct) if isinstance(rooms, dict) else None
        if not isinstance(lst, list):
            return None
        for r in lst:
            if getattr(r, "room_id", None) == self._room_id:
                return r
        return None

    @property
    def available(self) -> bool:
        return super().available and self._obj is not None

    @property
    def native_value(self):
        o = self._obj
        return None if o is None else o.value

    @property
    def native_unit_of_measurement(self):
        o = self._obj
        return _safe_unit(o)

    @property
    def extra_state_attributes(self):
        o = self._obj
        if o is None:
            return {}
        return {
            "share_percent": o.share_percent,
            "room_id": o.room_id,
            "room_name": o.room_name,
            "cost_type": o.cost_type,
            "kind": getattr(o, "kind", None),
        }
