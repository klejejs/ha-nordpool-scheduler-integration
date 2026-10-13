"""The Nordpool Scheduler integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_ON, Platform
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_utc_time_change,
)
from homeassistant.util import dt as dt_util

from .auto import blocks_slot, select_auto_slots
from .const import (
    CONF_DEFAULT_STATE,
    CONF_STOP_ENTITY,
    CONF_TARGET_ENTITY,
    DEFAULT_MAX_RUNS,
    DOMAIN,
    SLOT_SOURCE_AUTO,
    SLOT_SOURCE_DEFAULT,
    SLOT_SOURCE_OVERRIDE,
    SLOT_SOURCE_STOPPED,
    STATE_DEFAULT_ON,
)
from .control import DesiredStateStore, async_apply_now, async_apply_slot
from .coordinator import NordpoolSchedulerPriceCoordinator
from .schedule import ScheduleStore
from .services import async_setup_services
from .stats import PriceStats
from .util import is_prices_only
from .websocket_api import async_setup_websocket_api
from .windows import AutoWindowStore, async_migrate_windows

if TYPE_CHECKING:
    from datetime import datetime, tzinfo

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.typing import ConfigType

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
]
PRICES_PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type NordpoolSchedulerConfigEntry = ConfigEntry[NordpoolSchedulerRuntimeData]


@dataclass
class NordpoolSchedulerRuntimeData:
    """Runtime state for one Nordpool Scheduler config entry."""

    coordinator: NordpoolSchedulerPriceCoordinator
    schedule: ScheduleStore
    stats: PriceStats
    desired_state: DesiredStateStore
    windows: AutoWindowStore
    entry_id: str
    default_on: bool = False
    stop_entity: str | None = None
    enabled: bool = True
    auto_enabled: bool = False
    runs_limited: bool = False
    max_runs: float = DEFAULT_MAX_RUNS
    auto_slots: dict[datetime, bool] = field(default_factory=dict, repr=False)
    time_zone: tzinfo = field(default=dt_util.DEFAULT_TIME_ZONE, repr=False)
    last_desired_state: bool | None = None
    restored_desired_state: bool | None = None
    unsub_tick: CALLBACK_TYPE | None = field(default=None, repr=False)

    @property
    def update_signal(self) -> str:
        """Dispatcher signal fired when the schedule or prices change."""
        return f"{DOMAIN}_updated_{self.entry_id}"

    @property
    def run_hours(self) -> float:
        """Return how long the time windows run for in total each day."""
        return sum(window.run_hours for window in self.windows.windows)

    def refresh_auto(self, hass: HomeAssistant) -> None:
        """Recompute auto mode's picks from the current prices and settings."""
        tz = dt_util.get_time_zone(hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
        self.time_zone = tz
        self.auto_slots = select_auto_slots(
            self.coordinator.data or {},
            tz,
            windows=self.windows.windows,
            max_runs=int(self.max_runs) if self.runs_limited else None,
        )

    def auto_pick(self, slot_start: datetime) -> bool | None:
        """Return auto mode's choice for a slot, or None if it makes none."""
        if not self.auto_enabled:
            return None
        pick = self.auto_slots.get(slot_start)
        if pick is None and blocks_slot(
            slot_start, self.time_zone, self.windows.windows
        ):
            return False
        return pick

    def base_state(self, slot_start: datetime) -> tuple[bool, str]:
        """Return what auto mode or the default wants, ignoring overrides."""
        auto = self.auto_pick(slot_start)
        if auto is not None:
            return auto, SLOT_SOURCE_AUTO
        return self.default_on, SLOT_SOURCE_DEFAULT

    def prune_overrides(self, now: datetime) -> None:
        """Drop overrides that have ended or that auto mode or the default now match."""
        self.schedule.prune(now, lambda start: self.base_state(start)[0])

    def slot_state(self, slot_start: datetime) -> tuple[bool, str]:
        """Return a slot's effective state and where it comes from."""
        override = self.schedule.get(slot_start)
        if override is not None:
            return override, SLOT_SOURCE_OVERRIDE
        return self.base_state(slot_start)

    def stopped(self, hass: HomeAssistant) -> bool:
        """Return whether the stop entity is holding the target off."""
        if self.stop_entity is None:
            return False
        return _is_stopping(hass.states.get(self.stop_entity))

    def live_state(self, hass: HomeAssistant, slot_start: datetime) -> tuple[bool, str]:
        """Return what the target should do now, with the stop entity applied."""
        if self.stopped(hass):
            return False, SLOT_SOURCE_STOPPED
        return self.slot_state(slot_start)


def _is_stopping(state: State | None) -> bool:
    return state is not None and state.state == STATE_ON


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

    stats = PriceStats(hass, entry.entry_id, coordinator.get_price)
    await stats.async_load()

    settings = {**entry.data, **entry.options}
    desired_state = DesiredStateStore(
        hass, entry.entry_id, settings.get(CONF_TARGET_ENTITY)
    )
    restored_desired_state = await desired_state.async_load()

    windows = AutoWindowStore(hass, entry.entry_id)
    await windows.async_load()

    runtime = NordpoolSchedulerRuntimeData(
        coordinator=coordinator,
        schedule=schedule,
        stats=stats,
        desired_state=desired_state,
        windows=windows,
        entry_id=entry.entry_id,
        default_on=settings.get(CONF_DEFAULT_STATE) == STATE_DEFAULT_ON,
        stop_entity=settings.get(CONF_STOP_ENTITY) or None,
        restored_desired_state=restored_desired_state,
    )
    runtime.refresh_auto(hass)
    entry.runtime_data = runtime

    @callback
    def _on_prices_updated() -> None:
        # The coordinator also calls this at every slot boundary, so the time
        # since the last sample is counted before the update goes out.
        now = dt_util.utcnow()
        stats.sample(now)
        runtime.refresh_auto(hass)
        if entry.state is ConfigEntryState.LOADED:
            # During setup the auto settings aren't restored yet, so the base
            # state could wrongly match an override.
            runtime.prune_overrides(now)
        async_dispatcher_send(hass, runtime.update_signal)

    entry.async_on_unload(coordinator.async_add_listener(_on_prices_updated))
    entry.async_on_unload(
        stats.async_start(settings.get(CONF_TARGET_ENTITY), runtime.update_signal)
    )

    if is_prices_only(entry):
        await hass.config_entries.async_forward_entry_setups(entry, PRICES_PLATFORMS)
        return True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _async_apply_initial_state(_event: object = None) -> None:
        # A stop must hold even if the target was turned on while we were down.
        await async_apply_slot(
            hass, entry, dt_util.utcnow(), sync_target=runtime.stopped(hass)
        )

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
            hass, async_apply_slot(hass, entry, now), "nordpool_scheduler_tick"
        )

    entry.async_on_unload(
        async_track_utc_time_change(hass, _on_tick, minute=[0, 15, 30, 45], second=0)
    )

    if runtime.stop_entity is not None:

        @callback
        def _on_stop_change(event: Event[EventStateChangedData]) -> None:
            if _is_stopping(event.data["old_state"]) == _is_stopping(
                event.data["new_state"]
            ):
                return
            entry.async_create_task(
                hass,
                async_apply_now(hass, entry, sync_target=True),
                "nordpool_scheduler_stop",
            )

        entry.async_on_unload(
            async_track_state_change_event(hass, [runtime.stop_entity], _on_stop_change)
        )

    return True


async def async_migrate_entry(
    hass: HomeAssistant, entry: NordpoolSchedulerConfigEntry
) -> bool:
    """Migrate an entry from an older version."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:  # noqa: PLR2004
        if not is_prices_only(entry):
            await async_migrate_windows(hass, entry)
        hass.config_entries.async_update_entry(entry, minor_version=2)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: NordpoolSchedulerConfigEntry
) -> bool:
    """Unload a config entry."""
    platforms = PRICES_PLATFORMS if is_prices_only(entry) else PLATFORMS
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        # A reload can otherwise race Store's delayed saves and lose a
        # just-made schedule change or the time counted since the last tick.
        runtime = entry.runtime_data
        await runtime.schedule.async_flush()
        await runtime.desired_state.async_flush()
        await runtime.windows.async_flush()
        runtime.stats.sample(dt_util.utcnow())
        await runtime.stats.async_flush()
    return unload_ok
