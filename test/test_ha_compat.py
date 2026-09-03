"""Compatibility regressions that run with the CI-pinned Home Assistant."""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace

from custom_components.brunata_nutzerportal.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.brunata_nutzerportal.sensor import async_setup_entry


class HomeAssistantCompatibilityTests(unittest.TestCase):
    def test_diagnostics_are_serializable_and_private(self) -> None:
        coordinator = SimpleNamespace(
            data={
                "supported_cost_types": ["HZ01"],
                "heating_ytd": SimpleNamespace(
                    value="PRIVATE-CONSUMPTION", name="PRIVATE-NAME"
                ),
                "rooms": {
                    "HZ01": [
                        SimpleNamespace(
                            room_id="PRIVATE-ID",
                            room_name="PRIVATE-ROOM",
                            value="PRIVATE-ROOM-VALUE",
                        )
                    ]
                },
                "errors": {"forecast": "LoginError"},
            },
            last_update_success=False,
            last_exception=RuntimeError("PRIVATE-RESPONSE"),
        )
        entry = SimpleNamespace(
            data={
                "username": "PRIVATE-USERNAME",
                "password": "PRIVATE-PASSWORD",
                "base_url": "https://private.invalid",
                "sap_client": "201",
            },
            options={"update_hours": 6},
            runtime_data=SimpleNamespace(coordinator=coordinator),
        )

        result = asyncio.run(async_get_config_entry_diagnostics(None, entry))
        encoded = json.dumps(result)
        for secret in (
            "PRIVATE-CONSUMPTION",
            "PRIVATE-NAME",
            "PRIVATE-ID",
            "PRIVATE-ROOM",
            "PRIVATE-ROOM-VALUE",
            "PRIVATE-RESPONSE",
            "PRIVATE-USERNAME",
            "PRIVATE-PASSWORD",
            "private.invalid",
        ):
            self.assertNotIn(secret, encoded)
        self.assertEqual(result["data"]["object_counts"]["rooms"], 1)

    def test_late_sensor_discovery_is_deduplicated(self) -> None:
        coordinator = SimpleNamespace(data={"has_heating": True})

        def add_listener(listener):
            coordinator.listener = listener
            return lambda: None

        coordinator.async_add_listener = add_listener
        added = []
        entry = SimpleNamespace(
            entry_id="entry",
            runtime_data=SimpleNamespace(coordinator=coordinator),
            async_on_unload=lambda unsubscribe: None,
        )
        asyncio.run(async_setup_entry(None, entry, added.extend))
        self.assertEqual(len(added), 2)

        coordinator.data = {
            "has_heating": True,
            "has_hotwater": True,
            "meter_readings": {"HZ01": SimpleNamespace()},
            "comparison": {"HZ01": SimpleNamespace()},
            "forecast": {"HZ01": SimpleNamespace()},
            "rooms": {
                "HZ01": [SimpleNamespace(room_id="room-1", room_name="Room")]
            },
        }
        coordinator.listener()
        self.assertEqual(len(added), 8)
        coordinator.listener()
        self.assertEqual(len(added), 8)


if __name__ == "__main__":
    unittest.main()
