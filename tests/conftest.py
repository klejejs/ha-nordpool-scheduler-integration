"""Fixtures for Nordpool Scheduler tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler.const import (
    CONF_AREA,
    CONF_DEFAULT_STATE,
    CONF_NORDPOOL_ENTRY_ID,
    CONF_SCHEDULER_NAME,
    CONF_TARGET_ENTITY,
    DOMAIN,
    STATE_DEFAULT_OFF,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

AREA = "LV"
OSLO_TZ = ZoneInfo("Europe/Oslo")


def hourly_day_prices(
    day: date, price_by_hour: Callable[[int], float] | None = None, *, hours: int = 24
) -> list[dict[str, Any]]:
    """Build 15-minute price entries (EUR/MWh) for one CET calendar day.

    ``hours`` lets a test simulate a 23- or 25-hour DST transition day.
    """
    price_by_hour = price_by_hour or (lambda hour: 10.0 + hour)
    start = datetime.combine(day, datetime.min.time(), tzinfo=OSLO_TZ)
    entries = []
    slot_count = hours * 4
    for i in range(slot_count):
        slot_start = start + timedelta(minutes=15 * i)
        slot_end = slot_start + timedelta(minutes=15)
        entries.append(
            {
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat(),
                "price": price_by_hour(i // 4),
            }
        )
    return entries


@pytest.fixture
def nordpool_prices() -> dict[date, list[dict[str, Any]]]:
    """Mutable table of {date: entries} the fake nordpool service serves.

    Tests populate this directly; a missing date simulates "not published".
    """
    return {}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Enable custom integrations for all tests."""


@pytest.fixture
def mock_nordpool_service(
    hass: HomeAssistant, nordpool_prices: dict[date, list[dict[str, Any]]]
) -> Generator[None]:
    """Register a fake nordpool.get_prices_for_date service."""

    async def handle_get_prices(call: ServiceCall) -> ServiceResponse:
        asked_date = call.data["date"]
        if isinstance(asked_date, str):
            asked_date = date.fromisoformat(asked_date)
        areas = call.data["areas"]
        entries = nordpool_prices.get(asked_date)
        if entries is None:
            msg = "No data for that date"
            raise ServiceValidationError(msg)
        return dict.fromkeys(areas, entries)

    hass.services.async_register(
        "nordpool",
        "get_prices_for_date",
        handle_get_prices,
        supports_response=SupportsResponse.ONLY,
    )
    yield
    hass.services.async_remove("nordpool", "get_prices_for_date")


@pytest.fixture
def mock_nordpool_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Stand in for a configured core Nord Pool config entry."""
    entry = MockConfigEntry(
        domain="nordpool",
        title="Nord Pool",
        data={"areas": [AREA], "currency": "EUR"},
        entry_id="nordpool_entry_id",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def mock_target(hass: HomeAssistant) -> str:
    """Set up a mock target entity that responds to turn_on/turn_off."""
    entity_id = "input_boolean.test_target"
    hass.states.async_set(entity_id, "off")

    async def _turn_on(call: ServiceCall) -> None:
        if call.data.get("entity_id") in (entity_id, [entity_id]):
            hass.states.async_set(entity_id, "on")

    async def _turn_off(call: ServiceCall) -> None:
        if call.data.get("entity_id") in (entity_id, [entity_id]):
            hass.states.async_set(entity_id, "off")

    hass.services.async_register("input_boolean", "turn_on", _turn_on)
    hass.services.async_register("input_boolean", "turn_off", _turn_off)
    return entity_id


async def setup_scheduler_entry(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    nordpool_prices: dict[date, list[dict[str, Any]]],
) -> None:
    """Register today's and yesterday's prices, then set up the entry.

    Yesterday is required because the coordinator always fetches it and
    treats it as an error, not "not published yet", if it's missing.
    """
    entry.add_to_hass(hass)
    today = datetime.now(OSLO_TZ).date()
    nordpool_prices.setdefault(today, hourly_day_prices(today))
    nordpool_prices.setdefault(today - timedelta(days=1), hourly_day_prices(today))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
def mock_config_entry(mock_nordpool_entry: MockConfigEntry) -> MockConfigEntry:
    """Return a mock Nordpool Scheduler config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Nordpool Scheduler - Test",
        data={
            CONF_SCHEDULER_NAME: "Test",
            CONF_TARGET_ENTITY: "input_boolean.test_target",
            CONF_DEFAULT_STATE: STATE_DEFAULT_OFF,
            CONF_NORDPOOL_ENTRY_ID: mock_nordpool_entry.entry_id,
            CONF_AREA: AREA,
        },
        entry_id="scheduler_entry_id",
        unique_id="input_boolean.test_target",
        version=2,
    )
