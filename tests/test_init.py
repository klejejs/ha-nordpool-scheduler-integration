"""Tests for the Nordpool Scheduler integration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler.const import DOMAIN
from tests.conftest import get_schedule_key


async def test_setup_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test setting up the integration."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Check that the entry is loaded
    assert mock_config_entry.state.name == "LOADED"

    # Check that data is stored
    assert DOMAIN in hass.data
    assert mock_config_entry.entry_id in hass.data[DOMAIN]

    # Check that coordinator exists
    assert "coordinator" in hass.data[DOMAIN]

    # Check that entities are created
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        mock_config_entry.entry_id,
    )
    # Should have both sensor and binary_sensor
    assert len(entries) == 2
    domains = {e.domain for e in entries}
    assert "sensor" in domains
    assert "binary_sensor" in domains


async def test_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test unloading the integration."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Check that the entry is unloaded
    assert mock_config_entry.state.name == "NOT_LOADED"

    # Check that data is removed
    assert mock_config_entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_services_registered(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test that services are registered."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Check that services are registered
    assert hass.services.has_service(DOMAIN, "set_schedule")
    assert hass.services.has_service(DOMAIN, "set_slot")
    assert hass.services.has_service(DOMAIN, "clear_schedule")
    assert hass.services.has_service(DOMAIN, "get_schedule")


async def test_set_schedule_service(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test the set_schedule service."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get tomorrow's date for testing (to avoid past-time cleanup)
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    riga_tz = ZoneInfo("Europe/Riga")
    tomorrow = (datetime.now(riga_tz).date() + timedelta(days=1)).isoformat()

    # Set schedule for specific slots on tomorrow
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slots": {
                "0": True,
                "4": True,
                "8": False,
            },
        },
        blocking=True,
    )

    # Check that schedule was updated (schedule is now date-based dict)
    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert entry_data["schedule"][get_schedule_key(0, days_ahead=1)] is True
    assert entry_data["schedule"][get_schedule_key(4, days_ahead=1)] is True
    assert entry_data["schedule"][get_schedule_key(8, days_ahead=1)] is False


async def test_clear_schedule_service(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test the clear_schedule service."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Set some schedule first (schedule is now date-based dict) - use tomorrow's date
    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    entry_data["schedule"][get_schedule_key(0, days_ahead=1)] = True
    entry_data["schedule"][get_schedule_key(4, days_ahead=1)] = True

    # Clear schedule
    await hass.services.async_call(
        DOMAIN,
        "clear_schedule",
        {"entry_id": mock_config_entry.entry_id},
        blocking=True,
    )

    # Check that schedule was cleared (should be empty dict)
    assert entry_data["schedule"] == {}


async def test_multiple_instances(
    hass: HomeAssistant,
    mock_aiohttp_session,
) -> None:
    """Test that multiple instances can be created."""
    # Create first instance
    hass.states.async_set("switch.test_switch_1", "off")
    from custom_components.nordpool_scheduler.const import (
        CONF_DEFAULT_STATE,
        DEFAULT_STATE_OFF,
    )

    entry1 = MockConfigEntry(
        domain=DOMAIN,
        data={
            "scheduler_name": "scheduler1",
            "target_switch": "switch.test_switch_1",
            CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
        },
        entry_id="entry1",
        unique_id="scheduler1_switch.test_switch_1",
    )
    entry1.add_to_hass(hass)

    # Set up first entry
    result1 = await hass.config_entries.async_setup(entry1.entry_id)
    await hass.async_block_till_done()
    assert result1

    # Create second instance AFTER first is set up
    hass.states.async_set("switch.test_switch_2", "off")
    entry2 = MockConfigEntry(
        domain=DOMAIN,
        data={
            "scheduler_name": "scheduler2",
            "target_switch": "switch.test_switch_2",
            CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
        },
        entry_id="entry2",
        unique_id="scheduler2_switch.test_switch_2",
    )
    entry2.add_to_hass(hass)

    # Set up second entry
    result2 = await hass.config_entries.async_setup(entry2.entry_id)
    await hass.async_block_till_done()
    assert result2

    # Check that both are loaded
    assert entry1.entry_id in hass.data[DOMAIN]
    assert entry2.entry_id in hass.data[DOMAIN]

    # They should share the same coordinator
    coordinator1 = hass.data[DOMAIN][entry1.entry_id]["coordinator"]
    coordinator2 = hass.data[DOMAIN][entry2.entry_id]["coordinator"]
    assert coordinator1 == coordinator2


async def test_set_slot_service(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test the set_slot service."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get tomorrow's date for testing
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    riga_tz = ZoneInfo("Europe/Riga")
    tomorrow = (datetime.now(riga_tz).date() + timedelta(days=1)).isoformat()

    # Set a single slot on tomorrow
    await hass.services.async_call(
        DOMAIN,
        "set_slot",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slot_index": 10,
            "enabled": True,
        },
        blocking=True,
    )

    # Check that the slot was updated
    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert entry_data["schedule"][get_schedule_key(10, days_ahead=1)] is True

    # Update the same slot to disabled
    await hass.services.async_call(
        DOMAIN,
        "set_slot",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slot_index": 10,
            "enabled": False,
        },
        blocking=True,
    )

    # Check that the slot was updated
    assert entry_data["schedule"][get_schedule_key(10, days_ahead=1)] is False

    # Set multiple individual slots
    await hass.services.async_call(
        DOMAIN,
        "set_slot",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slot_index": 5,
            "enabled": True,
        },
        blocking=True,
    )

    await hass.services.async_call(
        DOMAIN,
        "set_slot",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slot_index": 15,
            "enabled": False,
        },
        blocking=True,
    )

    # Check all slots
    assert entry_data["schedule"][get_schedule_key(5, days_ahead=1)] is True
    assert entry_data["schedule"][get_schedule_key(10, days_ahead=1)] is False
    assert entry_data["schedule"][get_schedule_key(15, days_ahead=1)] is False


async def test_get_schedule_service(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test the get_schedule service returns the schedule."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get tomorrow's date for testing
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    riga_tz = ZoneInfo("Europe/Riga")
    tomorrow = (datetime.now(riga_tz).date() + timedelta(days=1)).isoformat()

    # Set schedule for specific slots on tomorrow
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slots": {
                "0": True,
                "4": True,
                "8": False,
                "12": True,
            },
        },
        blocking=True,
    )

    # Get the schedule
    response = await hass.services.async_call(
        DOMAIN,
        "get_schedule",
        {"entry_id": mock_config_entry.entry_id},
        blocking=True,
        return_response=True,
    )

    # Check that the response contains the schedule (now grouped by date)
    assert response is not None
    assert "schedule" in response
    schedule_by_date = response["schedule"]

    assert tomorrow in schedule_by_date
    schedule = schedule_by_date[tomorrow]
    assert schedule[0] is True
    assert schedule[4] is True
    assert schedule[8] is False
    assert schedule[12] is True


async def test_schedule_persistence(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test that schedule persists across integration reload."""
    mock_config_entry.add_to_hass(hass)

    # Set up the integration
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get tomorrow's date for testing
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    riga_tz = ZoneInfo("Europe/Riga")
    tomorrow = (datetime.now(riga_tz).date() + timedelta(days=1)).isoformat()

    # Set schedule for specific slots on tomorrow
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slots": {
                "10": True,
                "20": False,
                "30": True,
            },
        },
        blocking=True,
    )

    # Verify schedule is set
    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert entry_data["schedule"][get_schedule_key(10, days_ahead=1)] is True
    assert entry_data["schedule"][get_schedule_key(20, days_ahead=1)] is False
    assert entry_data["schedule"][get_schedule_key(30, days_ahead=1)] is True

    # Unload the integration (simulating HA restart)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Reload the integration
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Verify schedule was restored from persistence
    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert entry_data["schedule"][get_schedule_key(10, days_ahead=1)] is True
    assert entry_data["schedule"][get_schedule_key(20, days_ahead=1)] is False
    assert entry_data["schedule"][get_schedule_key(30, days_ahead=1)] is True


async def test_schedule_persistence_with_set_slot(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test that individual slot changes persist across integration reload."""
    mock_config_entry.add_to_hass(hass)

    # Set up the integration
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get tomorrow's date for testing
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    riga_tz = ZoneInfo("Europe/Riga")
    tomorrow = (datetime.now(riga_tz).date() + timedelta(days=1)).isoformat()

    # Set individual slots on tomorrow
    await hass.services.async_call(
        DOMAIN,
        "set_slot",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slot_index": 45,
            "enabled": True,
        },
        blocking=True,
    )

    # Unload and reload
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Verify slot was restored
    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert entry_data["schedule"][get_schedule_key(45, days_ahead=1)] is True


async def test_schedule_persistence_clear(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiohttp_session,
    mock_switch,
) -> None:
    """Test that clearing schedule persists across integration reload."""
    mock_config_entry.add_to_hass(hass)

    # Set up the integration
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Get tomorrow's date for testing
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    riga_tz = ZoneInfo("Europe/Riga")
    tomorrow = (datetime.now(riga_tz).date() + timedelta(days=1)).isoformat()

    # Set a schedule on tomorrow
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entry_id": mock_config_entry.entry_id,
            "date": tomorrow,
            "slots": {"5": True, "15": False},
        },
        blocking=True,
    )

    # Clear the schedule
    await hass.services.async_call(
        DOMAIN,
        "clear_schedule",
        {"entry_id": mock_config_entry.entry_id},
        blocking=True,
    )

    # Unload and reload
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Verify schedule is still empty after reload
    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert entry_data["schedule"] == {}
