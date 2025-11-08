"""Tests for multiple entity domain support."""

import pytest
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler.const import (
    CONF_DEFAULT_STATE,
    CONF_SCHEDULER_NAME,
    CONF_TARGET_SWITCH,
    DEFAULT_STATE_OFF,
    DOMAIN,
)


@pytest.mark.parametrize(
    ("entity_domain", "entity_id"),
    [
        ("switch", "switch.test_device"),
        ("input_boolean", "input_boolean.test_toggle"),
        ("light", "light.test_light"),
        ("fan", "fan.test_fan"),
        ("climate", "climate.test_climate"),
    ],
)
async def test_setup_with_different_domains(
    hass: HomeAssistant,
    mock_aiohttp_session,
    entity_domain: str,
    entity_id: str,
) -> None:
    """Test that integration sets up correctly with different entity domains."""
    # Create mock entity
    hass.states.async_set(entity_id, STATE_OFF)

    # Create config entry for this entity
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SCHEDULER_NAME: f"test_{entity_domain}",
            CONF_TARGET_SWITCH: entity_id,
            CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
        },
        entry_id=f"test_{entity_domain}_entry",
        unique_id=f"test_{entity_domain}_{entity_id}",
    )
    entry.add_to_hass(hass)

    # Setup integration
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Verify entry is loaded
    assert entry.state.name == "LOADED"
    assert entry.entry_id in hass.data[DOMAIN]


@pytest.mark.parametrize(
    ("entity_domain", "entity_id"),
    [
        ("switch", "switch.test_device"),
        ("input_boolean", "input_boolean.test_toggle"),
        ("light", "light.test_light"),
        ("fan", "fan.test_fan"),
        ("climate", "climate.test_climate"),
    ],
)
async def test_domain_extracted_correctly_from_entity_id(
    hass: HomeAssistant,
    mock_aiohttp_session,
    entity_domain: str,
    entity_id: str,
) -> None:
    """Test that domain is correctly extracted from entity_id for automation."""
    # Create mock entity
    hass.states.async_set(entity_id, STATE_OFF)

    # Create config entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SCHEDULER_NAME: f"test_{entity_domain}",
            CONF_TARGET_SWITCH: entity_id,
            CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
        },
        entry_id=f"test_{entity_domain}_entry",
        unique_id=f"test_{entity_domain}_{entity_id}",
    )
    entry.add_to_hass(hass)

    # Setup integration
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Verify entity_id is stored correctly
    entry_data = hass.data[DOMAIN][entry.entry_id]
    stored_entity_id = entry_data["config"][CONF_TARGET_SWITCH]
    assert stored_entity_id == entity_id

    # Verify domain extraction works correctly
    extracted_domain = stored_entity_id.split(".")[0]
    assert extracted_domain == entity_domain


async def test_multiple_domains_simultaneously(
    hass: HomeAssistant,
    mock_aiohttp_session,
) -> None:
    """Test multiple entities of different domains controlled simultaneously."""
    entities = [
        ("switch", "switch.test_switch"),
        ("input_boolean", "input_boolean.test_toggle"),
        ("light", "light.test_light"),
        ("fan", "fan.test_fan"),
        ("climate", "climate.test_climate"),
    ]

    entries = []

    # Create and setup all entries
    for domain_name, entity_id in entities:
        hass.states.async_set(entity_id, STATE_OFF)

        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_SCHEDULER_NAME: f"scheduler_{domain_name}",
                CONF_TARGET_SWITCH: entity_id,
                CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
            },
            entry_id=f"entry_{domain_name}",
            unique_id=f"scheduler_{domain_name}_{entity_id}",
        )
        entry.add_to_hass(hass)
        entries.append((domain_name, entity_id, entry))

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Verify all entries are loaded
    for _domain_name, entity_id, entry in entries:
        assert entry.state.name == "LOADED"
        assert entry.entry_id in hass.data[DOMAIN]

        # Verify correct entity is configured
        entry_data = hass.data[DOMAIN][entry.entry_id]
        assert entry_data["config"][CONF_TARGET_SWITCH] == entity_id

    # All entries should share the same coordinator
    coordinator = hass.data[DOMAIN]["coordinator"]
    for _domain_name, _entity_id, entry in entries:
        entry_data = hass.data[DOMAIN][entry.entry_id]
        assert entry_data["coordinator"] == coordinator


@pytest.mark.parametrize(
    ("entity_domain", "entity_id"),
    [
        ("switch", "switch.test_device"),
        ("input_boolean", "input_boolean.test_toggle"),
        ("light", "light.test_light"),
        ("fan", "fan.test_fan"),
        ("climate", "climate.test_climate"),
    ],
)
async def test_service_set_schedule_with_different_domains(
    hass: HomeAssistant,
    mock_aiohttp_session,
    entity_domain: str,
    entity_id: str,
) -> None:
    """Test set_schedule service works with different entity domains."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from tests.conftest import get_schedule_key

    hass.states.async_set(entity_id, STATE_OFF)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SCHEDULER_NAME: f"test_{entity_domain}",
            CONF_TARGET_SWITCH: entity_id,
            CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
        },
        entry_id=f"test_{entity_domain}_entry",
        unique_id=f"test_{entity_domain}_{entity_id}",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Get tomorrow's date for testing
    riga_tz = ZoneInfo("Europe/Riga")
    tomorrow = (datetime.now(riga_tz).date() + timedelta(days=1)).isoformat()

    # Set schedule for multiple slots on tomorrow
    await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            "entry_id": entry.entry_id,
            "date": tomorrow,
            "slots": {
                "0": True,
                "1": True,
                "2": False,
                "10": True,
            },
        },
        blocking=True,
    )

    # Verify schedule was set correctly
    entry_data = hass.data[DOMAIN][entry.entry_id]
    assert entry_data["schedule"][get_schedule_key(0, days_ahead=1)] is True
    assert entry_data["schedule"][get_schedule_key(1, days_ahead=1)] is True
    assert entry_data["schedule"][get_schedule_key(2, days_ahead=1)] is False
    assert entry_data["schedule"][get_schedule_key(10, days_ahead=1)] is True


async def test_domain_extraction_from_entity_id(
    hass: HomeAssistant,
    mock_aiohttp_session,
) -> None:
    """Test that domain is correctly extracted from entity_id."""
    test_cases = [
        ("switch.my_switch", "switch"),
        ("input_boolean.my_toggle", "input_boolean"),
        ("light.bedroom_light", "light"),
        ("fan.ceiling_fan", "fan"),
        ("climate.thermostat", "climate"),
    ]

    for entity_id, expected_domain in test_cases:
        hass.states.async_set(entity_id, STATE_OFF)

        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_SCHEDULER_NAME: f"test_{expected_domain}",
                CONF_TARGET_SWITCH: entity_id,
                CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
            },
            entry_id=f"test_{expected_domain}_entry",
            unique_id=f"test_{expected_domain}_{entity_id}",
        )
        entry.add_to_hass(hass)

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Verify entity_id is stored correctly
        entry_data = hass.data[DOMAIN][entry.entry_id]
        stored_entity_id = entry_data["config"][CONF_TARGET_SWITCH]
        assert stored_entity_id == entity_id

        # Extract domain and verify
        extracted_domain = stored_entity_id.split(".")[0]
        assert extracted_domain == expected_domain

        # Cleanup for next iteration
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
