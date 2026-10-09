"""Websocket API used by the Nordpool Scheduler Lovelace card.

Rather than have the card poll or read stale entity attributes, it
subscribes to a snapshot that is pushed again whenever prices refresh, the
schedule changes, or a new slot starts.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .snapshot import build_snapshot


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_subscribe)


def _entry_for_sensor(hass: HomeAssistant, entity_id: str) -> ConfigEntry | None:
    """Find the scheduler config entry that owns a sensor/binary_sensor entity."""
    registry_entry = er.async_get(hass).async_get(entity_id)
    if registry_entry is None or registry_entry.platform != DOMAIN:
        return None
    if registry_entry.config_entry_id is None:
        return None
    return hass.config_entries.async_get_entry(registry_entry.config_entry_id)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nordpool_scheduler/subscribe",
        vol.Required("entity_id"): cv.entity_id,
    }
)
@callback
def ws_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to schedule/price snapshots for one scheduler entity."""
    entry = _entry_for_sensor(hass, msg["entity_id"])
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(
            msg["id"], "not_found", "Unknown Nordpool Scheduler entity"
        )
        return

    @callback
    def send_snapshot(*_args: Any) -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], build_snapshot(hass, entry))
        )

    runtime = entry.runtime_data
    unsub_schedule = async_dispatcher_connect(
        hass, runtime.update_signal, send_snapshot
    )
    unsub_coordinator = runtime.coordinator.async_add_listener(send_snapshot)

    def unsubscribe() -> None:
        unsub_schedule()
        unsub_coordinator()

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
    send_snapshot()
