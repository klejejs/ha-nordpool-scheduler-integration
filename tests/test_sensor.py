"""Tests for the sensor platform."""

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import async_update_entity
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler.const import DOMAIN


async def test_sensor_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test sensor setup."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Check that sensor is created
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )

    # Filter for sensor entities only
    sensor_entries = [e for e in entries if e.domain == "sensor"]
    assert len(sensor_entries) == 1
    assert "electricity_price" in sensor_entries[0].unique_id


async def test_sensor_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test sensor state."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get sensor entity ID from registry
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )
    sensor_entries = [e for e in entries if e.domain == "sensor"]
    assert len(sensor_entries) > 0
    sensor_entity_id = sensor_entries[0].entity_id

    state = hass.states.get(sensor_entity_id)

    assert state is not None
    # Sensor might be unavailable if coordinator hasn't fetched data yet
    # but it should exist

    # Check attributes
    assert "prices" in state.attributes
    assert "current_slot" in state.attributes
    assert "entry_id" in state.attributes
    assert state.attributes["entry_id"] == mock_config_entry.entry_id


async def test_sensor_attributes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test sensor attributes include statistics."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get sensor entity ID from registry
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )
    sensor_entries = [e for e in entries if e.domain == "sensor"]
    assert len(sensor_entries) > 0
    sensor_entity_id = sensor_entries[0].entity_id

    state = hass.states.get(sensor_entity_id)

    # Prices may not be loaded in test, so we just check the structure
    assert "prices" in state.attributes
    assert isinstance(state.attributes["prices"], list)


async def test_sensor_device_info(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test sensor device info."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get entity registry
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )

    # Filter for sensor entities only
    sensor_entries = [e for e in entries if e.domain == "sensor"]
    assert len(sensor_entries) == 1
    sensor_entry = sensor_entries[0]

    # Check device info
    assert sensor_entry.device_id is not None


async def test_sensor_target_entity_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test that sensor includes target entity current state."""
    mock_config_entry.add_to_hass(hass)

    # Set the target switch to a known state
    hass.states.async_set("switch.test_switch", STATE_ON)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get sensor entity ID from registry
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )
    sensor_entries = [e for e in entries if e.domain == "sensor"]
    assert len(sensor_entries) > 0
    sensor_entity_id = sensor_entries[0].entity_id

    state = hass.states.get(sensor_entity_id)
    assert state is not None

    # Check target_entity_state attribute
    assert "target_entity_state" in state.attributes
    assert state.attributes["target_entity_state"] == STATE_ON

    # Change the target switch state
    hass.states.async_set("switch.test_switch", STATE_OFF)
    await hass.async_block_till_done()

    # Force sensor to update
    await async_update_entity(hass, sensor_entity_id)
    await hass.async_block_till_done()

    state = hass.states.get(sensor_entity_id)
    assert state.attributes["target_entity_state"] == STATE_OFF


async def test_sensor_scheduled_overrides_empty(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test that sensor shows empty scheduled_overrides when no schedule is set."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get sensor entity ID from registry
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )
    sensor_entries = [e for e in entries if e.domain == "sensor"]
    assert len(sensor_entries) > 0
    sensor_entity_id = sensor_entries[0].entity_id

    state = hass.states.get(sensor_entity_id)
    assert state is not None

    # Check scheduled_overrides attributes
    assert "scheduled_overrides" in state.attributes
    assert "scheduled_overrides_count" in state.attributes
    assert state.attributes["scheduled_overrides"] == []
    assert state.attributes["scheduled_overrides_count"] == 0


async def test_sensor_scheduled_overrides_with_schedule(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test that sensor shows scheduled_overrides when schedule is set."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get sensor entity ID from registry first
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )
    sensor_entries = [e for e in entries if e.domain == "sensor"]
    assert len(sensor_entries) > 0
    sensor_entity_id = sensor_entries[0].entity_id

    # Get tomorrow's date for testing
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    riga_tz = ZoneInfo("Europe/Riga")
    tomorrow = (datetime.now(riga_tz).date() + timedelta(days=1)).isoformat()

    # Set a schedule with multiple slots on tomorrow
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slots": {
                "0": True,  # 00:00
                "4": True,  # 01:00
                "8": False,  # 02:00
                "20": True,  # 05:00
            },
        },
        blocking=True,
    )

    # Force sensor to update
    await async_update_entity(hass, sensor_entity_id)
    await hass.async_block_till_done()

    state = hass.states.get(sensor_entity_id)
    assert state is not None

    # Check scheduled_overrides attributes
    assert "scheduled_overrides" in state.attributes
    assert "scheduled_overrides_count" in state.attributes

    scheduled_overrides = state.attributes["scheduled_overrides"]
    assert len(scheduled_overrides) == 4
    assert state.attributes["scheduled_overrides_count"] == 4

    # Verify the schedule is sorted and formatted correctly
    assert scheduled_overrides[0]["time"] == "00:00"
    assert scheduled_overrides[0]["slot"] == 0
    assert scheduled_overrides[0]["state"] == "on"

    assert scheduled_overrides[1]["time"] == "01:00"
    assert scheduled_overrides[1]["slot"] == 4
    assert scheduled_overrides[1]["state"] == "on"

    assert scheduled_overrides[2]["time"] == "02:00"
    assert scheduled_overrides[2]["slot"] == 8
    assert scheduled_overrides[2]["state"] == "off"

    assert scheduled_overrides[3]["time"] == "05:00"
    assert scheduled_overrides[3]["slot"] == 20
    assert scheduled_overrides[3]["state"] == "on"


async def test_sensor_scheduled_overrides_after_clear(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test that sensor clears scheduled_overrides when schedule is cleared."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get tomorrow's date for testing
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    riga_tz = ZoneInfo("Europe/Riga")
    tomorrow = (datetime.now(riga_tz).date() + timedelta(days=1)).isoformat()

    # Set a schedule first on tomorrow
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slots": {
                "0": True,
                "4": True,
            },
        },
        blocking=True,
    )

    # Get sensor entity ID from registry
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )
    sensor_entries = [e for e in entries if e.domain == "sensor"]
    assert len(sensor_entries) > 0
    sensor_entity_id = sensor_entries[0].entity_id

    # Force sensor to update
    await async_update_entity(hass, sensor_entity_id)
    await hass.async_block_till_done()

    # Verify schedule is set
    state = hass.states.get(sensor_entity_id)
    assert state.attributes["scheduled_overrides_count"] == 2

    # Clear the schedule
    await hass.services.async_call(
        DOMAIN,
        "clear_schedule",
        {"entry_id": mock_config_entry.entry_id},
        blocking=True,
    )

    # Force sensor to update
    await async_update_entity(hass, sensor_entity_id)
    await hass.async_block_till_done()

    # Verify schedule is cleared
    state = hass.states.get(sensor_entity_id)
    assert state.attributes["scheduled_overrides"] == []
    assert state.attributes["scheduled_overrides_count"] == 0


async def test_sensor_time_formatting(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test that scheduled times are formatted correctly (HH:MM)."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get sensor entity ID from registry first
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )
    sensor_entries = [e for e in entries if e.domain == "sensor"]
    assert len(sensor_entries) > 0
    sensor_entity_id = sensor_entries[0].entity_id

    # Get tomorrow's date for testing
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    riga_tz = ZoneInfo("Europe/Riga")
    tomorrow = (datetime.now(riga_tz).date() + timedelta(days=1)).isoformat()

    # Set schedules for various times to test formatting on tomorrow
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slots": {
                "0": True,  # 00:00
                "1": True,  # 00:15
                "37": True,  # 09:15
                "95": True,  # 23:45
            },
        },
        blocking=True,
    )

    # Force sensor to update
    await async_update_entity(hass, sensor_entity_id)
    await hass.async_block_till_done()

    state = hass.states.get(sensor_entity_id)
    scheduled_overrides = state.attributes["scheduled_overrides"]

    # Verify time formatting with leading zeros
    times = [override["time"] for override in scheduled_overrides]
    assert "00:00" in times
    assert "00:15" in times
    assert "09:15" in times
    assert "23:45" in times


async def test_sensor_target_entity_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
) -> None:
    """Test sensor when target entity is unavailable."""
    mock_config_entry.add_to_hass(hass)

    # Don't create the target switch - it should be unavailable

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get sensor entity ID from registry
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )
    sensor_entries = [e for e in entries if e.domain == "sensor"]
    assert len(sensor_entries) > 0
    sensor_entity_id = sensor_entries[0].entity_id

    state = hass.states.get(sensor_entity_id)
    assert state is not None

    # Target entity should be unavailable
    assert "target_entity_state" in state.attributes
    assert state.attributes["target_entity_state"] == "unavailable"
