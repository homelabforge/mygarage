"""Base entity helpers for MyGarage."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MyGarageCoordinator


class MyGarageVehicleEntity(CoordinatorEntity[MyGarageCoordinator]):
    """Entity bound to a single VIN."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MyGarageCoordinator, vin: str) -> None:
        super().__init__(coordinator)
        self.vin = vin
        self._attr_unique_id = f"{vin}_{self.__class__.__name__}"

    @property
    def vehicle(self) -> dict | None:
        return self.coordinator.vehicle_by_vin(self.vin)

    @property
    def available(self) -> bool:
        return super().available and self.vehicle is not None

    @property
    def device_info(self) -> DeviceInfo:
        vehicle = self.vehicle or {}
        label = vehicle.get("label") or self.vin
        return DeviceInfo(
            identifiers={(DOMAIN, self.vin)},
            name=label,
            manufacturer=vehicle.get("make"),
            model=vehicle.get("model"),
            sw_version=str(vehicle.get("year") or ""),
        )
