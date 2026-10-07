"""Websocket API used by the Nordpool Scheduler Lovelace card.

Rather than have the card poll or read stale entity attributes, it
subscribes to a snapshot that is pushed again whenever prices refresh, the
schedule changes, or a new slot starts.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONTROL_MODE,
    CONF_DEFAULT_STATE,
    CONF_TARGET_ENTITY,
    CONTROL_MODE_ON_CHANGE,
    DOMAIN,
    MAX_SLOT_LOOKAHEAD_DAYS,
    SLOT_MINUTES,
    SLOT_STATE_OFF,
    SLOT_STATE_ON,
    STATE_DEFAULT_OFF,
)
from .stats import WINDOWS
from .util import local_midnight, slot_start_for


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


def _on_off(*, on: bool) -> str:
    return SLOT_STATE_ON if on else SLOT_STATE_OFF


def _entity_id_for(hass: HomeAssistant, domain: str, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)


def _build_auto_snapshot(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Auto mode's state, settings and the entities that hold them."""
    runtime = entry.runtime_data
    entry_id = entry.entry_id
    return {
        "enabled": runtime.auto_enabled,
        "switch_entity": _entity_id_for(hass, "switch", f"{entry_id}_auto_mode"),
        "run_hours": runtime.run_hours,
        "max_price": runtime.max_price,
        "cheap_price": runtime.cheap_price,
        "run_hours_entity": _entity_id_for(hass, "number", f"{entry_id}_run_hours"),
        "max_price_entity": _entity_id_for(hass, "number", f"{entry_id}_max_price"),
        "cheap_price_entity": _entity_id_for(hass, "number", f"{entry_id}_cheap_price"),
    }


def _build_averages(entry: ConfigEntry) -> dict[str, Any]:
    """Return the average price and hours run for each stats window."""
    stats = entry.runtime_data.stats
    today = dt_util.now().date()
    averages = {}
    for window in WINDOWS:
        price, hours = stats.average(window.start(today))
        averages[window.key] = {"price": price, "running_hours": hours}
    return averages


def _build_snapshot(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Build the current schedule/price snapshot for one config entry."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    settings = {**entry.data, **entry.options}
    default_state = settings.get(CONF_DEFAULT_STATE, STATE_DEFAULT_OFF)
    target_entity = settings.get(CONF_TARGET_ENTITY)

    window_start = local_midnight(hass)
    window_end = local_midnight(hass, MAX_SLOT_LOOKAHEAD_DAYS)

    slots: list[dict[str, Any]] = []
    cursor = window_start
    while cursor < window_end:
        override = runtime.schedule.get(cursor)
        base_on, _source = runtime.base_state(cursor)
        effective_on, _source = runtime.slot_state(cursor)
        slots.append(
            {
                "start": cursor.isoformat(),
                "end": (cursor + timedelta(minutes=SLOT_MINUTES)).isoformat(),
                "price": coordinator.get_price(cursor),
                "override": None if override is None else _on_off(on=override),
                "base": _on_off(on=base_on),
                "auto": runtime.auto_pick(cursor),
                "effective": _on_off(on=effective_on),
            }
        )
        cursor += timedelta(minutes=SLOT_MINUTES)

    target_state = hass.states.get(target_entity) if target_entity else None

    return {
        "config_entry_id": entry.entry_id,
        "target_entity": target_entity,
        "default_state": default_state,
        "control_mode": settings.get(CONF_CONTROL_MODE, CONTROL_MODE_ON_CHANGE),
        "time_zone": hass.config.time_zone,
        "currency": coordinator.currency,
        "vat_percent": coordinator.vat_percent,
        "now_slot_start": slot_start_for(dt_util.utcnow()).isoformat(),
        "target_state": target_state.state if target_state else None,
        "auto": _build_auto_snapshot(hass, entry),
        "averages": _build_averages(entry),
        "slots": slots,
    }


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
            websocket_api.event_message(msg["id"], _build_snapshot(hass, entry))
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
