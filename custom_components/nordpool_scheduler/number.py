"""Number platform for Nordpool Scheduler: auto mode's settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.number import (
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import EntityCategory, UnitOfTime

from .const import DEFAULT_RUN_HOURS, PRICE_UNIT
from .control import async_apply_now
from .entity import build_device_info

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import NordpoolSchedulerConfigEntry


@dataclass(frozen=True, kw_only=True)
class AutoSettingDescription(NumberEntityDescription):
    """A number entity backed by one runtime auto mode setting."""

    default: float


DESCRIPTIONS: tuple[AutoSettingDescription, ...] = (
    AutoSettingDescription(
        key="run_hours",
        translation_key="run_hours",
        native_min_value=0,
        native_max_value=24,
        native_step=0.25,
        native_unit_of_measurement=UnitOfTime.HOURS,
        default=DEFAULT_RUN_HOURS,
    ),
    AutoSettingDescription(
        key="max_price",
        translation_key="max_price",
        native_min_value=0,
        native_max_value=1000,
        native_step=0.01,
        native_unit_of_measurement=PRICE_UNIT,
        default=0.0,
    ),
    AutoSettingDescription(
        key="cheap_price",
        translation_key="cheap_price",
        native_min_value=0,
        native_max_value=1000,
        native_step=0.01,
        native_unit_of_measurement=PRICE_UNIT,
        default=0.0,
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: NordpoolSchedulerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the auto mode settings for a config entry."""
    async_add_entities(
        NordpoolSchedulerAutoSetting(entry, description) for description in DESCRIPTIONS
    )


class NordpoolSchedulerAutoSetting(RestoreNumber):
    """One auto mode setting: hours per day, max price or cheap price."""

    entity_description: AutoSettingDescription
    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(
        self, entry: NordpoolSchedulerConfigEntry, description: AutoSettingDescription
    ) -> None:
        """Initialize."""
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = build_device_info(entry)
        self._attr_native_value = description.default

    async def async_added_to_hass(self) -> None:
        """Restore the last value and feed it to auto mode."""
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        self._store(self._attr_native_value)

    async def async_set_native_value(self, value: float) -> None:
        """Change the setting and re-pick auto mode's slots."""
        self._attr_native_value = value
        self._store(value)
        self.async_write_ha_state()
        await async_apply_now(self.hass, self._entry)

    def _store(self, value: float) -> None:
        runtime = self._entry.runtime_data
        setattr(runtime, self.entity_description.key, value)
        runtime.refresh_auto(self.hass)
