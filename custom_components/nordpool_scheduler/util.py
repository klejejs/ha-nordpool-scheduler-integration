"""Small shared helpers for Nordpool Scheduler."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.util import dt as dt_util

from .const import CONF_TARGET_ENTITY, SLOT_MINUTES

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, State


def is_prices_only(entry: ConfigEntry) -> bool:
    """Return whether the entry only supplies prices and controls no entity."""
    return CONF_TARGET_ENTITY not in {**entry.data, **entry.options}


def is_running(state: State | None) -> bool:
    """Return whether an entity's state counts as on."""
    return state is not None and state.state not in (
        STATE_OFF,
        STATE_UNAVAILABLE,
        STATE_UNKNOWN,
    )


def slot_start_for(moment: datetime) -> datetime:
    """Return the UTC start of the 15-minute slot containing ``moment``."""
    moment_utc = dt_util.as_utc(moment)
    minute = (moment_utc.minute // SLOT_MINUTES) * SLOT_MINUTES
    return moment_utc.replace(minute=minute, second=0, microsecond=0)


def local_midnight(hass: HomeAssistant, days_from_today: int = 0) -> datetime:
    """Return local midnight (HA's configured time zone) ``days_from_today`` in UTC."""
    tz = dt_util.get_time_zone(hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
    day = dt_util.utcnow().astimezone(tz).date() + timedelta(days=days_from_today)
    return dt_util.as_utc(datetime.combine(day, datetime.min.time(), tzinfo=tz))
