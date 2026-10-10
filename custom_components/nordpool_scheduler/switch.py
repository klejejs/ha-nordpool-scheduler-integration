"""Switch platform for Nordpool Scheduler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .control import async_apply_now
from .entity import build_device_info

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import NordpoolSchedulerConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: NordpoolSchedulerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the enabled and auto mode switches for a config entry."""
    async_add_entities(
        [
            NordpoolSchedulerEnabledSwitch(entry),
            NordpoolSchedulerAutoModeSwitch(entry),
            NordpoolSchedulerWindowSwitch(entry),
            NordpoolSchedulerCheapAllDaySwitch(entry),
            NordpoolSchedulerRunsLimitSwitch(entry),
        ]
    )


class NordpoolSchedulerEnabledSwitch(RestoreEntity, SwitchEntity):
    """Enable or disable automatic scheduling for this entry."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_translation_key = "scheduler_enabled"
    _attr_should_poll = False

    def __init__(self, entry: NordpoolSchedulerConfigEntry) -> None:
        """Initialize."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_scheduler_enabled"
        self._attr_device_info = build_device_info(entry)
        self._attr_is_on = True

    async def async_added_to_hass(self) -> None:
        """Restore the last known enabled state."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == STATE_ON
        self._entry.runtime_data.enabled = self._attr_is_on

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Enable scheduling."""
        self._attr_is_on = True
        self._entry.runtime_data.enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Disable scheduling; the target entity is left as-is."""
        self._attr_is_on = False
        self._entry.runtime_data.enabled = False
        self.async_write_ha_state()


class NordpoolSchedulerAutoSettingSwitch(RestoreEntity, SwitchEntity):
    """An auto mode on/off setting, off until turned on, kept across restarts."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_should_poll = False
    _key: str
    _runtime_attr: str

    def __init__(self, entry: NordpoolSchedulerConfigEntry) -> None:
        """Initialize."""
        self._entry = entry
        self._attr_translation_key = self._key
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_device_info = build_device_info(entry)
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore the last known state."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == STATE_ON
        self._store()

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn the setting on."""
        await self._async_set(on=True)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn the setting off."""
        await self._async_set(on=False)

    async def _async_set(self, *, on: bool) -> None:
        self._attr_is_on = on
        self._store()
        self.async_write_ha_state()
        await async_apply_now(self.hass, self._entry)

    def _store(self) -> None:
        runtime = self._entry.runtime_data
        setattr(runtime, self._runtime_attr, self._attr_is_on)
        runtime.refresh_auto(self.hass)


class NordpoolSchedulerAutoModeSwitch(NordpoolSchedulerAutoSettingSwitch):
    """Pick the cheapest slots of each day instead of using the default state.

    Turned off, slots without an override follow the default state.
    """

    _key = "auto_mode"
    _runtime_attr = "auto_enabled"


class NordpoolSchedulerWindowSwitch(NordpoolSchedulerAutoSettingSwitch):
    """Only pick slots between auto mode's start and end times."""

    _key = "window_enabled"
    _runtime_attr = "window_enabled"


class NordpoolSchedulerCheapAllDaySwitch(NordpoolSchedulerAutoSettingSwitch):
    """Run slots at or below the cheap price outside the hour range too."""

    _key = "cheap_all_day"
    _runtime_attr = "cheap_all_day"


class NordpoolSchedulerRunsLimitSwitch(NordpoolSchedulerAutoSettingSwitch):
    """Cap how many separate runs auto mode makes each day."""

    _key = "runs_limited"
    _runtime_attr = "runs_limited"
