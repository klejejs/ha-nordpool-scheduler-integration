"""The Nordpool Scheduler integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.const import (
    ATTR_ENTITY_ID,
    EVENT_HOMEASSISTANT_STARTED,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONTROL_MODE,
    CONF_DEFAULT_STATE,
    CONF_TARGET_ENTITY,
    CONTROL_MODE_ENFORCE,
    DOMAIN,
    STATE_DEFAULT_ON,
)
from .coordinator import NordpoolSchedulerPriceCoordinator
from .schedule import ScheduleStore
from .services import async_setup_services
from .util import is_prices_only, slot_start_for
from .websocket_api import async_setup_websocket_api

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]
PRICES_PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type NordpoolSchedulerConfigEntry = ConfigEntry[NordpoolSchedulerRuntimeData]


@dataclass
class NordpoolSchedulerRuntimeData:
    """Runtime state for one Nordpool Scheduler config entry."""

    coordinator: NordpoolSchedulerPriceCoordinator
    schedule: ScheduleStore
    entry_id: str
    enabled: bool = True
    last_desired_state: bool | None = None
    unsub_tick: CALLBACK_TYPE | None = field(default=None, repr=False)

    @property
    def update_signal(self) -> str:
        """Dispatcher signal fired when the schedule or prices change."""
        return f"{DOMAIN}_updated_{self.entry_id}"


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Set up services and the websocket API shared by all entries."""
    async_setup_services(hass)
    async_setup_websocket_api(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: NordpoolSchedulerConfigEntry
) -> bool:
    """Set up Nordpool Scheduler from a config entry."""
    coordinator = NordpoolSchedulerPriceCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    schedule = ScheduleStore(hass, entry.entry_id)
    await schedule.async_load()

    runtime = NordpoolSchedulerRuntimeData(
        coordinator=coordinator, schedule=schedule, entry_id=entry.entry_id
    )
    entry.runtime_data = runtime

    coordinator.async_add_listener(
        lambda: async_dispatcher_send(hass, runtime.update_signal)
    )

    if is_prices_only(entry):
        await hass.config_entries.async_forward_entry_setups(entry, PRICES_PLATFORMS)
        return True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _async_apply_initial_state(_event: object = None) -> None:
        await _async_apply_slot(hass, entry, dt_util.utcnow())

    if hass.is_running:
        await _async_apply_initial_state()
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _async_apply_initial_state
            )
        )

    @callback
    def _on_tick(now: datetime) -> None:
        entry.async_create_task(
            hass, _async_apply_slot(hass, entry, now), "nordpool_scheduler_tick"
        )

    entry.async_on_unload(
        async_track_utc_time_change(hass, _on_tick, minute=[0, 15, 30, 45], second=0)
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: NordpoolSchedulerConfigEntry
) -> bool:
    """Unload a config entry."""
    platforms = PRICES_PLATFORMS if is_prices_only(entry) else PLATFORMS
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        # A reload can otherwise race Store's delayed save and lose a
        # just-made schedule change.
        await entry.runtime_data.schedule.async_flush()
    return unload_ok


async def async_migrate_entry(
    _hass: HomeAssistant, entry: NordpoolSchedulerConfigEntry
) -> bool:
    """Migrate an old config entry.

    Version 1 entries priced from a CSV feed and had no Nord Pool config
    entry or area to price by; that can't be inferred automatically. Ask
    the user to remove and re-add the scheduler, picking a Nord Pool
    source, instead of leaving it half-migrated.
    """
    if entry.version == 1:
        _LOGGER.error(
            "Nordpool Scheduler entry %s was created before this integration used "
            "the Nord Pool integration for prices. It can't be migrated "
            "automatically: please remove it and add it again, selecting a Nord "
            "Pool config entry",
            entry.title,
        )
        return False
    return True


async def _async_apply_slot(
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
    default_on = settings.get(CONF_DEFAULT_STATE) == STATE_DEFAULT_ON
    override = runtime.schedule.get(slot_start)
    desired_on = default_on if override is None else override

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
