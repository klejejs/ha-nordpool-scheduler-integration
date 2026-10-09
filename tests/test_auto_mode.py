"""Tests for auto mode: its switch, its settings and how it drives the target."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

from custom_components.nordpool_scheduler.util import slot_start_for

from .conftest import OSLO_TZ, hourly_day_prices

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.typing import WebSocketGenerator

AUTO_SWITCH = "switch.nordpool_scheduler_test_auto_mode"
RUN_HOURS = "number.nordpool_scheduler_test_auto_hours_per_day"
MAX_PRICE = "number.nordpool_scheduler_test_auto_max_price"
CHEAP_PRICE = "number.nordpool_scheduler_test_auto_cheap_price"
WINDOW_SWITCH = "switch.nordpool_scheduler_test_auto_hour_range"
CHEAP_ALL_DAY = "switch.nordpool_scheduler_test_auto_cheap_price_all_day"
WINDOW_START = "time.nordpool_scheduler_test_auto_start_time"
WINDOW_END = "time.nordpool_scheduler_test_auto_end_time"
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


async def _set_number(hass: HomeAssistant, entity_id: str, value: float) -> None:
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )
    await hass.async_block_till_done()


async def _switch(
    hass: HomeAssistant, service: str, entity_id: str = AUTO_SWITCH
) -> None:
    await hass.services.async_call(
        "switch", service, {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def _set_time(hass: HomeAssistant, entity_id: str, value: time) -> None:
    await hass.services.async_call(
        "time", "set_value", {"entity_id": entity_id, "time": value}, blocking=True
    )
    await hass.async_block_till_done()


async def test_auto_mode_is_off_by_default(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A new scheduler starts with auto mode off and the blueprint's defaults."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)

    assert hass.states.get(AUTO_SWITCH).state == "off"
    assert float(hass.states.get(RUN_HOURS).state) == 2
    assert float(hass.states.get(MAX_PRICE).state) == 0
    assert float(hass.states.get(CHEAP_PRICE).state) == 0
    assert hass.states.get(MAX_PRICE).attributes["unit_of_measurement"] == "c/kWh"
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


async def test_settings_re_pick_and_apply(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Changing a setting re-picks the slots and applies the current one."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)
    await _switch(hass, "turn_on")
    assert hass.states.get(mock_target).state == "on"

    await _set_number(hass, MAX_PRICE, 1.0)  # below the cheap hour's 1.21
    assert hass.states.get(mock_target).state == "off"

    await _set_number(hass, MAX_PRICE, 0)
    await _set_number(hass, RUN_HOURS, 0)
    assert hass.states.get(mock_target).state == "off"

    await _set_number(hass, CHEAP_PRICE, 2.0)
    assert hass.states.get(mock_target).state == "on"


async def test_hour_range_limits_picks(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A range without the current hour turns it off, unless it's cheap all day."""
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)
    assert hass.states.get(WINDOW_SWITCH).state == "off"
    assert hass.states.get(CHEAP_ALL_DAY).state == "off"
    assert hass.states.get(WINDOW_START).state == "17:00:00"
    assert hass.states.get(WINDOW_END).state == "23:00:00"

    await _switch(hass, "turn_on")
    assert hass.states.get(mock_target).state == "on"

    hour = datetime.now(OSLO_TZ).hour
    await _set_time(hass, WINDOW_START, time((hour + 2) % 24))
    await _set_time(hass, WINDOW_END, time((hour + 3) % 24))
    assert hass.states.get(mock_target).state == "on"

    await _switch(hass, "turn_on", WINDOW_SWITCH)
    assert hass.states.get(mock_target).state == "off"
    assert hass.states.get(SCHEDULED_ON).attributes["source"] == "auto"

    await _set_number(hass, CHEAP_PRICE, 2.0)
    assert hass.states.get(mock_target).state == "off"

    await _switch(hass, "turn_on", CHEAP_ALL_DAY)
    assert hass.states.get(mock_target).state == "on"


async def test_hour_range_is_restored(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The hour range's switches and times survive a restart."""
    mock_restore_cache(
        hass,
        [
            State(WINDOW_SWITCH, "on"),
            State(CHEAP_ALL_DAY, "on"),
            State(WINDOW_START, "06:15:00"),
            State(WINDOW_END, "unknown"),
        ],
    )
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)

    runtime = mock_config_entry.runtime_data
    assert runtime.window_enabled is True
    assert runtime.cheap_all_day is True
    assert runtime.window_start == time(6, 15)
    assert runtime.window_end == time(23, 0)
    assert hass.states.get(WINDOW_START).state == "06:15:00"


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
            (
                State(RUN_HOURS, "3.5"),
                {
                    "native_value": 3.5,
                    "native_unit_of_measurement": "h",
                    "native_min_value": 0,
                    "native_max_value": 24,
                    "native_step": 0.25,
                },
            ),
        ],
    )
    await _setup_with_cheap_current_hour(hass, mock_config_entry, nordpool_prices)

    runtime = mock_config_entry.runtime_data
    assert hass.states.get(AUTO_SWITCH).state == "on"
    assert runtime.auto_enabled is True
    assert runtime.run_hours == 3.5
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
        "max_price": 0.0,
        "cheap_price": 0.0,
        "run_hours_entity": RUN_HOURS,
        "max_price_entity": MAX_PRICE,
        "cheap_price_entity": CHEAP_PRICE,
        "window_enabled": False,
        "window_start": "17:00",
        "window_end": "23:00",
        "cheap_all_day": False,
        "window_enabled_entity": WINDOW_SWITCH,
        "window_start_entity": WINDOW_START,
        "window_end_entity": WINDOW_END,
        "cheap_all_day_entity": CHEAP_ALL_DAY,
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
