"""Small shared helpers for Nordpool Scheduler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .const import SLOT_MINUTES

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant


def slot_start_for(moment: datetime) -> datetime:
    """Return the UTC start of the 15-minute slot containing ``moment``."""
    moment_utc = dt_util.as_utc(moment)
    minute = (moment_utc.minute // SLOT_MINUTES) * SLOT_MINUTES
    return moment_utc.replace(minute=minute, second=0, microsecond=0)


def local_midnight_today(hass: HomeAssistant) -> datetime:
    """Return today's local midnight (HA's configured time zone) in UTC."""
    tz = dt_util.get_time_zone(hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
    now_local = dt_util.utcnow().astimezone(tz)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt_util.as_utc(midnight_local)
