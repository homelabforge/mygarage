"""Sensor platform for MyGarage."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
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

    def _build(item: dict) -> list[SensorEntity]:
        vin = item["vin"]
        return [
            MyGarageOdometerSensor(coordinator, vin),
            MyGarageFuelEconomySensor(coordinator, vin),
            MyGarageOverdueSensor(coordinator, vin),
            MyGarageUpcomingSensor(coordinator, vin),
            MyGarageLastFuelSensor(coordinator, vin),
            MyGarageHoursSensor(coordinator, vin),
        ]

    async_listen_new_vehicles(entry, coordinator, async_add_entities, _build)


class MyGarageOdometerSensor(MyGarageVehicleEntity, SensorEntity):
    _attr_translation_key = "odometer"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS

    @property
    def native_value(self):
        vehicle = self.vehicle or {}
        return vehicle.get("odometer_km") if vehicle.get("odometer_km") is not None else vehicle.get("odometer")


class MyGarageFuelEconomySensor(MyGarageVehicleEntity, SensorEntity):
    _attr_translation_key = "fuel_economy"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "L/100km"

    @property
    def native_value(self):
        vehicle = self.vehicle or {}
        return vehicle.get("average_l_per_100km") or vehicle.get("recent_l_per_100km")


class MyGarageOverdueSensor(MyGarageVehicleEntity, SensorEntity):
    _attr_translation_key = "overdue_maintenance"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return (self.vehicle or {}).get("overdue_maintenance", 0)


class MyGarageUpcomingSensor(MyGarageVehicleEntity, SensorEntity):
    _attr_translation_key = "upcoming_maintenance"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return (self.vehicle or {}).get("upcoming_maintenance", 0)


class MyGarageLastFuelSensor(MyGarageVehicleEntity, SensorEntity):
    _attr_translation_key = "last_fuel_date"
    _attr_device_class = SensorDeviceClass.DATE

    @property
    def native_value(self):
        raw = (self.vehicle or {}).get("last_fuel_date")
        if not raw:
            return None
        from datetime import date

        if isinstance(raw, date):
            return raw
        return date.fromisoformat(str(raw)[:10])


class MyGarageHoursSensor(MyGarageVehicleEntity, SensorEntity):
    _attr_translation_key = "engine_hours"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "h"

    @property
    def native_value(self):
        return (self.vehicle or {}).get("latest_hours")
