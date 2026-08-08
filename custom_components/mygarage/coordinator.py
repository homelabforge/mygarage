"""DataUpdateCoordinator for MyGarage widget polling."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MyGarageApiClient, MyGarageApiError
from .const import (
    ATTR_OVERDUE,
    ATTR_UPCOMING,
    ATTR_VEHICLE_NAME,
    ATTR_VIN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_DUE_SOON,
    EVENT_OVERDUE,
)

_LOGGER = logging.getLogger(__name__)


class MyGarageCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll widget summary + per-vehicle rollups; emit due events."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: MyGarageApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        self.client = client
        self._prev_overdue: dict[str, int] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            summary = await self.client.summary()
            vehicle_list = await self.client.list_vehicles()
            vehicles: list[dict[str, Any]] = []
            for ref in vehicle_list.get("vehicles", []):
                vin = ref.get("vin")
                if not vin:
                    continue
                detail = await self.client.vehicle(vin)
                detail["vin"] = vin
                detail.setdefault("label", ref.get("label") or vin)
                vehicles.append(detail)
        except MyGarageApiError as err:
            raise UpdateFailed(str(err)) from err

        data = {"summary": summary, "vehicles": vehicles}
        self._emit_transitions(vehicles)
        return data

    def _emit_transitions(self, vehicles: list[dict[str, Any]]) -> None:
        for vehicle in vehicles:
            vin = vehicle.get("vin")
            if not vin:
                continue
            overdue = int(vehicle.get("overdue_maintenance") or 0)
            upcoming = int(vehicle.get("upcoming_maintenance") or 0)
            prev = self._prev_overdue.get(vin)
            self._prev_overdue[vin] = overdue
            if prev is None:
                continue
            event_data = {
                ATTR_VIN: vin,
                ATTR_VEHICLE_NAME: vehicle.get("label") or vin,
                ATTR_OVERDUE: overdue,
                ATTR_UPCOMING: upcoming,
            }
            if overdue > prev:
                self.hass.bus.async_fire(EVENT_OVERDUE, event_data)
            elif upcoming > 0 and prev == 0 and overdue == 0:
                self.hass.bus.async_fire(EVENT_DUE_SOON, event_data)

    def vehicle_by_vin(self, vin: str) -> dict[str, Any] | None:
        if not self.data:
            return None
        for item in self.data.get("vehicles", []):
            if item.get("vin") == vin:
                return item
        return None

    @callback
    def async_vehicles(self) -> list[dict[str, Any]]:
        if not self.data:
            return []
        return list(self.data.get("vehicles", []))
