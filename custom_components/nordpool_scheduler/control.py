"""Drive the target entity from the schedule."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import CONF_CONTROL_MODE, CONF_TARGET_ENTITY, CONTROL_MODE_ENFORCE
from .util import slot_start_for

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant

    from . import NordpoolSchedulerConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_apply_now(
    hass: HomeAssistant, entry: NordpoolSchedulerConfigEntry
) -> None:
    """Push the change to listeners and apply the current slot straight away."""
    async_dispatcher_send(hass, entry.runtime_data.update_signal)
    await async_apply_slot(hass, entry, dt_util.utcnow())


async def async_apply_slot(
    hass: HomeAssistant,
    entry: NordpoolSchedulerConfigEntry,
    now: datetime,
) -> None:
    """Turn the target entity on or off for the slot containing ``now``."""
    runtime = entry.runtime_data
    if not runtime.enabled:
        return

    settings = {**entry.data, **entry.options}
    target_entity: str = settings[CONF_TARGET_ENTITY]
    target_state = hass.states.get(target_entity)
    if target_state is None or target_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        _LOGGER.debug(
            "Target entity %s is unavailable, skipping slot update", target_entity
        )
        return

    slot_start = slot_start_for(now)
    desired_on, _source = runtime.slot_state(slot_start)

    runtime.schedule.prune_ended(now)

    control_mode = settings.get(CONF_CONTROL_MODE)
    if runtime.last_desired_state is None:
        # First run since setup: there is no previous slot to compare with,
        # so only call the target if it doesn't already match the schedule.
        currently_on = target_state.state != STATE_OFF
        should_call = currently_on != desired_on
    else:
        should_call = (
            control_mode == CONTROL_MODE_ENFORCE
            or runtime.last_desired_state != desired_on
        )

    if not should_call:
        runtime.last_desired_state = desired_on
    else:
        domain = target_entity.split(".")[0]
        try:
            await hass.services.async_call(
                domain,
                SERVICE_TURN_ON if desired_on else SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: target_entity},
            )
        except HomeAssistantError as err:
            # A failed call here must not fail entry setup, or abort a
            # 15-minute tick shared with other listeners. Leave the marker
            # unset so on_change mode retries on the next tick instead of
            # believing this state was already applied.
            _LOGGER.warning(
                "Could not set %s to %s: %s", target_entity, desired_on, err
            )
        else:
            runtime.last_desired_state = desired_on
            _LOGGER.debug(
                "%s: slot %s -> %s", entry.title, slot_start.isoformat(), desired_on
            )

    async_dispatcher_send(hass, runtime.update_signal)
