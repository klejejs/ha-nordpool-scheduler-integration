"""Tests for the average price stats and their sensors."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.nordpool_scheduler.stats import KEEP_DAYS, WINDOWS, PriceStats

from .conftest import hourly_day_prices
from .conftest import setup_scheduler_entry as _setup

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

# 10:00 in Oslo (CEST). The tests stay inside this hour: crossing it would fire
# the core nordpool integration's own hourly fetch, which needs the network.
START = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
# 20 EUR/MWh then 30 EUR/MWh, in c/kWh with 21% VAT.
TWO_SLOT_AVERAGE = round((2.42 + 3.63) / 2, 4)
SCHEDULER_TODAY = "sensor.nordpool_scheduler_test_average_price_today"
PRICES_TODAY = "sensor.nordpool_scheduler_prices_lv_average_price_today"


@pytest.fixture
async def riga_tz(hass: HomeAssistant) -> None:
    """Use a European time zone, UTC+3 in summer and UTC+2 in winter."""
    await hass.config.async_set_time_zone("Europe/Riga")


async def _stats(hass: HomeAssistant, prices: dict[datetime, float]) -> PriceStats:
    stats = PriceStats(hass, "entry1", prices.get)
    await stats.async_load()
    return stats


def _set_start_prices(nordpool_prices: dict[date, list]) -> None:
    """Price START's slot at 20 EUR/MWh and the one after it at 30."""
    entries = hourly_day_prices(date(2026, 10, 7))
    entries[40]["price"] = 20.0
    entries[41]["price"] = 30.0
    nordpool_prices[date(2026, 10, 7)] = entries


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(minutes=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("riga_tz")
async def test_accrue_weights_each_slot_by_time(hass: HomeAssistant) -> None:
    """A run across a slot boundary is priced by each slot's share of it."""
    slot_a = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    slot_b = slot_a + timedelta(minutes=15)
    stats = await _stats(hass, {slot_a: 10.0, slot_b: 40.0})

    stats.accrue(slot_a + timedelta(minutes=10), slot_b + timedelta(minutes=10))

    # 5 minutes at 10, 10 minutes at 40.
    assert stats.average(date(2026, 7, 1)) == (30.0, 0.25)


@pytest.mark.usefixtures("riga_tz")
async def test_accrue_splits_at_local_midnight(hass: HomeAssistant) -> None:
    """Time either side of local midnight counts towards its own day."""
    midnight = datetime(2026, 7, 1, 21, 0, tzinfo=UTC)  # 00:00 in Riga
    before = midnight - timedelta(minutes=15)
    stats = await _stats(hass, {before: 10.0, midnight: 30.0})

    stats.accrue(before, midnight + timedelta(minutes=15))

    assert stats.average(date(2026, 7, 2)) == (30.0, 0.25)
    assert stats.average(date(2026, 7, 1)) == (20.0, 0.5)


@pytest.mark.usefixtures("riga_tz")
async def test_accrue_skips_unpriced_slots(hass: HomeAssistant) -> None:
    """A slot with no price adds neither time nor price."""
    slot_a = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    stats = await _stats(hass, {slot_a: 10.0})

    stats.accrue(slot_a, slot_a + timedelta(minutes=30))

    assert stats.average(date(2026, 7, 1)) == (10.0, 0.25)


@pytest.mark.usefixtures("riga_tz")
async def test_accrue_counts_a_25_hour_day(hass: HomeAssistant) -> None:
    """The day clocks go back has 25 hours, all of them in one bucket."""
    day_start = datetime(2026, 10, 24, 21, 0, tzinfo=UTC)  # 25 Oct 00:00 EEST
    day_end = datetime(2026, 10, 25, 22, 0, tzinfo=UTC)  # 26 Oct 00:00 EET
    prices: dict[datetime, float] = {}
    slot = day_start - timedelta(hours=1)
    while slot < day_end + timedelta(hours=1):
        prices[slot] = 5.0
        slot += timedelta(minutes=15)
    stats = await _stats(hass, prices)

    stats.accrue(day_start - timedelta(hours=1), day_end + timedelta(hours=1))

    assert stats.average(date(2026, 10, 26)) == (5.0, 1.0)
    _price, hours_from_25th = stats.average(date(2026, 10, 25))
    assert hours_from_25th == 26.0


async def test_average_is_none_without_running_time(hass: HomeAssistant) -> None:
    """With nothing counted, there's no average, and zero hours."""
    stats = await _stats(hass, {})
    assert stats.average(date(2026, 1, 1)) == (None, 0.0)


async def test_old_days_are_pruned(hass: HomeAssistant) -> None:
    """Days further back than KEEP_DAYS are dropped as new time is counted."""
    old = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    new = old + timedelta(days=KEEP_DAYS + 1)
    stats = await _stats(hass, {old: 10.0, new: 20.0})

    stats.accrue(old, old + timedelta(minutes=15))
    stats.accrue(new, new + timedelta(minutes=15))

    assert stats.average(date(2000, 1, 1)) == (20.0, 0.25)


async def test_totals_survive_a_reload(hass: HomeAssistant) -> None:
    """Flushed totals are read back by a fresh store."""
    slot = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    stats = await _stats(hass, {slot: 12.5})
    stats.accrue(slot, slot + timedelta(minutes=15))
    await stats.async_flush()

    reloaded = await _stats(hass, {})
    assert reloaded.average(date(2026, 1, 1)) == (12.5, 0.25)


def test_window_starts() -> None:
    """Calendar windows start today, on Monday, on the 1st and on 1 January."""
    wednesday = date(2026, 10, 7)
    assert {w.key: w.start(wednesday) for w in WINDOWS} == {
        "today": wednesday,
        "week": date(2026, 10, 5),
        "month": date(2026, 10, 1),
        "year": date(2026, 1, 1),
    }


async def test_scheduler_sensor_averages_running_time(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Only time with the target on counts, and the totals survive a reload."""
    freezer.move_to(START)
    _set_start_prices(nordpool_prices)
    await _setup(hass, mock_config_entry, nordpool_prices)
    state = hass.states.get(SCHEDULER_TODAY)
    assert state.state == "unknown"
    assert state.attributes["running_hours"] == 0.0
    assert state.attributes["unit_of_measurement"] == "c/kWh"

    hass.states.async_set(mock_target, "on")
    await hass.async_block_till_done()
    await _tick(hass, freezer)
    await _tick(hass, freezer)
    hass.states.async_set(mock_target, "off")
    await hass.async_block_till_done()
    await _tick(hass, freezer)

    state = hass.states.get(SCHEDULER_TODAY)
    assert float(state.state) == pytest.approx(TWO_SLOT_AVERAGE, abs=0.001)
    assert state.attributes["running_hours"] == 0.5
    assert state.attributes["period_start"] == dt_util.now().date().isoformat()

    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get(SCHEDULER_TODAY).state) == pytest.approx(
        TWO_SLOT_AVERAGE, abs=0.001
    )


async def test_prices_entry_sensor_averages_every_slot(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_prices_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
) -> None:
    """A prices entry averages all the time since setup, with no running hours."""
    freezer.move_to(START)
    _set_start_prices(nordpool_prices)
    await _setup(hass, mock_prices_entry, nordpool_prices)

    await _tick(hass, freezer)
    await _tick(hass, freezer)

    state = hass.states.get(PRICES_TODAY)
    assert float(state.state) == pytest.approx(TWO_SLOT_AVERAGE, abs=0.001)
    assert "running_hours" not in state.attributes
