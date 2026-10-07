"""Tests for the set_slots and clear_schedule services."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError

from custom_components.nordpool_scheduler.const import DOMAIN
from custom_components.nordpool_scheduler.util import slot_start_for

from .conftest import OSLO_TZ
from .conftest import setup_scheduler_entry as _setup

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_set_slots_and_clear(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Slots can be set to on/off/default and cleared in bulk."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    start = slot_start_for(datetime.now(OSLO_TZ)) + timedelta(minutes=15)

    await hass.services.async_call(
        DOMAIN,
        "set_slots",
        {
            "config_entry": mock_config_entry.entry_id,
            "slots": [{"start": start.isoformat(), "state": "on"}],
        },
        blocking=True,
    )
    entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert entry.runtime_data.schedule.get(start) is True

    await hass.services.async_call(
        DOMAIN,
        "set_slots",
        {
            "config_entry": mock_config_entry.entry_id,
            "slots": [{"start": start.isoformat(), "state": "default"}],
        },
        blocking=True,
    )
    assert entry.runtime_data.schedule.get(start) is None

    entry.runtime_data.schedule.set_slot(start, state=True)
    await hass.services.async_call(
        DOMAIN,
        "clear_schedule",
        {"config_entry": mock_config_entry.entry_id},
        blocking=True,
    )
    assert entry.runtime_data.schedule.as_dict() == {}


async def test_set_slots_on_current_slot_syncs_target(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Editing the current slot undoes a manual toggle; a later slot doesn't."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    now_slot = slot_start_for(datetime.now(OSLO_TZ))
    next_slot = now_slot + timedelta(minutes=15)
    hass.states.async_set(mock_target, "on")

    await hass.services.async_call(
        DOMAIN,
        "set_slots",
        {
            "config_entry": mock_config_entry.entry_id,
            "slots": [{"start": next_slot.isoformat(), "state": "off"}],
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(mock_target).state == "on"

    await hass.services.async_call(
        DOMAIN,
        "set_slots",
        {
            "config_entry": mock_config_entry.entry_id,
            "slots": [{"start": now_slot.isoformat(), "state": "off"}],
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(mock_target).state == "off"


async def test_set_slots_rejects_unaligned_start(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A start time not on a 15-minute boundary is rejected."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    bad_start = slot_start_for(datetime.now(OSLO_TZ)) + timedelta(minutes=5)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_slots",
            {
                "config_entry": mock_config_entry.entry_id,
                "slots": [{"start": bad_start.isoformat(), "state": "on"}],
            },
            blocking=True,
        )


async def test_set_slots_rejects_past_start(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A slot in the past is rejected."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    past = slot_start_for(datetime.now(OSLO_TZ)) - timedelta(minutes=15)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_slots",
            {
                "config_entry": mock_config_entry.entry_id,
                "slots": [{"start": past.isoformat(), "state": "on"}],
            },
            blocking=True,
        )


async def test_set_slots_rejects_unknown_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """An unknown config entry id is a clean validation error, not a 500."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    start = slot_start_for(datetime.now(OSLO_TZ))

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_slots",
            {
                "config_entry": "does_not_exist",
                "slots": [{"start": start.isoformat(), "state": "on"}],
            },
            blocking=True,
        )


async def test_set_slots_rejects_bad_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """An invalid state literal fails schema validation before the handler runs."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    start = slot_start_for(datetime.now(OSLO_TZ))

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "set_slots",
            {
                "config_entry": mock_config_entry.entry_id,
                "slots": [{"start": start.isoformat(), "state": "maybe"}],
            },
            blocking=True,
        )


async def test_set_slots_rejects_prices_entry(
    hass: HomeAssistant,
    mock_prices_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
) -> None:
    """A prices entry has no schedule to set."""
    await _setup(hass, mock_prices_entry, nordpool_prices)
    start = slot_start_for(datetime.now(OSLO_TZ))

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_slots",
            {
                "config_entry": mock_prices_entry.entry_id,
                "slots": [{"start": start.isoformat(), "state": "on"}],
            },
            blocking=True,
        )
