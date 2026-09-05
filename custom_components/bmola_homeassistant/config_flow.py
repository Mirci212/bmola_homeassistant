"""Config flow for Bmola Home Assistant integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

DOMAIN = "bmola_homeassistant"
_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required("user_name"): str,
        vol.Required("device_id"): str,
        vol.Optional("password", default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class BmolaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bmola Luftreiniger."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_name = str(user_input["user_name"]).strip()
            device_id = str(user_input["device_id"]).strip()
            password = str(user_input.get("password", "")).strip()

            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Bmola ({device_id})",
                data={
                    "user_name": user_name,
                    "device_id": device_id,
                    "password": password,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow handler."""
        return BmolaOptionsFlowHandler(config_entry)


class BmolaOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Bmola Luftreiniger."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data={**self._config_entry.data, **user_input},
            )
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    "user_name",
                    default=self._config_entry.data.get("user_name", ""),
                ): str,
                vol.Required(
                    "device_id",
                    default=self._config_entry.data.get("device_id", ""),
                ): str,
                vol.Optional(
                    "password",
                    default=self._config_entry.data.get("password", ""),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )