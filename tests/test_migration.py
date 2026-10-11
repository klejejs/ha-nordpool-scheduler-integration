"""Tests for migrating the old per-day auto settings into time windows."""

from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING, Any

from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.nordpool_scheduler.auto import AutoWindow
from custom_components.nordpool_scheduler.const import DOMAIN

from .conftest import setup_scheduler_entry as _setup

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

OLD_ENTITIES = {
    "run_hours": "number.nordpool_scheduler_test_auto_hours_per_day",
    "max_price": "number.nordpool_scheduler_test_auto_max_price",
    "cheap_price": "number.nordpool_scheduler_test_auto_cheap_price",
    "window_enabled": "switch.nordpool_scheduler_test_auto_hour_range",
    "window_start": "time.nordpool_scheduler_test_auto_start_time",
    "window_end": "time.nordpool_scheduler_test_auto_end_time",
    "cheap_all_day": "switch.nordpool_scheduler_test_auto_cheap_price_all_day",
}


def _old_entry(entry: MockConfigEntry) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=entry.title,
        data=entry.data,
        entry_id=entry.entry_id,
        unique_id=entry.unique_id,
        minor_version=1,
    )


def _register_old_entities(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    registry = er.async_get(hass)
    for key, entity_id in OLD_ENTITIES.items():
        domain, object_id = entity_id.split(".")
        registry.async_get_or_create(
            domain,
            DOMAIN,
            f"{entry.entry_id}_{key}",
            config_entry=entry,
            suggested_object_id=object_id,
        )


def _number(key: str, value: float) -> tuple[State, dict[str, Any]]:
    return (
        State(OLD_ENTITIES[key], str(value)),
        {
            "native_value": value,
            "native_unit_of_measurement": None,
            "native_min_value": 0,
            "native_max_value": 1000,
            "native_step": 0.01,
        },
    )


def _state(key: str, value: str) -> tuple[State, dict[str, Any]]:
    return State(OLD_ENTITIES[key], value), {}


async def _migrate(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    nordpool_prices: dict[date, list],
    restored: list[tuple[State, dict[str, Any]]],
) -> MockConfigEntry:
    entry = _old_entry(mock_config_entry)
    entry.add_to_hass(hass)
    _register_old_entities(hass, entry)
    mock_restore_cache_with_extra_data(hass, restored)
    await _setup(hass, entry, nordpool_prices)
    return entry


async def test_whole_day_without_hour_range(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """With the hour range off, the old settings become one whole-day window."""
    entry = await _migrate(
        hass,
        mock_config_entry,
        nordpool_prices,
        [
            _number("run_hours", 3.5),
            _number("max_price", 20),
            _number("cheap_price", 2),
            _state("window_enabled", "off"),
            _state("window_start", "06:00:00"),
            _state("cheap_all_day", "on"),
        ],
    )

    assert entry.minor_version == 2
    assert entry.runtime_data.windows.windows == (
        AutoWindow(
            start=time(0, 0), end=time(23, 59), hours=3.5, max_price=20, cheap_price=2
        ),
    )


async def test_hour_range_becomes_its_window(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """With the hour range on, the window is the range, and the old entities go."""
    entry = await _migrate(
        hass,
        mock_config_entry,
        nordpool_prices,
        [
            _number("run_hours", 3),
            _state("window_enabled", "on"),
            _state("window_start", "22:00:30"),
            _state("window_end", "06:00:00"),
        ],
    )

    assert entry.runtime_data.windows.windows == (
        AutoWindow(start=time(22, 1), end=time(6, 0), hours=3),
    )
    registry = er.async_get(hass)
    for entity_id in OLD_ENTITIES.values():
        assert registry.async_get(entity_id) is None
        assert hass.states.get(entity_id) is None
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 11


async def test_cheap_all_day_adds_a_cheap_whole_day_window(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Cheap slots outside the range keep running through a 0-hour window."""
    entry = await _migrate(
        hass,
        mock_config_entry,
        nordpool_prices,
        [
            _number("max_price", 20),
            _number("cheap_price", 2),
            _state("window_enabled", "on"),
            _state("cheap_all_day", "on"),
        ],
    )

    assert entry.runtime_data.windows.windows == (
        AutoWindow(
            start=time(0, 0), end=time(23, 59), hours=0, max_price=20, cheap_price=2
        ),
        AutoWindow(
            start=time(17, 0), end=time(23, 0), hours=2, max_price=20, cheap_price=2
        ),
    )


async def test_no_restore_data_gives_the_default_window(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """An entry with no saved settings gets the old defaults as one window."""
    entry = await _migrate(hass, mock_config_entry, nordpool_prices, [])
    assert entry.runtime_data.windows.windows == (
        AutoWindow(start=time(0, 0), end=time(23, 59), hours=2),
    )


async def test_prices_entry_is_only_bumped(
    hass: HomeAssistant,
    mock_prices_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
) -> None:
    """A prices-only entry has no auto settings to migrate."""
    entry = _old_entry(mock_prices_entry)
    await _setup(hass, entry, nordpool_prices)
    assert entry.minor_version == 2
