"""Tests for the config flow."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler.const import (
    CONF_DEFAULT_STATE,
    CONF_SCHEDULER_NAME,
    CONF_TARGET_SWITCH,
    DEFAULT_STATE_OFF,
    DOMAIN,
)


async def test_form(hass: HomeAssistant, mock_switch) -> None:
    """Test the config flow form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SCHEDULER_NAME: "test_scheduler",
            CONF_TARGET_SWITCH: "switch.test_switch",
            CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
        },
    )
    await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Nordpool Scheduler - test_scheduler"
    assert result2["data"] == {
        CONF_SCHEDULER_NAME: "test_scheduler",
        CONF_TARGET_SWITCH: "switch.test_switch",
        CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
    }


async def test_form_invalid_switch(hass: HomeAssistant) -> None:
    """Test invalid switch entity."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SCHEDULER_NAME: "test_scheduler",
            CONF_TARGET_SWITCH: "switch.nonexistent",
        },
    )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_switch"}


async def test_form_already_configured(hass: HomeAssistant, mock_switch) -> None:
    """Test that duplicate entries are not allowed."""
    # Create an existing entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SCHEDULER_NAME: "test_scheduler",
            CONF_TARGET_SWITCH: "switch.test_switch",
            CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
        },
        unique_id="test_scheduler_switch.test_switch",
    )
    entry.add_to_hass(hass)

    # Try to create a duplicate
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SCHEDULER_NAME: "test_scheduler",
            CONF_TARGET_SWITCH: "switch.test_switch",
        },
    )

    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


async def test_options_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_switch,
) -> None:
    """Test options flow."""
    mock_config_entry.add_to_hass(hass)

    # Set up a second switch for testing
    hass.states.async_set("switch.new_switch", "off")

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_TARGET_SWITCH: "switch.new_switch"},
    )

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_TARGET_SWITCH] == "switch.new_switch"
