"""The MyGarage Home Assistant integration (thin widget-API client)."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import MyGarageApiClient, MyGarageApiError
from .const import CONF_API_KEY, CONF_HOST, CONF_WEBHOOK_TOKEN, DOMAIN
from .coordinator import MyGarageCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

SERVICE_LOG_FUEL = "log_fuel"
SERVICE_SET_ODOMETER = "set_odometer"
SERVICE_COMPLETE_REMINDER = "complete_reminder"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up from YAML (config entries only)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MyGarage from a config entry."""
    data = {**entry.data, **entry.options}
    client = MyGarageApiClient(
        data[CONF_HOST],
        data.get(CONF_API_KEY, ""),
        data.get(CONF_WEBHOOK_TOKEN, ""),
    )
    coordinator = MyGarageCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        stored = hass.data[DOMAIN].pop(entry.entry_id)
        await stored["client"].close()
    return unload_ok


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_LOG_FUEL):
        return

    async def _client() -> MyGarageApiClient:
        for stored in hass.data.get(DOMAIN, {}).values():
            return stored["client"]
        raise HomeAssistantError("MyGarage is not configured")

    async def handle_log_fuel(call: ServiceCall) -> None:
        client = await _client()
        try:
            await client.log_fuel(dict(call.data))
        except MyGarageApiError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_set_odometer(call: ServiceCall) -> None:
        client = await _client()
        try:
            await client.set_odometer(dict(call.data))
        except MyGarageApiError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_complete_reminder(call: ServiceCall) -> None:
        client = await _client()
        try:
            await client.complete_reminder(dict(call.data))
        except MyGarageApiError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_LOG_FUEL,
        handle_log_fuel,
        schema=vol.Schema(
            {
                vol.Required("vin"): cv.string,
                vol.Required("date"): cv.string,
                vol.Optional("odometer_km"): vol.Coerce(float),
                vol.Optional("liters"): vol.Coerce(float),
                vol.Optional("kwh"): vol.Coerce(float),
                vol.Optional("cost"): vol.Coerce(float),
                vol.Optional("price_per_unit"): vol.Coerce(float),
                vol.Optional("notes"): cv.string,
                vol.Optional("is_full_tank", default=True): cv.boolean,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ODOMETER,
        handle_set_odometer,
        schema=vol.Schema(
            {
                vol.Required("vin"): cv.string,
                vol.Required("odometer_km"): vol.Coerce(float),
                vol.Optional("date"): cv.string,
                vol.Optional("notes"): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPLETE_REMINDER,
        handle_complete_reminder,
        schema=vol.Schema(
            {
                vol.Required("vin"): cv.string,
                vol.Required("reminder_id"): cv.positive_int,
            }
        ),
    )
