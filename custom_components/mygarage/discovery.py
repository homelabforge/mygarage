"""Discover vehicles as they appear in coordinator data."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MyGarageCoordinator


def async_listen_new_vehicles(
    entry: ConfigEntry,
    coordinator: MyGarageCoordinator,
    async_add_entities: AddEntitiesCallback,
    build: Callable[[dict], list],
) -> None:
    """Add entities for each VIN the first time it appears."""
    known: set[str] = set()

    @callback
    def _check() -> None:
        new_entities = []
        for vehicle in coordinator.async_vehicles():
            vin = vehicle.get("vin")
            if not vin or vin in known:
                continue
            known.add(vin)
            new_entities.extend(build(vehicle))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_check))
    _check()
