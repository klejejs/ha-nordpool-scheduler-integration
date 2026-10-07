"""Sensor platform for Nordpool Scheduler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_AREA, PRICE_UNIT
from .coordinator import NordpoolSchedulerPriceCoordinator
from .entity import build_device_info
from .stats import WINDOWS, StatsWindow
from .util import is_prices_only, slot_start_for

if TYPE_CHECKING:
    from datetime import date

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import NordpoolSchedulerConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: NordpoolSchedulerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the price sensors for a config entry."""
    async_add_entities(
        [
            NordpoolSchedulerPriceSensor(entry),
            *(NordpoolSchedulerAveragePriceSensor(entry, w) for w in WINDOWS),
        ]
    )


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


class NordpoolSchedulerAveragePriceSensor(SensorEntity):
    """The average price while the target ran, over one calendar period."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = PRICE_UNIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_should_poll = False

    def __init__(
        self, entry: NordpoolSchedulerConfigEntry, window: StatsWindow
    ) -> None:
        """Initialize."""
        self._entry = entry
        self._window = window
        self._attr_translation_key = f"average_price_{window.key}"
        self._attr_unique_id = f"{entry.entry_id}_average_price_{window.key}"
        self._attr_device_info = build_device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._entry.runtime_data.update_signal, self._async_refresh
            )
        )

    @callback
    def _async_refresh(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        """Return the average price for the period so far."""
        price, _hours = self._entry.runtime_data.stats.average(self._period_start)
        return price

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes: dict[str, Any] = {"period_start": self._period_start.isoformat()}
        if not is_prices_only(self._entry):
            _price, hours = self._entry.runtime_data.stats.average(self._period_start)
            attributes["running_hours"] = hours
        return attributes

    @property
    def _period_start(self) -> date:
        return self._window.start(dt_util.now().date())
