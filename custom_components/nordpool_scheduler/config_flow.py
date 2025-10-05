"""Config flow for Nordpool Scheduler integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEFAULT_STATE,
    CONF_SCHEDULER_NAME,
    CONF_TARGET_SWITCH,
    DEFAULT_STATE_OFF,
    DEFAULT_STATE_ON,
    DOMAIN,
    SUPPORTED_DOMAINS,
)

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided
    by the user.
    """
    # Validate that the target entity exists
    target_switch = data[CONF_TARGET_SWITCH]

    if not hass.states.get(target_switch):
        msg = "Target entity does not exist"
        raise ValueError(msg)

    # Return info that you want to store in the config entry.
    return {
        "title": f"Nordpool Scheduler - {data[CONF_SCHEDULER_NAME]}",
        CONF_SCHEDULER_NAME: data[CONF_SCHEDULER_NAME],
        CONF_TARGET_SWITCH: target_switch,
        CONF_DEFAULT_STATE: data.get(CONF_DEFAULT_STATE, DEFAULT_STATE_OFF),
    }


class NordpoolSchedulerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nordpool Scheduler."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except ValueError:
                errors["base"] = "invalid_switch"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Check if a config entry with the same name already exists
                await self.async_set_unique_id(
                    f"{user_input[CONF_SCHEDULER_NAME]}_{user_input[CONF_TARGET_SWITCH]}",
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=info["title"],
                    data={
                        CONF_SCHEDULER_NAME: user_input[CONF_SCHEDULER_NAME],
                        CONF_TARGET_SWITCH: user_input[CONF_TARGET_SWITCH],
                        CONF_DEFAULT_STATE: user_input.get(
                            CONF_DEFAULT_STATE,
                            DEFAULT_STATE_OFF,
                        ),
                    },
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SCHEDULER_NAME): str,
                vol.Required(CONF_TARGET_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=SUPPORTED_DOMAINS),
                ),
                vol.Required(
                    CONF_DEFAULT_STATE,
                    default=DEFAULT_STATE_OFF,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=DEFAULT_STATE_OFF,
                                label="Default OFF",
                            ),
                            selector.SelectOptionDict(
                                value=DEFAULT_STATE_ON,
                                label="Default ON",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                ),
            },
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> NordpoolSchedulerOptionsFlowHandler:
        """Get the options flow for this handler."""
        return NordpoolSchedulerOptionsFlowHandler(config_entry)


class NordpoolSchedulerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Nordpool Scheduler."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_TARGET_SWITCH,
                    default=self.config_entry.data.get(CONF_TARGET_SWITCH),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=SUPPORTED_DOMAINS),
                ),
                vol.Required(
                    CONF_DEFAULT_STATE,
                    default=self.config_entry.data.get(
                        CONF_DEFAULT_STATE,
                        DEFAULT_STATE_OFF,
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=DEFAULT_STATE_OFF,
                                label="Default OFF",
                            ),
                            selector.SelectOptionDict(
                                value=DEFAULT_STATE_ON,
                                label="Default ON",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    ),
                ),
            },
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
