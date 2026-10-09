"""Tests for the schedule sensor that publishes the card's snapshot."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.helpers import entity_registry as er

from custom_components.nordpool_scheduler.const import DOMAIN
from custom_components.nordpool_scheduler.snapshot import build_snapshot
from custom_components.nordpool_scheduler.util import slot_start_for

from .conftest import OSLO_TZ
from .conftest import setup_scheduler_entry as _setup

if TYPE_CHECKING:
    from datetime import date

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

SCHEDULE = "sensor.nordpool_scheduler_test_schedule"
PRICES_SCHEDULE = "sensor.nordpool_scheduler_prices_lv_schedule"
FLAGS = {"1": "on", "0": "off", "-": None}
AUTO_FLAGS = {"1": True, "0": False, "-": None}
# The recorder drops a state's attributes when they serialize to more than this.
MAX_STATE_ATTRS_BYTES = 16384


def _enable(hass: HomeAssistant, entry: MockConfigEntry, object_id: str) -> None:
    """Pre-register the disabled-by-default schedule sensor as enabled."""
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_schedule",
        suggested_object_id=object_id,
        config_entry=entry,
    )


def _unpack(published: dict) -> list[dict]:
    """Rebuild the websocket snapshot's slot list from the packed attribute."""
    first = datetime.fromisoformat(published["slots_start"])
    return [
        {
            "start": (first + timedelta(minutes=15 * i)).isoformat(),
            "end": (first + timedelta(minutes=15 * (i + 1))).isoformat(),
            "price": price,
            "override": FLAGS[published["slot_overrides"][i]],
            "base": FLAGS[published["slot_base"][i]],
            "auto": AUTO_FLAGS[published["slot_auto"][i]],
            "effective": FLAGS[published["slot_overrides"][i]]
            or FLAGS[published["slot_base"][i]],
        }
        for i, price in enumerate(published["slot_prices"])
    ]


def _assert_unpacks_to_snapshot(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    published = dict(hass.states.get(SCHEDULE).attributes["schedule"])
    expected = build_snapshot(hass, entry)
    assert published.pop("entity_id") == SCHEDULE
    assert _unpack(published) == expected.pop("slots")
    for key in (
        "slots_start",
        "slot_prices",
        "slot_overrides",
        "slot_base",
        "slot_auto",
    ):
        published.pop(key)
    assert published == expected


async def test_schedule_sensor_disabled_by_default(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The sensor exists but stays off unless someone enables it."""
    await _setup(hass, mock_config_entry, nordpool_prices)

    entry = er.async_get(hass).async_get(SCHEDULE)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(SCHEDULE) is None


async def test_schedule_sensor_publishes_snapshot(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The attribute unpacks to the snapshot the websocket sends."""
    # Auto mode only picks in a local day Nord Pool has fully priced.
    await hass.config.async_set_time_zone("Europe/Oslo")
    _enable(hass, mock_config_entry, "nordpool_scheduler_test_schedule")
    await _setup(hass, mock_config_entry, nordpool_prices)

    state = hass.states.get(SCHEDULE)
    assert state is not None
    assert datetime.fromisoformat(state.state) == slot_start_for(datetime.now(OSLO_TZ))
    assert "schedule" in state.state_info["unrecorded_attributes"]

    _assert_unpacks_to_snapshot(hass, mock_config_entry)

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.nordpool_scheduler_test_auto_mode"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert "1" in hass.states.get(SCHEDULE).attributes["schedule"]["slot_auto"]
    _assert_unpacks_to_snapshot(hass, mock_config_entry)


async def test_schedule_sensor_follows_overrides(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Setting a slot rewrites the attribute straight away."""
    _enable(hass, mock_config_entry, "nordpool_scheduler_test_schedule")
    await _setup(hass, mock_config_entry, nordpool_prices)
    published = hass.states.get(SCHEDULE).attributes["schedule"]
    start = datetime.fromisoformat(published["now_slot_start"]) + timedelta(minutes=15)
    index = (start - datetime.fromisoformat(published["slots_start"])) // timedelta(
        minutes=15
    )
    assert published["slot_overrides"][index] == "-"

    await hass.services.async_call(
        DOMAIN,
        "set_slots",
        {
            "config_entry": mock_config_entry.entry_id,
            "slots": [{"start": start.isoformat(), "state": "on"}],
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    published = hass.states.get(SCHEDULE).attributes["schedule"]
    assert published["slot_overrides"][index] == "1"


async def test_schedule_sensor_fits_recorder_limit(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A full window of four-decimal prices stays well under the recorder's limit."""
    _enable(hass, mock_config_entry, "nordpool_scheduler_test_schedule")
    await _setup(hass, mock_config_entry, nordpool_prices)

    attributes = dict(hass.states.get(SCHEDULE).attributes)
    published = dict(attributes["schedule"])
    # Two 25-hour DST days, every slot priced.
    slots = 2 * 25 * 4
    published["slot_prices"] = [123.4567] * slots
    for key in ("slot_overrides", "slot_base", "slot_auto"):
        published[key] = "-" * slots
    attributes["schedule"] = published
    assert len(json.dumps(attributes)) < MAX_STATE_ATTRS_BYTES / 2


async def test_schedule_sensor_on_prices_entry(
    hass: HomeAssistant,
    mock_prices_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
) -> None:
    """A prices-only entry publishes its prices with no target."""
    _enable(hass, mock_prices_entry, "nordpool_scheduler_prices_lv_schedule")
    await _setup(hass, mock_prices_entry, nordpool_prices)

    published = hass.states.get(PRICES_SCHEDULE).attributes["schedule"]
    assert published["target_entity"] is None
    assert published["config_entry_id"] == mock_prices_entry.entry_id
