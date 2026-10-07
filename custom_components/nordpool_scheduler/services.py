"""Services for Nordpool Scheduler."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CONFIG_ENTRY,
    ATTR_SLOTS,
    ATTR_START,
    ATTR_STATE,
    DOMAIN,
    MAX_SLOT_LOOKAHEAD_DAYS,
    SERVICE_CLEAR_SCHEDULE,
    SERVICE_SET_SLOTS,
    SLOT_MINUTES,
    SLOT_STATE_DEFAULT,
    SLOT_STATE_ON,
    SLOT_STATES,
)
from .control import async_apply_now
from .util import is_prices_only, slot_start_for

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_SLOTS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): selector.ConfigEntrySelector(
            {"integration": DOMAIN}
        ),
        vol.Required(ATTR_SLOTS): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required(ATTR_START): cv.datetime,
                        vol.Required(ATTR_STATE): vol.In(SLOT_STATES),
                    }
                )
            ],
        ),
    }
)

SERVICE_CLEAR_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): selector.ConfigEntrySelector(
            {"integration": DOMAIN}
        ),
    }
)


def _loaded_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry:
    entry = hass.config_entries.async_get_entry(entry_id)
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"entry_id": entry_id},
        )
    return entry


def _scheduler_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry:
    entry = _loaded_entry(hass, entry_id)
    if is_prices_only(entry):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="prices_only_entry",
            translation_placeholders={"title": entry.title},
        )
    return entry


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register services for Nordpool Scheduler."""

    async def handle_set_slots(call: ServiceCall) -> None:
        entry = _scheduler_entry(hass, call.data[ATTR_CONFIG_ENTRY])
        runtime = entry.runtime_data
        now = dt_util.utcnow()
        earliest = slot_start_for(now)
        latest = earliest + timedelta(days=MAX_SLOT_LOOKAHEAD_DAYS)

        for raw_slot in call.data[ATTR_SLOTS]:
            start = dt_util.as_utc(raw_slot[ATTR_START])
            if start != slot_start_for(start):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="slot_not_aligned",
                    translation_placeholders={
                        "start": start.isoformat(),
                        "minutes": str(SLOT_MINUTES),
                    },
                )
            if not earliest <= start <= latest:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="slot_out_of_range",
                    translation_placeholders={"start": start.isoformat()},
                )

            state = raw_slot[ATTR_STATE]
            runtime.schedule.set_slot(
                start,
                state=None if state == SLOT_STATE_DEFAULT else state == SLOT_STATE_ON,
            )

        await async_apply_now(hass, entry)

    async def handle_clear_schedule(call: ServiceCall) -> None:
        entry = _scheduler_entry(hass, call.data[ATTR_CONFIG_ENTRY])
        runtime = entry.runtime_data
        runtime.schedule.clear()
        await async_apply_now(hass, entry)

    hass.services.async_register(
        DOMAIN, SERVICE_SET_SLOTS, handle_set_slots, schema=SERVICE_SET_SLOTS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_SCHEDULE,
        handle_clear_schedule,
        schema=SERVICE_CLEAR_SCHEDULE_SCHEMA,
    )
