"""Config flow for Nordpool Scheduler integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AREA,
    CONF_CONTROL_MODE,
    CONF_DEFAULT_STATE,
    CONF_NORDPOOL_ENTRY_ID,
    CONF_SCHEDULER_NAME,
    CONF_TARGET_ENTITY,
    CONF_VAT_PERCENT,
    CONTROL_MODE_ENFORCE,
    CONTROL_MODE_ON_CHANGE,
    DEFAULT_VAT_PERCENT,
    DOMAIN,
    NORDPOOL_DOMAIN,
    STATE_DEFAULT_OFF,
    STATE_DEFAULT_ON,
    SUPPORTED_DOMAINS,
)
from .util import is_prices_only

_LOGGER = logging.getLogger(__name__)

_DEFAULT_STATE_OPTIONS = [
    selector.SelectOptionDict(value=STATE_DEFAULT_OFF, label="Default OFF"),
    selector.SelectOptionDict(value=STATE_DEFAULT_ON, label="Default ON"),
]

_CONTROL_MODE_OPTIONS = [
    selector.SelectOptionDict(
        value=CONTROL_MODE_ON_CHANGE, label="Only act when the schedule changes"
    ),
    selector.SelectOptionDict(
        value=CONTROL_MODE_ENFORCE, label="Enforce every 15 minutes"
    ),
]


def _target_entity_selector() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=SUPPORTED_DOMAINS)
    )


def _default_state_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=_DEFAULT_STATE_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _nordpool_entry_selector() -> selector.ConfigEntrySelector:
    return selector.ConfigEntrySelector({"integration": NORDPOOL_DOMAIN})


def _vat_percent_validator() -> vol.All:
    return vol.All(vol.Coerce(float), vol.Range(min=0, max=100))


def _control_mode_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=_CONTROL_MODE_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


class NordpoolSchedulerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nordpool Scheduler."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._user_input: dict[str, Any] = {}

    async def async_step_user(
        self,
        _user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Ask whether to add a scheduler or a prices-only entry."""
        if not self.hass.config_entries.async_entries(NORDPOOL_DOMAIN):
            return self.async_abort(reason="nordpool_not_configured")
        return self.async_show_menu(
            step_id="user", menu_options=["scheduler", "prices"]
        )

    def _nordpool_entry_field(self) -> vol.Required:
        """Return the Nord Pool source field, preselecting the first entry.

        The frontend can't build an empty initial value for a required
        config entry selector and fails to render the form without a default.
        """
        entries = self.hass.config_entries.async_entries(NORDPOOL_DOMAIN)
        return vol.Required(CONF_NORDPOOL_ENTRY_ID, default=entries[0].entry_id)

    async def async_step_scheduler(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect the scheduler name, target entity and Nord Pool source."""
        if not self.hass.config_entries.async_entries(NORDPOOL_DOMAIN):
            return self.async_abort(reason="nordpool_not_configured")
        errors: dict[str, str] = {}

        if user_input is not None:
            if not self.hass.states.get(user_input[CONF_TARGET_ENTITY]):
                errors["base"] = "invalid_target"
            else:
                self._user_input = user_input
                return await self.async_step_area()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SCHEDULER_NAME): str,
                vol.Required(CONF_TARGET_ENTITY): _target_entity_selector(),
                vol.Required(
                    CONF_DEFAULT_STATE, default=STATE_DEFAULT_OFF
                ): _default_state_selector(),
                self._nordpool_entry_field(): _nordpool_entry_selector(),
            },
        )

        return self.async_show_form(
            step_id="scheduler", data_schema=data_schema, errors=errors
        )

    async def async_step_prices(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect the Nord Pool source for a prices-only entry."""
        if not self.hass.config_entries.async_entries(NORDPOOL_DOMAIN):
            return self.async_abort(reason="nordpool_not_configured")
        if user_input is not None:
            self._user_input = user_input
            return await self.async_step_area()

        data_schema = vol.Schema(
            {self._nordpool_entry_field(): _nordpool_entry_selector()}
        )
        return self.async_show_form(step_id="prices", data_schema=data_schema)

    async def async_step_area(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Pick which of the Nord Pool entry's areas this scheduler prices by."""
        nordpool_entry = self.hass.config_entries.async_get_entry(
            self._user_input[CONF_NORDPOOL_ENTRY_ID]
        )
        areas: list[str] = []
        if nordpool_entry is not None:
            areas = nordpool_entry.data.get("areas", [])

        if not areas:
            return self.async_abort(reason="nordpool_no_areas")

        if len(areas) == 1 or user_input is not None:
            area = areas[0] if user_input is None else user_input[CONF_AREA]
            data = {**self._user_input, CONF_AREA: area}

            if CONF_TARGET_ENTITY in data:
                unique_id = data[CONF_TARGET_ENTITY]
                title = f"Nordpool Scheduler - {data[CONF_SCHEDULER_NAME]}"
            else:
                unique_id = f"prices_{data[CONF_NORDPOOL_ENTRY_ID]}_{area}"
                title = f"Nordpool Scheduler - Prices {area}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(title=title, data=data)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_AREA): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=areas, mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
            }
        )
        return self.async_show_form(step_id="area", data_schema=data_schema)

    @staticmethod
    @callback
    def async_get_options_flow(
        _config_entry: config_entries.ConfigEntry,
    ) -> NordpoolSchedulerOptionsFlowHandler:
        """Get the options flow for this handler."""
        return NordpoolSchedulerOptionsFlowHandler()


class NordpoolSchedulerOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle options for an existing Nordpool Scheduler entry."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if is_prices_only(self.config_entry):
            return await self.async_step_prices(user_input)

        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            target_entity = user_input[CONF_TARGET_ENTITY]
            if not self.hass.states.get(target_entity):
                errors["base"] = "invalid_target"
            elif any(
                entry.unique_id == target_entity
                for entry in self.hass.config_entries.async_entries(DOMAIN)
                if entry.entry_id != self.config_entry.entry_id
            ):
                errors["base"] = "already_configured"
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, unique_id=target_entity
                )
                return self.async_create_entry(data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_TARGET_ENTITY, default=current.get(CONF_TARGET_ENTITY)
                ): _target_entity_selector(),
                vol.Required(
                    CONF_DEFAULT_STATE,
                    default=current.get(CONF_DEFAULT_STATE, STATE_DEFAULT_OFF),
                ): _default_state_selector(),
                vol.Required(
                    CONF_CONTROL_MODE,
                    default=current.get(CONF_CONTROL_MODE, CONTROL_MODE_ON_CHANGE),
                ): _control_mode_selector(),
                vol.Required(
                    CONF_VAT_PERCENT,
                    default=current.get(CONF_VAT_PERCENT, DEFAULT_VAT_PERCENT),
                ): _vat_percent_validator(),
            },
        )

        return self.async_show_form(
            step_id="init", data_schema=data_schema, errors=errors
        )

    async def async_step_prices(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage the options of a prices-only entry."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_VAT_PERCENT,
                    default=current.get(CONF_VAT_PERCENT, DEFAULT_VAT_PERCENT),
                ): _vat_percent_validator(),
            },
        )
        return self.async_show_form(step_id="prices", data_schema=data_schema)
