"""Sensor platform for Nordpool Scheduler."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import CURRENCY_EURO
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_PRICES,
    CONF_DEFAULT_STATE,
    CONF_SCHEDULER_NAME,
    CONF_TARGET_SWITCH,
    DOMAIN,
)
from .coordinator import NordpoolDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nordpool Scheduler sensor based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    scheduler_name = entry.data[CONF_SCHEDULER_NAME]

    async_add_entities(
        [NordpoolPriceSensor(coordinator, entry, scheduler_name)],
        update_before_add=True,
    )


class NordpoolPriceSensor(
    CoordinatorEntity[NordpoolDataUpdateCoordinator],
    SensorEntity,
):
    """Representation of a Nordpool price sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = f"{CURRENCY_EURO}/kWh"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NordpoolDataUpdateCoordinator,
        entry: ConfigEntry,
        scheduler_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self._entry = entry
        self._scheduler_name = scheduler_name
        self._attr_unique_id = f"{entry.entry_id}_electricity_price"
        self._attr_name = "Electricity Price"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("current_price")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not self.coordinator.data:
            return {}

        prices = self.coordinator.data.get("prices", [])
        last_update = self.coordinator.data.get("last_update")

        attrs = {
            ATTR_PRICES: prices,
            "last_update": last_update.isoformat() if last_update else None,
            "entry_id": self._entry.entry_id,
            "scheduler_name": self._scheduler_name,
            "default_state": self._entry.data.get(CONF_DEFAULT_STATE),
        }

        # Add current slot index (in Riga timezone for electricity pricing)
        riga_tz = ZoneInfo("Europe/Riga")
        now_riga = datetime.now(riga_tz)
        current_slot = now_riga.hour * 4 + (now_riga.minute // 15)
        attrs["current_slot"] = current_slot

        # Calculate price statistics if we have data
        valid_prices = [p for p in prices if p is not None]
        if valid_prices:
            attrs["min_price"] = min(valid_prices)
            attrs["max_price"] = max(valid_prices)
            attrs["avg_price"] = sum(valid_prices) / len(valid_prices)

        # Add target entity current state
        target_entity_id = self._entry.data.get(CONF_TARGET_SWITCH)
        if target_entity_id and self.hass:
            target_state = self.hass.states.get(target_entity_id)
            if target_state:
                attrs["target_entity_state"] = target_state.state
            else:
                attrs["target_entity_state"] = "unavailable"
        else:
            attrs["target_entity_state"] = None

        # Add scheduled override times with dates
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        schedule = entry_data.get("schedule", {})

        # Parse date-based schedule keys and convert to readable format
        scheduled_times = []
        for key, state in schedule.items():
            # Parse "YYYY-MM-DD_slot" format
            try:
                date_str, slot_str = key.split("_")
                slot_index = int(slot_str)

                hour = slot_index // 4
                minute = (slot_index % 4) * 15
                time_str = f"{hour:02d}:{minute:02d}"

                scheduled_times.append(
                    {
                        "date": date_str,
                        "time": time_str,
                        "datetime": f"{date_str} {time_str}",
                        "slot": slot_index,
                        "state": "on" if state else "off",
                    }
                )
            except (ValueError, AttributeError):
                # Skip invalid keys
                continue

        # Sort by date and time
        scheduled_times.sort(key=lambda x: x["datetime"])

        attrs["scheduled_overrides"] = scheduled_times
        attrs["scheduled_overrides_count"] = len(scheduled_times)

        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success and self.coordinator.data is not None
        )

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"Nordpool Scheduler - {self._scheduler_name}",
            "manufacturer": "Nordpool",
            "model": "Price Scheduler",
            "sw_version": "1.0.0",
        }
