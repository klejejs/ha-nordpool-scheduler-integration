"""Tests for the set_slots and clear_schedule services."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

import pytest
import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError

from custom_components.nordpool_scheduler.auto import AutoWindow
from custom_components.nordpool_scheduler.const import DOMAIN
from custom_components.nordpool_scheduler.util import slot_start_for

from .conftest import OSLO_TZ
from .conftest import setup_scheduler_entry as _setup

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory
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
    freezer: FrozenDateTimeFactory,
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


async def test_set_slots_rejects_an_empty_list(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A call has to set at least one slot."""
    await _setup(hass, mock_config_entry, nordpool_prices)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "set_slots",
            {"config_entry": mock_config_entry.entry_id, "slots": []},
            blocking=True,
        )


async def test_set_slots_rejects_a_repeated_start(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The same slot twice in one call is refused, and nothing is set."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    start = slot_start_for(datetime.now(OSLO_TZ)) + timedelta(minutes=15)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "set_slots",
            {
                "config_entry": mock_config_entry.entry_id,
                "slots": [
                    {"start": start.isoformat(), "state": "on"},
                    {"start": start.isoformat(), "state": "off"},
                ],
            },
            blocking=True,
        )
    assert err.value.translation_key == "slot_duplicate"
    assert mock_config_entry.runtime_data.schedule.get(start) is None


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


async def test_set_auto_windows_replaces(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The windows are replaced as a whole, sorted by start."""
    await _setup(hass, mock_config_entry, nordpool_prices)

    await hass.services.async_call(
        DOMAIN,
        "set_auto_windows",
        {
            "config_entry": mock_config_entry.entry_id,
            "windows": [
                {"start": "20:00", "end": "00:00", "hours": 1},
                {"start": "06:00", "end": "08:00", "hours": 0.75, "max_price": 25},
            ],
        },
        blocking=True,
    )
    assert mock_config_entry.runtime_data.windows.windows == (
        AutoWindow(start=time(6, 0), end=time(8, 0), hours=0.75, max_price=25),
        AutoWindow(start=time(20, 0), end=time(0, 0), hours=1),
    )
    assert mock_config_entry.runtime_data.run_hours == 1.75


async def test_set_auto_windows_rejects_an_empty_list(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Auto mode's switch stops it, so the windows can't be emptied."""
    await _setup(hass, mock_config_entry, nordpool_prices)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "set_auto_windows",
            {"config_entry": mock_config_entry.entry_id, "windows": []},
            blocking=True,
        )
    assert len(mock_config_entry.runtime_data.windows.windows) == 1


@pytest.mark.parametrize(
    "window",
    [
        {"start": "06:00", "end": "08:00", "hours": 25},
        {"start": "06:00", "end": "08:00", "hours": -1},
        {"start": "6 am", "end": "08:00", "hours": 1},
        {"start": "06:00", "hours": 1},
        {"start": "06:00", "end": "08:00", "hours": 1, "max_price": -1},
        {"start": "06:00", "end": "08:00", "hours": 0.3},
        {"start": "06:00", "end": "08:00", "hours": 1, "min_run_hours": 0.3},
        {"start": "06:00", "end": "08:00", "hours": 1, "min_run_hours": 25},
    ],
)
async def test_set_auto_windows_rejects_bad_windows(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
    window: dict,
) -> None:
    """A window with a bad time, hours or price is refused."""
    await _setup(hass, mock_config_entry, nordpool_prices)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "set_auto_windows",
            {"config_entry": mock_config_entry.entry_id, "windows": [window]},
            blocking=True,
        )


async def test_set_auto_windows_rejects_prices_entry(
    hass: HomeAssistant,
    mock_prices_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
) -> None:
    """A prices-only entry has no auto mode to set windows for."""
    await _setup(hass, mock_prices_entry, nordpool_prices)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_auto_windows",
            {
                "config_entry": mock_prices_entry.entry_id,
                "windows": [{"start": "06:00", "end": "08:00", "hours": 1}],
            },
            blocking=True,
        )


async def test_set_auto_windows_requires_the_list(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Leaving the windows out is refused rather than clearing them."""
    await _setup(hass, mock_config_entry, nordpool_prices)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "set_auto_windows",
            {"config_entry": mock_config_entry.entry_id},
            blocking=True,
        )
    assert len(mock_config_entry.runtime_data.windows.windows) == 1


@pytest.mark.parametrize(
    ("windows", "key"),
    [
        (
            [{"start": "06:00:30", "end": "08:00", "hours": 1}],
            "window_time_not_aligned",
        ),
        ([{"start": "06:05", "end": "08:00", "hours": 1}], "window_time_not_aligned"),
        ([{"start": "06:00", "end": "08:00", "hours": 3}], "window_hours_too_long"),
        (
            [{"start": "06:00", "end": "08:00", "hours": 0.5, "min_run_hours": 1}],
            "window_min_run_above_hours",
        ),
        (
            [{"start": "06:00", "end": "08:00", "hours": 0, "cheap_price": 0}],
            "window_does_nothing",
        ),
        (
            [
                {"start": "06:00", "end": "08:00", "hours": 1},
                {"start": "06:00", "end": "08:00", "hours": 0.5},
            ],
            "windows_duplicate",
        ),
    ],
)
async def test_set_auto_windows_rejects_invalid_combinations(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
    windows: list[dict],
    key: str,
) -> None:
    """Windows that break a rule are refused, and the old ones kept."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    before = mock_config_entry.runtime_data.windows.windows

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "set_auto_windows",
            {"config_entry": mock_config_entry.entry_id, "windows": windows},
            blocking=True,
        )
    assert err.value.translation_key == key
    assert mock_config_entry.runtime_data.windows.windows == before


async def test_set_auto_windows_checks_the_run_limit(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """With Limit runs on, there can't be more running windows than runs per day."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    mock_config_entry.runtime_data.runs_limited = True
    mock_config_entry.runtime_data.max_runs = 1
    windows = [
        {"start": "06:00", "end": "08:00", "hours": 1},
        {"start": "18:00", "end": "20:00", "hours": 1},
    ]

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "set_auto_windows",
            {"config_entry": mock_config_entry.entry_id, "windows": windows},
            blocking=True,
        )
    assert err.value.translation_key == "windows_too_many_runs"

    # A window that only runs cheap slots needs no run of its own.
    windows[1] = {**windows[1], "hours": 0, "cheap_price": 1}
    await hass.services.async_call(
        DOMAIN,
        "set_auto_windows",
        {"config_entry": mock_config_entry.entry_id, "windows": windows},
        blocking=True,
    )
    assert len(mock_config_entry.runtime_data.windows.windows) == 2


async def test_set_auto_windows_takes_a_min_run(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A min run is kept, and counts towards the hours run."""
    await _setup(hass, mock_config_entry, nordpool_prices)

    await hass.services.async_call(
        DOMAIN,
        "set_auto_windows",
        {
            "config_entry": mock_config_entry.entry_id,
            "windows": [
                {"start": "00:00", "end": "23:59", "hours": 1, "min_run_hours": 1},
                {"start": "06:00", "end": "08:00", "hours": 0.25},
            ],
        },
        blocking=True,
    )
    assert mock_config_entry.runtime_data.windows.windows == (
        AutoWindow(start=time(0, 0), end=time(23, 59), hours=1, min_run_hours=1),
        AutoWindow(start=time(6, 0), end=time(8, 0), hours=0.25),
    )
    assert mock_config_entry.runtime_data.run_hours == 1.25
