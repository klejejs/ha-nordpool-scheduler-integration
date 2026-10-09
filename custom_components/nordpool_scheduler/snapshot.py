"""Snapshots of a scheduler's prices and schedule, as the card reads them."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import entity_registry as er
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

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_FLAGS = {SLOT_STATE_ON: "1", SLOT_STATE_OFF: "0", True: "1", False: "0", None: "-"}


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
        "window_enabled": runtime.window_enabled,
        "window_start": runtime.window_start.strftime("%H:%M"),
        "window_end": runtime.window_end.strftime("%H:%M"),
        "cheap_all_day": runtime.cheap_all_day,
        "window_enabled_entity": _entity_id_for(
            hass, "switch", f"{entry_id}_window_enabled"
        ),
        "window_start_entity": _entity_id_for(hass, "time", f"{entry_id}_window_start"),
        "window_end_entity": _entity_id_for(hass, "time", f"{entry_id}_window_end"),
        "cheap_all_day_entity": _entity_id_for(
            hass, "switch", f"{entry_id}_cheap_all_day"
        ),
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


def build_snapshot(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
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


def build_published_snapshot(
    hass: HomeAssistant, entry: ConfigEntry, entity_id: str
) -> dict[str, Any]:
    """Build the snapshot packed small enough to publish as a state attribute.

    Slots are consecutive, so each slot field becomes one list or string
    indexed by slot, with "1" for on, "0" for off and "-" for none.
    """
    snapshot = build_snapshot(hass, entry)
    slots = snapshot.pop("slots")
    return {
        **snapshot,
        "entity_id": entity_id,
        "slots_start": slots[0]["start"],
        "slot_prices": [slot["price"] for slot in slots],
        "slot_overrides": "".join(_FLAGS[slot["override"]] for slot in slots),
        "slot_base": "".join(_FLAGS[slot["base"]] for slot in slots),
        "slot_auto": "".join(_FLAGS[slot["auto"]] for slot in slots),
    }
