"""Tests for the sensor, binary sensor and switch entities."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.nordpool_scheduler import _async_apply_slot
from custom_components.nordpool_scheduler.const import CONF_DEFAULT_STATE
from custom_components.nordpool_scheduler.util import slot_start_for

from .conftest import OSLO_TZ, hourly_day_prices
from .conftest import setup_scheduler_entry as _setup

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

SENSOR = "sensor.nordpool_scheduler_test_electricity_price"
SCHEDULED_ON = "binary_sensor.nordpool_scheduler_test_scheduled_on"
ENABLED_SWITCH = "switch.nordpool_scheduler_test_scheduler_enabled"


async def test_price_sensor(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The price sensor reports the current price with its unit and area."""
    await _setup(hass, mock_config_entry, nordpool_prices)

    state = hass.states.get(SENSOR)
    assert state is not None
    assert state.state != "unknown"
    assert state.attributes["unit_of_measurement"] == "EUR/kWh"
    assert state.attributes["area"] == "LV"
    assert state.attributes["vat_percent"] == 21


async def test_scheduled_on_binary_sensor_tracks_default(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """With no overrides, the binary sensor follows the configured default."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    assert hass.states.get(SCHEDULED_ON).state == "off"


async def test_scheduled_on_binary_sensor_tracks_default_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A default of ON is reflected with no overrides set."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_DEFAULT_STATE: "on"}
    )
    today = datetime.now(OSLO_TZ).date()
    nordpool_prices[today] = hourly_day_prices(today)
    nordpool_prices[today - timedelta(days=1)] = hourly_day_prices(today)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(SCHEDULED_ON).state == "on"


async def test_device_info_shared_across_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """All three entities belong to the same device."""
    await _setup(hass, mock_config_entry, nordpool_prices)

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    device_ids = {
        entity.device_id
        for entity in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
    }
    assert len(device_ids) == 1
    device = device_registry.async_get(next(iter(device_ids)))
    assert device is not None
    assert device.name == mock_config_entry.title


async def test_scheduler_enabled_switch_gates_control(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Turning the switch off stops the scheduler from calling services."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    assert hass.states.get(ENABLED_SWITCH).state == "on"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": ENABLED_SWITCH}, blocking=True
    )
    entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert entry.runtime_data.enabled is False

    calls = []
    hass.services.async_register(
        "input_boolean", "turn_on", lambda call: calls.append(call.service)
    )
    entry.runtime_data.schedule.set_slot(slot_start_for(datetime.now(UTC)), state=True)
    await _async_apply_slot(hass, entry, datetime.now(UTC))
    await hass.async_block_till_done()
    assert not calls
