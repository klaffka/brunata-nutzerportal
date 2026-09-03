from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .models import BrunataConfigEntry


def _latest(series):
    return max(series, key=lambda r: r.timestamp) if series else None


def _safe_unit(v) -> str | None:
    try:
        u = getattr(v, "unit", None)
        return str(u) if u else None
    except Exception:
        return None


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="BRUdirekt",
        manufacturer="BRUNATA-METRONA (Portal)",
        model="Nutzerportal (München)",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrunataConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors and discover datasets added by later refreshes."""
    coordinator = entry.runtime_data.coordinator
    known_unique_ids: set[str] = set()

    @callback
    def _discover_entities() -> None:
        data = coordinator.data or {}
        entities: list[SensorEntity] = []

        for prefix in ("heating", "hotwater"):
            if data.get(f"has_{prefix}") or any(
                f"{prefix}_{suffix}" in data for suffix in ("ytd", "monthly")
            ):
                entities.extend(
                    (
                        BrunataYtdSensor(coordinator, entry, f"{prefix}_ytd"),
                        BrunataLatestMonthlySensor(
                            coordinator, entry, f"{prefix}_monthly"
                        ),
                    )
                )

        for data_key, sensor_cls in (
            ("meter_readings", BrunataMeterSensor),
            ("comparison", BrunataComparisonSensor),
            ("forecast", BrunataForecastSensor),
        ):
            values = data.get(data_key) or {}
            if isinstance(values, dict):
                entities.extend(
                    sensor_cls(coordinator, entry, str(cost_type))
                    for cost_type, value in sorted(values.items())
                    if value is not None
                )

        rooms = data.get("rooms") or {}
        if isinstance(rooms, dict):
            for cost_type, room_list in rooms.items():
                if not isinstance(room_list, list):
                    continue
                for room in room_list:
                    room_id = getattr(room, "room_id", None)
                    room_name = getattr(room, "room_name", None)
                    if room_id and room_name:
                        entities.append(
                            BrunataRoomSensor(
                                coordinator,
                                entry,
                                cost_type=str(cost_type),
                                room_id=str(room_id),
                                room_name=str(room_name),
                            )
                        )

        new_entities = [
            entity
            for entity in entities
            if entity.unique_id not in known_unique_ids
        ]
        if new_entities:
            known_unique_ids.update(
                entity.unique_id for entity in new_entities if entity.unique_id is not None
            )
            async_add_entities(new_entities)

    _discover_entities()
    entry.async_on_unload(coordinator.async_add_listener(_discover_entities))


class _BrunataBase(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, key: str):
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = _device_info(entry)

    @property
    def available(self) -> bool:
        return super().available and (self._key in (self.coordinator.data or {}))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "supported_cost_types": (self.coordinator.data or {}).get(
                "supported_cost_types"
            ),
        }


class BrunataYtdSensor(_BrunataBase):
    _attr_translation_key = None
    _attr_entity_category = None

    def __init__(self, coordinator, entry: ConfigEntry, key: str):
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key

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
        base.update(
            {
                "as_of": obj.as_of.isoformat(),
                "cost_type": obj.cost_type,
                "kind": getattr(obj, "kind", None),
            }
        )
        return base


class BrunataLatestMonthlySensor(_BrunataBase):
    _attr_entity_category = None

    def __init__(self, coordinator, entry: ConfigEntry, key: str):
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key

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
        base.update(
            {
                "timestamp": last.timestamp.isoformat(),
                "kind": getattr(last, "kind", None),
                "months": [
                    {"timestamp": r.timestamp.isoformat(), "value": r.value}
                    for r in sorted(series, key=lambda r: r.timestamp)
                ],
            }
        )
        return base


class BrunataMeterSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "meter"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, cost_type: str):
        super().__init__(coordinator)
        self._ct = cost_type
        self._attr_translation_placeholders = {"ct": cost_type}
        self._attr_unique_id = f"{entry.entry_id}_meter_{cost_type}"
        self._attr_device_info = _device_info(entry)

    @property
    def _obj(self):
        return (
            (self.coordinator.data or {}).get("meter_readings") or {}
        ).get(self._ct)

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
    _attr_translation_key = "comparison"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, cost_type: str):
        super().__init__(coordinator)
        self._ct = cost_type
        self._attr_translation_placeholders = {"ct": cost_type}
        self._attr_unique_id = f"{entry.entry_id}_comparison_{cost_type}"
        self._attr_device_info = _device_info(entry)

    @property
    def _obj(self):
        return (
            (self.coordinator.data or {}).get("comparison") or {}
        ).get(self._ct)

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
    _attr_translation_key = "forecast"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, cost_type: str):
        super().__init__(coordinator)
        self._ct = cost_type
        self._attr_translation_placeholders = {"ct": cost_type}
        self._attr_unique_id = f"{entry.entry_id}_forecast_{cost_type}"
        self._attr_device_info = _device_info(entry)

    @property
    def _obj(self):
        return (
            (self.coordinator.data or {}).get("forecast") or {}
        ).get(self._ct)

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
    _attr_translation_key = "room"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        *,
        cost_type: str,
        room_id: str,
        room_name: str,
    ):
        super().__init__(coordinator)
        self._ct = cost_type
        self._room_id = room_id
        self._attr_translation_placeholders = {"ct": cost_type, "room": room_name}
        self._attr_unique_id = f"{entry.entry_id}_room_{cost_type}_{room_id}"
        self._attr_device_info = _device_info(entry)

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
