"""The Nordpool Scheduler integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.util import dt as dt_util

from .auto import select_auto_slots
from .const import (
    CONF_DEFAULT_STATE,
    CONF_TARGET_ENTITY,
    DEFAULT_RUN_HOURS,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    DOMAIN,
    SLOT_SOURCE_AUTO,
    SLOT_SOURCE_DEFAULT,
    SLOT_SOURCE_OVERRIDE,
    STATE_DEFAULT_ON,
)
from .control import DesiredStateStore, async_apply_slot
from .coordinator import NordpoolSchedulerPriceCoordinator
from .schedule import ScheduleStore
from .services import async_setup_services
from .stats import PriceStats
from .util import is_prices_only
from .websocket_api import async_setup_websocket_api

if TYPE_CHECKING:
    from datetime import datetime, time

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.typing import ConfigType

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.TIME,
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
    entry_id: str
    default_on: bool = False
    enabled: bool = True
    auto_enabled: bool = False
    run_hours: float = DEFAULT_RUN_HOURS
    max_price: float = 0.0
    cheap_price: float = 0.0
    window_enabled: bool = False
    window_start: time = DEFAULT_WINDOW_START
    window_end: time = DEFAULT_WINDOW_END
    cheap_all_day: bool = False
    auto_slots: dict[datetime, bool] = field(default_factory=dict, repr=False)
    last_desired_state: bool | None = None
    restored_desired_state: bool | None = None
    unsub_tick: CALLBACK_TYPE | None = field(default=None, repr=False)

    @property
    def update_signal(self) -> str:
        """Dispatcher signal fired when the schedule or prices change."""
        return f"{DOMAIN}_updated_{self.entry_id}"

    def refresh_auto(self, hass: HomeAssistant) -> None:
        """Recompute auto mode's picks from the current prices and settings."""
        tz = dt_util.get_time_zone(hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
        self.auto_slots = select_auto_slots(
            self.coordinator.data or {},
            tz,
            run_hours=self.run_hours,
            max_price=self.max_price,
            cheap_price=self.cheap_price,
            window=(
                (self.window_start, self.window_end) if self.window_enabled else None
            ),
            cheap_all_day=self.cheap_all_day,
        )

    def auto_pick(self, slot_start: datetime) -> bool | None:
        """Return auto mode's choice for a slot, or None if it makes none."""
        if not self.auto_enabled:
            return None
        return self.auto_slots.get(slot_start)

    def base_state(self, slot_start: datetime) -> tuple[bool, str]:
        """Return what auto mode or the default wants, ignoring overrides."""
        auto = self.auto_pick(slot_start)
        if auto is not None:
            return auto, SLOT_SOURCE_AUTO
        return self.default_on, SLOT_SOURCE_DEFAULT

    def slot_state(self, slot_start: datetime) -> tuple[bool, str]:
        """Return a slot's effective state and where it comes from."""
        override = self.schedule.get(slot_start)
        if override is not None:
            return override, SLOT_SOURCE_OVERRIDE
        return self.base_state(slot_start)


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

    runtime = NordpoolSchedulerRuntimeData(
        coordinator=coordinator,
        schedule=schedule,
        stats=stats,
        desired_state=desired_state,
        entry_id=entry.entry_id,
        default_on=settings.get(CONF_DEFAULT_STATE) == STATE_DEFAULT_ON,
        restored_desired_state=restored_desired_state,
    )
    runtime.refresh_auto(hass)
    entry.runtime_data = runtime

    @callback
    def _on_prices_updated() -> None:
        # The coordinator also calls this at every slot boundary, so the time
        # since the last sample is counted before the update goes out.
        stats.sample(dt_util.utcnow())
        runtime.refresh_auto(hass)
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
        await async_apply_slot(hass, entry, dt_util.utcnow())

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
        runtime.stats.sample(dt_util.utcnow())
        await runtime.stats.async_flush()
    return unload_ok
