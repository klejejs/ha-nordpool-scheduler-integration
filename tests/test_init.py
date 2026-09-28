"""Tests for Nordpool Scheduler setup, unload, migration and slot handling."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler import _async_apply_slot
from custom_components.nordpool_scheduler.const import (
    CONF_CONTROL_MODE,
    CONF_TARGET_ENTITY,
    CONTROL_MODE_ENFORCE,
    DOMAIN,
)

from .conftest import setup_scheduler_entry as _setup

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_setup_creates_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Setting up an entry creates the sensor, binary sensor and switch."""
    await _setup(hass, mock_config_entry, nordpool_prices)

    assert mock_config_entry.state.name == "LOADED"

    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    assert len(entries) == 3


async def test_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Unloading stops updates and cleans up."""
    await _setup(hass, mock_config_entry, nordpool_prices)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state.name == "NOT_LOADED"


async def test_migrate_v1_entry_fails(hass: HomeAssistant) -> None:
    """A pre-rewrite (CSV-based) entry can't be migrated automatically."""
    old_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Nordpool Scheduler - Old",
        data={
            "scheduler_name": "Old",
            "target_switch": "switch.old",
            "default_state": "off",
        },
        version=1,
    )
    old_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(old_entry.entry_id)
    await hass.async_block_till_done()
    assert old_entry.state.name == "MIGRATION_ERROR"


async def test_apply_slot_skips_when_target_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
) -> None:
    """No service call is made while the target entity is unavailable."""
    hass.states.async_set(mock_config_entry.data[CONF_TARGET_ENTITY], "unavailable")
    await _setup(hass, mock_config_entry, nordpool_prices)

    calls: list[dict] = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, lambda event: calls.append(event.data))
    await _async_apply_slot(hass, mock_config_entry, datetime.now(UTC))
    await hass.async_block_till_done()
    assert not calls


async def test_on_change_mode_only_calls_on_transition(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """In on_change mode, repeating the same desired state doesn't call the service."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    runtime = entry.runtime_data

    calls: list[str] = []
    hass.services.async_register(
        "input_boolean", "turn_on", lambda call: calls.append(call.service)
    )

    now = datetime.now(UTC)
    runtime.schedule.set_slot(_slot_start(now), state=True)

    await _async_apply_slot(hass, entry, now)
    await hass.async_block_till_done()
    assert calls == ["turn_on"]

    # Same slot, same desired state -> no repeat call in on_change mode.
    await _async_apply_slot(hass, entry, now)
    await hass.async_block_till_done()
    assert calls == ["turn_on"]


async def test_enforce_mode_calls_every_slot(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """In enforce mode, the service is called even if the state already matches."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_CONTROL_MODE: CONTROL_MODE_ENFORCE}
    )
    await _setup(hass, mock_config_entry, nordpool_prices)
    entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    runtime = entry.runtime_data
    runtime.last_desired_state = False  # pretend a previous slot already ran

    now = datetime.now(UTC)
    hass.states.async_set(mock_target, "off")

    calls = []

    async def _record(call) -> None:
        calls.append(call.service)

    hass.services.async_register("input_boolean", "turn_off", _record)
    hass.services.async_register("input_boolean", "turn_on", _record)

    await _async_apply_slot(hass, entry, now)
    await hass.async_block_till_done()
    assert "turn_off" in calls


async def test_reload_mid_slot_keeps_current_override(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A reload partway through a slot doesn't lose that slot's override.

    Regression test: overrides used to be popped the moment their slot
    started, so a reload before the next slot boundary reverted to default.
    """
    await _setup(hass, mock_config_entry, nordpool_prices)
    entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    now = datetime.now(UTC)
    entry.runtime_data.schedule.set_slot(_slot_start(now), state=True)
    await _async_apply_slot(hass, entry, now)
    await hass.async_block_till_done()
    assert hass.states.get(mock_target).state == "on"

    # Simulate a reload: fresh runtime, last_desired_state resets to None.
    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)

    # The override for the still-current slot must have survived the reload.
    assert entry.runtime_data.schedule.get(_slot_start(now)) is True
    assert hass.states.get(mock_target).state == "on"


def _slot_start(now: datetime) -> datetime:
    from custom_components.nordpool_scheduler.util import (
        slot_start_for,
    )

    return slot_start_for(now)
