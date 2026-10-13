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

from .auto import AutoWindow
from .const import (
    ATTR_CHEAP_PRICE,
    ATTR_CONFIG_ENTRY,
    ATTR_END,
    ATTR_HOURS,
    ATTR_MAX_PRICE,
    ATTR_MIN_RUN_HOURS,
    ATTR_SLOTS,
    ATTR_START,
    ATTR_STATE,
    ATTR_WINDOWS,
    DOMAIN,
    MAX_SLOT_LOOKAHEAD_DAYS,
    SERVICE_CLEAR_SCHEDULE,
    SERVICE_SET_AUTO_WINDOWS,
    SERVICE_SET_SLOTS,
    SLOT_MINUTES,
    SLOT_STATE_DEFAULT,
    SLOT_STATE_ON,
    SLOT_STATES,
)
from .control import async_apply_now
from .util import is_prices_only, slot_start_for
from .windows import whole_minute

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


def _quarter_hours(hours: float) -> float:
    if (hours * 60) % SLOT_MINUTES:
        msg = f"hours must be a multiple of {SLOT_MINUTES} minutes"
        raise vol.Invalid(msg)
    return hours


_PRICE = vol.All(vol.Coerce(float), vol.Range(min=0, max=1000))
_HOURS = vol.All(vol.Coerce(float), vol.Range(min=0, max=24), _quarter_hours)

SERVICE_SET_AUTO_WINDOWS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): selector.ConfigEntrySelector(
            {"integration": DOMAIN}
        ),
        vol.Required(ATTR_WINDOWS): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required(ATTR_START): vol.All(cv.time, whole_minute),
                        vol.Required(ATTR_END): vol.All(cv.time, whole_minute),
                        vol.Required(ATTR_HOURS): _HOURS,
                        vol.Optional(ATTR_MAX_PRICE, default=0): _PRICE,
                        vol.Optional(ATTR_CHEAP_PRICE, default=0): _PRICE,
                        vol.Optional(ATTR_MIN_RUN_HOURS, default=0): _HOURS,
                    }
                )
            ],
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
        touches_current = False

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

            touches_current = touches_current or start == earliest
            state = raw_slot[ATTR_STATE]
            runtime.schedule.set_slot(
                start,
                state=None if state == SLOT_STATE_DEFAULT else state == SLOT_STATE_ON,
            )

        await async_apply_now(hass, entry, sync_target=touches_current)

    async def handle_clear_schedule(call: ServiceCall) -> None:
        entry = _scheduler_entry(hass, call.data[ATTR_CONFIG_ENTRY])
        runtime = entry.runtime_data
        runtime.schedule.clear()
        await async_apply_now(hass, entry)

    async def handle_set_auto_windows(call: ServiceCall) -> None:
        entry = _scheduler_entry(hass, call.data[ATTR_CONFIG_ENTRY])
        runtime = entry.runtime_data
        runtime.windows.set_windows(
            [
                AutoWindow(
                    start=window[ATTR_START],
                    end=window[ATTR_END],
                    hours=window[ATTR_HOURS],
                    max_price=window[ATTR_MAX_PRICE],
                    cheap_price=window[ATTR_CHEAP_PRICE],
                    min_run_hours=window[ATTR_MIN_RUN_HOURS],
                )
                for window in call.data[ATTR_WINDOWS]
            ]
        )
        runtime.refresh_auto(hass)
        await async_apply_now(hass, entry)

    hass.services.async_register(
        DOMAIN, SERVICE_SET_SLOTS, handle_set_slots, schema=SERVICE_SET_SLOTS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_AUTO_WINDOWS,
        handle_set_auto_windows,
        schema=SERVICE_SET_AUTO_WINDOWS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_SCHEDULE,
        handle_clear_schedule,
        schema=SERVICE_CLEAR_SCHEDULE_SCHEMA,
    )
