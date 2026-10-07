"""Tests for the nordpool_scheduler/subscribe websocket command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .conftest import setup_scheduler_entry as _setup

if TYPE_CHECKING:
    from datetime import date

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.typing import WebSocketGenerator


async def test_subscribe_sends_snapshot(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Subscribing returns a snapshot with the current slot and its price."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    sensor_entity_id = "sensor.nordpool_scheduler_test_electricity_price"

    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "nordpool_scheduler/subscribe", "entity_id": sensor_entity_id}
    )
    response = await client.receive_json()
    assert response["success"]

    event = await client.receive_json()
    snapshot = event["event"]
    assert snapshot["target_entity"] == mock_target
    assert snapshot["currency"] == "EUR"
    now_slot_start = snapshot["now_slot_start"]
    assert any(slot["start"] == now_slot_start for slot in snapshot["slots"])
    current = next(
        slot for slot in snapshot["slots"] if slot["start"] == now_slot_start
    )
    assert current["price"] is not None
    assert current["effective"] == "off"
    assert set(snapshot["averages"]) == {"today", "week", "month", "year"}
    assert snapshot["averages"]["today"] == {"price": None, "running_hours": 0.0}


async def test_subscribe_pushes_update_on_schedule_change(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A schedule change pushes a fresh snapshot to subscribers."""
    await _setup(hass, mock_config_entry, nordpool_prices)
    sensor_entity_id = "sensor.nordpool_scheduler_test_electricity_price"
    entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)

    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "nordpool_scheduler/subscribe", "entity_id": sensor_entity_id}
    )
    await client.receive_json()  # result
    first = (await client.receive_json())["event"]
    slot_start = first["now_slot_start"]

    entry.runtime_data.schedule.set_slot(dt_util.parse_datetime(slot_start), state=True)
    async_dispatcher_send(hass, entry.runtime_data.update_signal)

    second = (await client.receive_json())["event"]
    current = next(s for s in second["slots"] if s["start"] == slot_start)
    assert current["override"] == "on"
    assert current["effective"] == "on"


async def test_subscribe_unknown_entity_errors(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Subscribing to an entity that isn't a scheduler sensor errors cleanly."""
    # Setting up any entry registers the websocket command.
    await _setup(hass, mock_config_entry, nordpool_prices)

    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "nordpool_scheduler/subscribe",
            "entity_id": "sensor.does_not_exist",
        }
    )
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "not_found"


async def test_subscribe_prices_entry_has_no_target(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_prices_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
) -> None:
    """A prices entry's snapshot has prices but no target entity."""
    await _setup(hass, mock_prices_entry, nordpool_prices)

    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "nordpool_scheduler/subscribe",
            "entity_id": "sensor.nordpool_scheduler_prices_lv_electricity_price",
        }
    )
    response = await client.receive_json()
    assert response["success"]

    snapshot = (await client.receive_json())["event"]
    assert snapshot["target_entity"] is None
    assert snapshot["target_state"] is None
    assert any(slot["price"] is not None for slot in snapshot["slots"])
