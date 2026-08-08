"""Config flow for MyGarage."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .api import MyGarageApiClient, MyGarageApiError
from .const import CONF_API_KEY, CONF_HOST, CONF_WEBHOOK_TOKEN, DEFAULT_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_API_KEY): str,
        vol.Optional(CONF_WEBHOOK_TOKEN, default=""): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate host + widget API key connectivity."""
    client = MyGarageApiClient(
        data[CONF_HOST],
        data.get(CONF_API_KEY, ""),
        data.get(CONF_WEBHOOK_TOKEN, ""),
    )
    try:
        health = await client.health()
        summary = await client.summary()
    finally:
        await client.close()
    return {
        "title": f"MyGarage ({health.get('version', 'ok')})",
        "vehicles": summary.get("active_vehicles", 0),
    }


class MyGarageConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MyGarage."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST].rstrip("/"))
            self._abort_if_unique_id_configured()
            try:
                info = await validate_input(self.hass, user_input)
            except MyGarageApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return MyGarageOptionsFlow()


class MyGarageOptionsFlow(config_entries.OptionsFlow):
    """Handle options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=data.get(CONF_HOST, DEFAULT_HOST)): str,
                vol.Required(CONF_API_KEY, default=data.get(CONF_API_KEY, "")): str,
                vol.Optional(
                    CONF_WEBHOOK_TOKEN, default=data.get(CONF_WEBHOOK_TOKEN, "")
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
