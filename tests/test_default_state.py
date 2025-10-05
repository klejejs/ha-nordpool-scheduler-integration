"""Tests for default state functionality."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler.const import (
    CONF_DEFAULT_STATE,
    CONF_SCHEDULER_NAME,
    CONF_TARGET_SWITCH,
    DEFAULT_STATE_OFF,
    DEFAULT_STATE_ON,
    DOMAIN,
)


async def test_default_state_off(
    hass: HomeAssistant,
    mock_aiohttp_session,
) -> None:
    """Test default state OFF behavior."""
    # Create switch
    hass.states.async_set("switch.test_switch", "off")

    # Create entry with default state OFF
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SCHEDULER_NAME: "test",
            CONF_TARGET_SWITCH: "switch.test_switch",
            CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
        },
        entry_id="test_entry",
        unique_id="test_switch.test_switch",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Check that entry data has the correct default state
    entry_data = hass.data[DOMAIN][entry.entry_id]
    assert entry_data["config"][CONF_DEFAULT_STATE] == DEFAULT_STATE_OFF

    # Schedule should be empty dict initially
    assert entry_data["schedule"] == {}


async def test_default_state_on(
    hass: HomeAssistant,
    mock_aiohttp_session,
) -> None:
    """Test default state ON behavior."""
    # Create switch
    hass.states.async_set("switch.test_switch", "off")

    # Create entry with default state ON
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SCHEDULER_NAME: "test",
            CONF_TARGET_SWITCH: "switch.test_switch",
            CONF_DEFAULT_STATE: DEFAULT_STATE_ON,
        },
        entry_id="test_entry",
        unique_id="test_switch.test_switch",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Check that entry data has the correct default state
    entry_data = hass.data[DOMAIN][entry.entry_id]
    assert entry_data["config"][CONF_DEFAULT_STATE] == DEFAULT_STATE_ON

    # Schedule should be empty dict initially
    assert entry_data["schedule"] == {}


async def test_schedule_overrides_default(
    hass: HomeAssistant,
    mock_aiohttp_session,
) -> None:
    """Test that scheduled slots override the default state."""
    # Create switch
    hass.states.async_set("switch.test_switch", "off")

    # Create entry with default state ON
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SCHEDULER_NAME: "test",
            CONF_TARGET_SWITCH: "switch.test_switch",
            CONF_DEFAULT_STATE: DEFAULT_STATE_ON,
        },
        entry_id="test_entry",
        unique_id="test_switch.test_switch",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Set schedule to turn OFF at slot 0 (override default ON)
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entry_id": entry.entry_id,
            "slots": {
                "0": False,  # Explicitly OFF
                "4": True,  # Explicitly ON
            },
        },
        blocking=True,
    )

    # Check that schedule has overrides
    entry_data = hass.data[DOMAIN][entry.entry_id]
    assert entry_data["schedule"][0] is False  # Override to OFF
    assert entry_data["schedule"][4] is True  # Override to ON
    assert 8 not in entry_data["schedule"]  # Not scheduled, will use default (ON)
