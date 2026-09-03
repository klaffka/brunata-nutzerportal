"""Shared runtime types for the BRUdirekt integration."""

from __future__ import annotations

from dataclasses import dataclass

from brunata_api import BrunataClient
from homeassistant.config_entries import ConfigEntry

from .coordinator import BrunataCoordinator


@dataclass(slots=True)
class BrunataRuntimeData:
    """Non-persisted objects owned by a loaded config entry."""

    client: BrunataClient
    coordinator: BrunataCoordinator


type BrunataConfigEntry = ConfigEntry[BrunataRuntimeData]
