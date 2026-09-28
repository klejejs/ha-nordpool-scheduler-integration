"""Tests for the config and options flows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler.const import (
    CONF_AREA,
    CONF_CONTROL_MODE,
    CONF_DEFAULT_STATE,
    CONF_NORDPOOL_ENTRY_ID,
    CONF_SCHEDULER_NAME,
    CONF_TARGET_ENTITY,
    CONF_VAT_PERCENT,
    CONTROL_MODE_ON_CHANGE,
    DOMAIN,
)

from .conftest import setup_scheduler_entry

if TYPE_CHECKING:
    from datetime import date

    from homeassistant.core import HomeAssistant


async def test_full_flow_single_area(
    hass: HomeAssistant, mock_nordpool_entry: MockConfigEntry, mock_target: str
) -> None:
    """The area step is skipped when the Nord Pool entry has one area."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SCHEDULER_NAME: "Test",
            CONF_TARGET_ENTITY: mock_target,
            CONF_DEFAULT_STATE: "off",
            "nordpool_config_entry_id": mock_nordpool_entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Nordpool Scheduler - Test"


async def test_flow_multi_area_requires_selection(
    hass: HomeAssistant, mock_target: str
) -> None:
    """With multiple areas configured, the user is asked to pick one."""
    entry = MockConfigEntry(
        domain="nordpool", data={"areas": ["LV", "LT"], "currency": "EUR"}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SCHEDULER_NAME: "Test",
            CONF_TARGET_ENTITY: mock_target,
            CONF_DEFAULT_STATE: "off",
            "nordpool_config_entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "area"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area": "LT"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_flow_invalid_target(
    hass: HomeAssistant, mock_nordpool_entry: MockConfigEntry
) -> None:
    """An entity that doesn't exist is rejected with an error, not an exception."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SCHEDULER_NAME: "Test",
            CONF_TARGET_ENTITY: "input_boolean.does_not_exist",
            CONF_DEFAULT_STATE: "off",
            "nordpool_config_entry_id": mock_nordpool_entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_target"}


async def test_flow_aborts_without_nordpool(hass: HomeAssistant) -> None:
    """Setting up a scheduler before Nord Pool is configured aborts cleanly."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nordpool_not_configured"


async def test_duplicate_target_aborts(
    hass: HomeAssistant,
    mock_nordpool_entry: MockConfigEntry,
    mock_config_entry: MockConfigEntry,
    mock_target: str,
) -> None:
    """A second scheduler for the same target entity is rejected."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SCHEDULER_NAME: "Another",
            CONF_TARGET_ENTITY: mock_config_entry.data[CONF_TARGET_ENTITY],
            CONF_DEFAULT_STATE: "off",
            "nordpool_config_entry_id": mock_nordpool_entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_updates_settings(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The options flow (previously a 500) saves target/default/mode/VAT."""
    await setup_scheduler_entry(hass, mock_config_entry, nordpool_prices)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_TARGET_ENTITY: mock_target,
            CONF_DEFAULT_STATE: "on",
            CONF_CONTROL_MODE: CONTROL_MODE_ON_CHANGE,
            CONF_VAT_PERCENT: 0,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert mock_config_entry.options[CONF_DEFAULT_STATE] == "on"
    assert mock_config_entry.options[CONF_VAT_PERCENT] == 0
    assert mock_config_entry.state.name == "LOADED"


async def test_options_flow_invalid_target(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """An invalid target in the options flow is a form error, not a crash."""
    await setup_scheduler_entry(hass, mock_config_entry, nordpool_prices)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_TARGET_ENTITY: "input_boolean.nope",
            CONF_DEFAULT_STATE: "off",
            CONF_CONTROL_MODE: CONTROL_MODE_ON_CHANGE,
            CONF_VAT_PERCENT: 21,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_target"}


async def test_options_flow_rejects_duplicate_target(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Retargeting to an entity another scheduler already controls is rejected."""
    await setup_scheduler_entry(hass, mock_config_entry, nordpool_prices)

    other_entity = "input_boolean.other_target"
    hass.states.async_set(other_entity, "off")
    other_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Nordpool Scheduler - Other",
        data={
            CONF_SCHEDULER_NAME: "Other",
            CONF_TARGET_ENTITY: other_entity,
            CONF_DEFAULT_STATE: "off",
            CONF_NORDPOOL_ENTRY_ID: mock_nordpool_entry.entry_id,
            CONF_AREA: "LV",
        },
        entry_id="other_scheduler_entry_id",
        unique_id=other_entity,
        version=2,
    )
    await setup_scheduler_entry(hass, other_entry, nordpool_prices)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_TARGET_ENTITY: other_entity,
            CONF_DEFAULT_STATE: "off",
            CONF_CONTROL_MODE: CONTROL_MODE_ON_CHANGE,
            CONF_VAT_PERCENT: 21,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "already_configured"}
    assert mock_config_entry.unique_id == mock_target


async def test_options_flow_retargeting_updates_unique_id(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Retargeting updates the entry's unique ID, freeing the old target."""
    await setup_scheduler_entry(hass, mock_config_entry, nordpool_prices)

    new_target = "input_boolean.new_target"
    hass.states.async_set(new_target, "off")

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_TARGET_ENTITY: new_target,
            CONF_DEFAULT_STATE: "off",
            CONF_CONTROL_MODE: CONTROL_MODE_ON_CHANGE,
            CONF_VAT_PERCENT: 21,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.unique_id == new_target

    # The old target is now free for a new scheduler to claim.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SCHEDULER_NAME: "Reclaimed",
            CONF_TARGET_ENTITY: mock_target,
            CONF_DEFAULT_STATE: "off",
            CONF_NORDPOOL_ENTRY_ID: mock_config_entry.data[CONF_NORDPOOL_ENTRY_ID],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
