"""Sensor platform for Nordpool Scheduler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_AREA, PRICE_UNIT
from .coordinator import NordpoolSchedulerPriceCoordinator
from .entity import build_device_info
from .util import slot_start_for

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import NordpoolSchedulerConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: NordpoolSchedulerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the price sensor for a config entry."""
    async_add_entities([NordpoolSchedulerPriceSensor(entry)])


class NordpoolSchedulerPriceSensor(
    CoordinatorEntity[NordpoolSchedulerPriceCoordinator], SensorEntity
):
    """The current electricity price in cents/kWh, VAT included."""

    _attr_has_entity_name = True
    _attr_translation_key = "electricity_price"
    _attr_native_unit_of_measurement = PRICE_UNIT
    _attr_suggested_display_precision = 2

    def __init__(self, entry: NordpoolSchedulerConfigEntry) -> None:
        """Initialize."""
        super().__init__(entry.runtime_data.coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_electricity_price"
        self._attr_device_info = build_device_info(entry)

    @property
    def native_value(self) -> float | None:
        """Return the price for the current slot."""
        return self.coordinator.get_price(slot_start_for(dt_util.utcnow()))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {
            "area": self._entry.data[CONF_AREA],
            "vat_percent": self.coordinator.vat_percent,
        }
