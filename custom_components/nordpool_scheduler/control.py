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
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONTROL_MODE,
    CONF_TARGET_ENTITY,
    CONTROL_MODE_ENFORCE,
    DESIRED_STATE_STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .util import slot_start_for

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant

    from . import NordpoolSchedulerConfigEntry, NordpoolSchedulerRuntimeData

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY = 5


class DesiredStateStore:
    """Persist the state the scheduler last applied to the target.

    on_change mode reads it back after a restart or reload, so a manual
    toggle made before then isn't undone.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize."""
        self._store: Store[dict[str, bool | None]] = Store(
            hass, STORAGE_VERSION, f"{DESIRED_STATE_STORAGE_KEY_PREFIX}.{entry_id}"
        )
        self._state: bool | None = None
        self._changed = False

    async def async_load(self) -> bool | None:
        """Load and return the saved state, or None if there is none."""
        stored = await self._store.async_load() or {}
        state = stored.get("desired_on")
        self._state = state if isinstance(state, bool) else None
        return self._state

    def save(self, *, state: bool | None) -> None:
        """Remember ``state``, writing it to disk after a short delay."""
        if state is self._state:
            return
        self._state = state
        self._changed = True
        self._store.async_delay_save(self._as_stored, SAVE_DELAY)

    async def async_flush(self) -> None:
        """Write out a pending delayed save immediately."""
        if self._changed:
            await self._store.async_save(self._as_stored())

    def _as_stored(self) -> dict[str, bool | None]:
        return {"desired_on": self._state}


async def async_apply_now(
    hass: HomeAssistant,
    entry: NordpoolSchedulerConfigEntry,
    *,
    sync_target: bool = False,
) -> None:
    """Push the change to listeners and apply the current slot straight away."""
    async_dispatcher_send(hass, entry.runtime_data.update_signal)
    await async_apply_slot(hass, entry, dt_util.utcnow(), sync_target=sync_target)


async def async_apply_slot(
    hass: HomeAssistant,
    entry: NordpoolSchedulerConfigEntry,
    now: datetime,
    *,
    sync_target: bool = False,
) -> None:
    """Turn the target entity on or off for the slot containing ``now``.

    ``sync_target`` switches the target whenever its state differs from the
    slot's, even in on_change mode after a manual toggle.
    """
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
    previous = runtime.last_desired_state
    if previous is None and control_mode != CONTROL_MODE_ENFORCE:
        # First run since setup: carry on from the state applied before the
        # restart or reload, so a manual toggle made since then is kept.
        previous = runtime.restored_desired_state
    runtime.restored_desired_state = None

    if previous is None or sync_target:
        # Nothing to go on, or the current slot was just edited: only call
        # the target if it doesn't already match the schedule.
        currently_on = target_state.state != STATE_OFF
        should_call = currently_on != desired_on
    else:
        should_call = control_mode == CONTROL_MODE_ENFORCE or previous != desired_on

    if not should_call:
        _set_last_desired_state(runtime, state=desired_on)
    else:
        domain = target_entity.split(".")[0]
        try:
            await hass.services.async_call(
                domain,
                SERVICE_TURN_ON if desired_on else SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: target_entity},
                blocking=True,
            )
        except HomeAssistantError as err:
            # A failed call here must not fail entry setup, or abort a
            # 15-minute tick shared with other listeners. Leave the marker
            # unset so on_change mode retries on the next tick instead of
            # believing this state was already applied.
            _LOGGER.warning(
                "Could not set %s to %s: %s", target_entity, desired_on, err
            )
            if sync_target:
                # The marker may already match the slot, which would stop
                # on_change mode retrying; compare with the target instead.
                _set_last_desired_state(runtime, state=None)
        else:
            _set_last_desired_state(runtime, state=desired_on)
            _LOGGER.debug(
                "%s: slot %s -> %s", entry.title, slot_start.isoformat(), desired_on
            )

    async_dispatcher_send(hass, runtime.update_signal)


def _set_last_desired_state(
    runtime: NordpoolSchedulerRuntimeData, *, state: bool | None
) -> None:
    runtime.last_desired_state = state
    runtime.desired_state.save(state=state)
