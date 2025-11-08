"""Tests for the binary sensor platform."""

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler.const import DOMAIN


async def test_binary_sensor_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test binary sensor setup."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Check that binary sensor is created
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )

    # Should have 2 entities: sensor and binary_sensor
    assert len(entries) == 2

    # Find the binary sensor
    binary_sensor_entry = next(
        (e for e in entries if e.domain == "binary_sensor"),
        None,
    )
    assert binary_sensor_entry is not None
    assert binary_sensor_entry.unique_id == f"{mock_config_entry.entry_id}_target_state"


async def test_binary_sensor_tracks_target_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test that binary sensor tracks target entity state."""
    # Set up with switch initially OFF
    hass.states.async_set("switch.test_switch", STATE_OFF)

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get the binary sensor state
    binary_sensor_id = "binary_sensor.nordpool_scheduler_test_scheduler_target_state"
    binary_sensor_state = hass.states.get(binary_sensor_id)
    assert binary_sensor_state is not None
    assert binary_sensor_state.state == STATE_OFF

    # Turn switch ON
    hass.states.async_set("switch.test_switch", STATE_ON)
    await hass.async_block_till_done()

    # Binary sensor should now be ON
    binary_sensor_state = hass.states.get(binary_sensor_id)
    assert binary_sensor_state.state == STATE_ON

    # Turn switch OFF again
    hass.states.async_set("switch.test_switch", STATE_OFF)
    await hass.async_block_till_done()

    # Binary sensor should now be OFF
    binary_sensor_state = hass.states.get(binary_sensor_id)
    assert binary_sensor_state.state == STATE_OFF


async def test_binary_sensor_attributes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test binary sensor attributes."""
    hass.states.async_set("switch.test_switch", STATE_ON)

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get the binary sensor state
    binary_sensor_id = "binary_sensor.nordpool_scheduler_test_scheduler_target_state"
    binary_sensor_state = hass.states.get(binary_sensor_id)
    assert binary_sensor_state is not None

    # Check attributes
    assert binary_sensor_state.attributes["target_entity"] == "switch.test_switch"
    assert binary_sensor_state.attributes["target_state"] == STATE_ON
    assert binary_sensor_state.attributes["entry_id"] == mock_config_entry.entry_id
    assert binary_sensor_state.attributes["scheduler_name"] == "test_scheduler"


async def test_binary_sensor_unavailable_when_target_missing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
) -> None:
    """Test binary sensor is unavailable when target entity doesn't exist."""
    # Don't create the target switch
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get the binary sensor state
    binary_sensor_id = "binary_sensor.nordpool_scheduler_test_scheduler_target_state"
    binary_sensor_state = hass.states.get(binary_sensor_id)
    assert binary_sensor_state is not None
    assert binary_sensor_state.state == "unavailable"


async def test_binary_sensor_device_info(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test binary sensor device info."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get device registry
    from homeassistant.helpers import device_registry as dr

    device_registry = dr.async_get(hass)

    # Find device
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, mock_config_entry.entry_id)},
    )
    assert device is not None
    assert device.name == "Nordpool Scheduler - test_scheduler"
    assert device.manufacturer == "Nordpool"
    assert device.model == "Price Scheduler"
