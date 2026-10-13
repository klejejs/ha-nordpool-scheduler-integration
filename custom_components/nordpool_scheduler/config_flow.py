"""Config flow for Nordpool Scheduler integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_AREA,
    CONF_CONTROL_MODE,
    CONF_DEFAULT_STATE,
    CONF_NORDPOOL_ENTRY_ID,
    CONF_SCHEDULER_NAME,
    CONF_STOP_ENTITY,
    CONF_TARGET_ENTITY,
    CONF_VAT_PERCENT,
    CONTROL_MODE_ENFORCE,
    CONTROL_MODE_ON_CHANGE,
    DEFAULT_VAT_PERCENT,
    DOMAIN,
    NORDPOOL_DOMAIN,
    STATE_DEFAULT_OFF,
    STATE_DEFAULT_ON,
    STOP_ENTITY_DOMAINS,
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


def _stop_entity_selector() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=STOP_ENTITY_DOMAINS)
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


def _target_error(hass: HomeAssistant, entity_id: str) -> str | None:
    if not hass.states.get(entity_id):
        return "invalid_target"
    registry_entry = er.async_get(hass).async_get(entity_id)
    if registry_entry is not None and registry_entry.platform == DOMAIN:
        return "target_is_scheduler"
    return None


def _nordpool_entry_error(hass: HomeAssistant, entry_id: str) -> str | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != NORDPOOL_DOMAIN:
        return "invalid_nordpool_entry"
    return None


class NordpoolSchedulerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nordpool Scheduler."""

    VERSION = 1
    MINOR_VERSION = 2

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
            if not user_input[CONF_SCHEDULER_NAME].strip():
                errors["base"] = "invalid_name"
            elif error := _target_error(
                self.hass, user_input[CONF_TARGET_ENTITY]
            ) or _nordpool_entry_error(self.hass, user_input[CONF_NORDPOOL_ENTRY_ID]):
                errors["base"] = error
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
            step_id="scheduler",
            data_schema=self.add_suggested_values_to_schema(data_schema, user_input),
            errors=errors,
        )

    async def async_step_prices(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect the Nord Pool source for a prices-only entry."""
        if not self.hass.config_entries.async_entries(NORDPOOL_DOMAIN):
            return self.async_abort(reason="nordpool_not_configured")
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _nordpool_entry_error(
                self.hass, user_input[CONF_NORDPOOL_ENTRY_ID]
            ):
                errors["base"] = error
            else:
                self._user_input = user_input
                return await self.async_step_area()

        data_schema = vol.Schema(
            {self._nordpool_entry_field(): _nordpool_entry_selector()}
        )
        return self.async_show_form(
            step_id="prices", data_schema=data_schema, errors=errors
        )

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
            stop_entity = user_input.get(CONF_STOP_ENTITY)
            stop_registry_entry = (
                er.async_get(self.hass).async_get(stop_entity) if stop_entity else None
            )
            if error := _target_error(self.hass, target_entity):
                errors["base"] = error
            elif stop_entity and not self.hass.states.get(stop_entity):
                errors["base"] = "invalid_stop_entity"
            elif stop_entity == target_entity:
                errors["base"] = "stop_is_target"
            elif (
                stop_registry_entry is not None
                and stop_registry_entry.config_entry_id == self.config_entry.entry_id
            ):
                errors["base"] = "stop_is_scheduler"
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
                vol.Optional(
                    CONF_STOP_ENTITY,
                    description={"suggested_value": current.get(CONF_STOP_ENTITY)},
                ): _stop_entity_selector(),
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
