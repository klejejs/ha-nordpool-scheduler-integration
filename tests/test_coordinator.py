"""Tests for NordpoolSchedulerPriceCoordinator."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.nordpool_scheduler.const import CONF_VAT_PERCENT
from custom_components.nordpool_scheduler.coordinator import (
    NordpoolSchedulerPriceCoordinator,
    NordpoolUnavailableError,
)

from .conftest import OSLO_TZ, hourly_day_prices

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def _build_coordinator(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    nordpool_prices: dict[date, list],
) -> NordpoolSchedulerPriceCoordinator:
    """Build a coordinator ready for async_config_entry_first_refresh.

    Fills in yesterday's prices too, since the coordinator always fetches
    it and treats a gap there as an error, not "not published yet".
    """
    entry.add_to_hass(hass)
    # async_config_entry_first_refresh requires this state; setting it
    # directly lets these tests exercise the coordinator without going
    # through a full integration setup.
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    today = datetime.now(OSLO_TZ).date()
    nordpool_prices.setdefault(today - timedelta(days=1), hourly_day_prices(today))
    return NordpoolSchedulerPriceCoordinator(hass, entry)


async def test_fetches_today_and_uses_vat(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
) -> None:
    """Prices are fetched, converted to currency/kWh, and VAT is applied."""
    today = datetime.now(OSLO_TZ).date()
    nordpool_prices[today] = hourly_day_prices(today, lambda _h: 100.0)  # 100 EUR/MWh

    coordinator = await _build_coordinator(hass, mock_config_entry, nordpool_prices)
    await coordinator.async_config_entry_first_refresh()
    coordinator._cancel_timers()

    # 100 EUR/MWh -> 0.1 EUR/kWh, +21% VAT -> 0.121
    price = coordinator.get_price(_first_known_slot(coordinator))
    assert price is not None
    assert 0.1 <= price <= 0.13


def _first_known_slot(coordinator: NordpoolSchedulerPriceCoordinator) -> datetime:
    return next(iter(sorted(coordinator.data)))


async def test_tomorrow_not_published_is_tolerated(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
) -> None:
    """Missing tomorrow prices don't fail the refresh."""
    today = datetime.now(OSLO_TZ).date()
    nordpool_prices[today] = hourly_day_prices(today)
    # tomorrow deliberately left out of nordpool_prices; yesterday is
    # filled in by _build_coordinator.

    coordinator = await _build_coordinator(hass, mock_config_entry, nordpool_prices)
    await coordinator.async_config_entry_first_refresh()
    coordinator._cancel_timers()

    assert coordinator.last_update_success
    assert coordinator.data


async def test_no_data_at_all_raises_update_failed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
) -> None:
    """If nothing is published for any of the three days, the refresh fails."""
    mock_config_entry.add_to_hass(hass)
    coordinator = NordpoolSchedulerPriceCoordinator(hass, mock_config_entry)
    coordinator._oslo_tz = OSLO_TZ  # normally set by _async_setup
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.parametrize(("hours", "expected_slots"), [(23, 92), (25, 100)])
async def test_dst_days_are_keyed_by_utc_timestamp(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
    hours: int,
    expected_slots: int,
) -> None:
    """A 23- or 25-hour CET day produces the right number of UTC-keyed slots."""
    today = datetime.now(OSLO_TZ).date()
    nordpool_prices[today] = hourly_day_prices(today, hours=hours)

    coordinator = await _build_coordinator(hass, mock_config_entry, nordpool_prices)
    day_prices = await coordinator._async_fetch_day(today)

    assert len(day_prices) == expected_slots


async def test_vat_percent_from_options(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
) -> None:
    """A custom VAT percent option changes the converted price."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_VAT_PERCENT: 0}
    )
    today = datetime.now(OSLO_TZ).date()
    nordpool_prices[today] = hourly_day_prices(today, lambda _h: 100.0)

    coordinator = await _build_coordinator(hass, mock_config_entry, nordpool_prices)
    await coordinator.async_config_entry_first_refresh()
    coordinator._cancel_timers()

    price = coordinator.get_price(_first_known_slot(coordinator))
    assert price == pytest.approx(0.1)


async def test_unavailable_error_is_a_home_assistant_error() -> None:
    """NordpoolUnavailableError is catchable as a HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError

    assert issubclass(NordpoolUnavailableError, HomeAssistantError)
