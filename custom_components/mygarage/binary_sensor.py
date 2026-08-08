"""Binary sensor platform for MyGarage."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MyGarageCoordinator
from .discovery import async_listen_new_vehicles
from .entity import MyGarageVehicleEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    stored = hass.data[DOMAIN][entry.entry_id]
    coordinator: MyGarageCoordinator = stored["coordinator"]

    def _build(item: dict) -> list[BinarySensorEntity]:
        return [MyGarageMaintenanceDueBinarySensor(coordinator, item["vin"])]

    async_listen_new_vehicles(entry, coordinator, async_add_entities, _build)


class MyGarageMaintenanceDueBinarySensor(MyGarageVehicleEntity, BinarySensorEntity):
    _attr_translation_key = "maintenance_due"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        return int((self.vehicle or {}).get("overdue_maintenance") or 0) > 0
