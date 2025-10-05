"""Tests for the Nordpool Scheduler integration."""


from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler.const import DOMAIN


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

    # Check that sensor is created
    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id,
    )
    assert len(entries) == 1
    assert entries[0].domain == "sensor"


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

    # Set schedule for specific slots
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entry_id": mock_config_entry.entry_id,
            "slots": {
                "0": True,
                "4": True,
                "8": False,
            },
        },
        blocking=True,
    )

    # Check that schedule was updated (schedule is now a dict)
    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert entry_data["schedule"][0] is True
    assert entry_data["schedule"][4] is True
    assert entry_data["schedule"][8] is False


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

    # Set some schedule first (schedule is now a dict)
    entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
    entry_data["schedule"][0] = True
    entry_data["schedule"][4] = True

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
