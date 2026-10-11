"""Tests for auto mode: its switch, its settings and how it drives the target."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache_with_extra_data,
)

from custom_components.nordpool_scheduler.auto import AutoWindow
from custom_components.nordpool_scheduler.util import slot_start_for

from .conftest import OSLO_TZ, hourly_day_prices

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.typing import WebSocketGenerator

AUTO_SWITCH = "switch.nordpool_scheduler_test_auto_mode"
RUNS_LIMIT = "switch.nordpool_scheduler_test_auto_run_limit"
MAX_RUNS = "number.nordpool_scheduler_test_auto_max_runs_per_day"
SCHEDULED_ON = "binary_sensor.nordpool_scheduler_test_scheduled_on"
SENSOR = "sensor.nordpool_scheduler_test_electricity_price"

CHEAP = 10.0  # EUR/MWh: 1.21 c/kWh with VAT
EXPENSIVE = 500.0  # EUR/MWh: 60.5 c/kWh with VAT


async def _setup_with_cheap_current_hour(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    nordpool_prices: dict[date, list],
) -> None:
    """Price the current hour cheap and the rest of the local day expensive.

    HA runs in Nord Pool's own time zone here, so one CET delivery day is
    exactly one local day and auto mode can decide it.
    """
    await hass.config.async_set_time_zone("Europe/Oslo")
    now = datetime.now(OSLO_TZ)
    today = now.date()
    midnight = datetime.combine(today, datetime.min.time(), tzinfo=OSLO_TZ)
    next_midnight = datetime.combine(
        today + timedelta(days=1), datetime.min.time(), tzinfo=OSLO_TZ
    )
    hour = timedelta(hours=1)
    hours = (next_midnight.astimezone(UTC) - midnight.astimezone(UTC)) // hour
    current_hour = (now.astimezone(UTC) - midnight.astimezone(UTC)) // hour

    nordpool_prices[today] = hourly_day_prices(
        today, lambda h: CHEAP if h == current_hour else EXPENSIVE, hours=hours
    )
    nordpool_prices[today - timedelta(days=1)] = hourly_day_prices(
        today - timedelta(days=1)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _switch(
    hass: HomeAssistant, service: str, entity_id: str = AUTO_SWITCH
) -> None:
    await hass.services.async_call(
        "switch", service, {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def _set_windows(
    hass: HomeAssistant, entry: MockConfigEntry, windows: list[dict]
) -> None:
    await hass.services.async_call(
        "nordpool_scheduler",
        "set_auto_windows",
        {"config_entry": entry.entry_id, "windows": windows},
        blocking=True,
    )
    await hass.async_block_till_done()


def _hours_from_now(start: int, end: int) -> tuple[str, str]:
    hour = datetime.now(OSLO_TZ).hour
    return f"{(hour + start) % 24:02}:00", f"{(hour + end) % 24:02}:00"


async def test_auto_mode_is_off_by_default(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A new scheduler starts with auto mode off and one whole-day window."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)

    assert hass.states.get(AUTO_SWITCH).state == "off"
    assert mock_config_entry.runtime_data.windows.windows == (
        AutoWindow(start=time(0, 0), end=time(23, 59), hours=2.0),
    )
    assert hass.states.get(mock_target).state == "off"


async def test_price_sensor_reports_cents(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The price sensor's value is in cents/kWh, VAT included."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)
    assert float(hass.states.get(SENSOR).state) == 1.21


async def test_turning_auto_on_applies_immediately(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The target follows auto's pick at once, and the default once auto is off."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)

    await _switch(hass, "turn_on")
    assert hass.states.get(mock_target).state == "on"
    state = hass.states.get(SCHEDULED_ON)
    assert state.state == "on"
    assert state.attributes["source"] == "auto"

    await _switch(hass, "turn_off")
    assert hass.states.get(mock_target).state == "off"
    assert hass.states.get(SCHEDULED_ON).attributes["source"] == "default"


async def test_override_beats_auto(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Overriding the current slot off wins over auto's pick, straight away."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)
    await _switch(hass, "turn_on")
    assert hass.states.get(mock_target).state == "on"

    await hass.services.async_call(
        "nordpool_scheduler",
        "set_slots",
        {
            "config_entry": mock_config_entry.entry_id,
            "slots": [
                {"start": slot_start_for(dt_util.utcnow()).isoformat(), "state": "off"}
            ],
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get(mock_target).state == "off"
    assert hass.states.get(SCHEDULED_ON).attributes["source"] == "override"


async def test_windows_re_pick_and_apply(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Changing the windows re-picks the slots and applies the current one."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)
    await _switch(hass, "turn_on")
    assert hass.states.get(mock_target).state == "on"

    whole_day = {"start": "00:00", "end": "23:59"}
    # Below the cheap hour's 1.21
    await _set_windows(
        hass, mock_config_entry, [{**whole_day, "hours": 2, "max_price": 1.0}]
    )
    assert hass.states.get(mock_target).state == "off"

    await _set_windows(hass, mock_config_entry, [{**whole_day, "hours": 0}])
    assert hass.states.get(mock_target).state == "off"

    await _set_windows(
        hass, mock_config_entry, [{**whole_day, "hours": 0, "cheap_price": 2.0}]
    )
    assert hass.states.get(mock_target).state == "on"

    await _set_windows(hass, mock_config_entry, [])
    assert hass.states.get(mock_target).state == "off"
    assert hass.states.get(SCHEDULED_ON).attributes["source"] == "auto"


async def test_window_limits_picks(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A window without the current hour turns it off, unless a row runs it cheap."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)
    await _switch(hass, "turn_on")
    assert hass.states.get(mock_target).state == "on"

    start, end = _hours_from_now(2, 3)
    await _set_windows(
        hass, mock_config_entry, [{"start": start, "end": end, "hours": 1}]
    )
    assert hass.states.get(mock_target).state == "off"
    assert hass.states.get(SCHEDULED_ON).attributes["source"] == "auto"

    await _set_windows(
        hass,
        mock_config_entry,
        [
            {"start": start, "end": end, "hours": 1},
            {"start": "00:00", "end": "23:59", "hours": 0, "cheap_price": 2.0},
        ],
    )
    assert hass.states.get(mock_target).state == "on"


async def test_run_limit_keeps_auto_to_one_run(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """One run a day: the hours run back to back and cheap slots start no other."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)
    assert hass.states.get(RUNS_LIMIT).state == "off"
    assert hass.states.get(MAX_RUNS).state == "1"
    await _switch(hass, "turn_on")

    await _switch(hass, "turn_on", RUNS_LIMIT)
    assert hass.states.get(mock_target).state == "on"
    runtime = mock_config_entry.runtime_data
    today = sorted(
        slot
        for slot in runtime.auto_slots
        if slot.astimezone(OSLO_TZ).date() == datetime.now(OSLO_TZ).date()
    )
    on = [runtime.auto_slots[slot] for slot in today]
    assert sum(on) == 8
    assert sum(o and (i == 0 or not on[i - 1]) for i, o in enumerate(on)) == 1

    await _set_windows(
        hass,
        mock_config_entry,
        [{"start": "00:00", "end": "23:59", "hours": 0, "cheap_price": 2.0}],
    )
    assert hass.states.get(mock_target).state == "off"

    await _switch(hass, "turn_off", RUNS_LIMIT)
    assert hass.states.get(mock_target).state == "on"


async def test_windows_survive_a_reload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The windows are saved to disk and read back on setup."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)
    await _set_windows(
        hass,
        mock_config_entry,
        [
            {"start": "19:00", "end": "22:00", "hours": 1, "cheap_price": 3},
            {"start": "06:00", "end": "08:00", "hours": 0.75, "max_price": 25},
        ],
    )

    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.windows.windows == (
        AutoWindow(start=time(6, 0), end=time(8, 0), hours=0.75, max_price=25),
        AutoWindow(start=time(19, 0), end=time(22, 0), hours=1, cheap_price=3),
    )


async def test_auto_settings_are_restored(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Auto mode and its settings survive a restart."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (State(AUTO_SWITCH, "on"), {}),
            (State(RUNS_LIMIT, "on"), {}),
            (
                State(MAX_RUNS, "2"),
                {
                    "native_value": 2,
                    "native_unit_of_measurement": None,
                    "native_min_value": 1,
                    "native_max_value": 24,
                    "native_step": 1,
                },
            ),
        ],
    )
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)

    runtime = mock_config_entry.runtime_data
    assert hass.states.get(AUTO_SWITCH).state == "on"
    assert runtime.auto_enabled is True
    assert runtime.runs_limited is True
    assert runtime.max_runs == 2
    assert hass.states.get(mock_target).state == "on"


async def test_snapshot_carries_auto_mode(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The card's snapshot says what auto picked, apart from the overrides."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)
    await _switch(hass, "turn_on")
    now_slot = slot_start_for(dt_util.utcnow())
    mock_config_entry.runtime_data.schedule.set_slot(now_slot, state=False)

    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "nordpool_scheduler/subscribe", "entity_id": SENSOR}
    )
    assert (await client.receive_json())["success"]
    snapshot = (await client.receive_json())["event"]

    assert snapshot["auto"] == {
        "enabled": True,
        "switch_entity": AUTO_SWITCH,
        "run_hours": 2.0,
        "windows": [
            {
                "start": "00:00",
                "end": "23:59",
                "hours": 2.0,
                "max_price": 0.0,
                "cheap_price": 0.0,
            }
        ],
        "runs_limited": False,
        "max_runs": 1,
        "runs_limited_entity": RUNS_LIMIT,
        "max_runs_entity": MAX_RUNS,
    }
    current = next(
        s for s in snapshot["slots"] if s["start"] == snapshot["now_slot_start"]
    )
    assert current["price"] == 1.21
    assert current["auto"] is True
    assert current["base"] == "on"
    assert current["override"] == "off"
    assert current["effective"] == "off"
    assert sum(1 for s in snapshot["slots"] if s["auto"]) >= 8
