"""DataUpdateCoordinator for Nordpool Scheduler.

Prices are sourced from the core ``nordpool`` integration's
``get_prices_for_date`` service rather than fetched directly, so this
coordinator never talks to the network itself.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AREA,
    CONF_NORDPOOL_ENTRY_ID,
    CONF_VAT_PERCENT,
    DEFAULT_VAT_PERCENT,
    DOMAIN,
    NORDPOOL_DOMAIN,
    NORDPOOL_SERVICE_GET_PRICES_FOR_DATE,
    NORDPOOL_TIMEZONE_NAME,
    SLOT_MINUTES,
)
from .util import slot_start_for

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

REFRESH_INTERVAL = timedelta(hours=1)
# Nord Pool typically publishes next-day prices between 13:00 and 15:00 CET.
PUBLISH_CHECK_HOUR = 13
PUBLISH_CHECK_MINUTE = 5


class NordpoolSchedulerPriceCoordinator(DataUpdateCoordinator[dict[datetime, float]]):
    """Fetch Nord Pool prices via the core nordpool integration and cache them.

    ``data`` maps each slot's UTC start timestamp to its price in cents
    (1/100 of the Nord Pool config entry's currency) per kWh, including VAT.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=REFRESH_INTERVAL,
        )
        self.nordpool_entry_id: str = entry.data[CONF_NORDPOOL_ENTRY_ID]
        self.area: str = entry.data[CONF_AREA]
        self.currency: str = "EUR"
        self._publish_check_unsub: CALLBACK_TYPE | None = None
        self._slot_tick_unsub: CALLBACK_TYPE | None = None
        self._oslo_tz: ZoneInfo | None = None

    @property
    def vat_percent(self) -> float:
        """Return the currently configured VAT percentage."""
        entry = self.config_entry
        return entry.options.get(
            CONF_VAT_PERCENT,
            entry.data.get(CONF_VAT_PERCENT, DEFAULT_VAT_PERCENT),
        )

    async def _async_setup(self) -> None:
        """Resolve the Nord Pool currency and schedule the publish-time check."""
        nordpool_entry = self.hass.config_entries.async_get_entry(
            self.nordpool_entry_id
        )
        if nordpool_entry is None:
            msg = "The configured Nord Pool config entry no longer exists"
            raise UpdateFailed(msg)
        self.currency = nordpool_entry.data.get("currency", "EUR")

        self._oslo_tz = await dt_util.async_get_time_zone(NORDPOOL_TIMEZONE_NAME)
        self._schedule_publish_check()
        self._schedule_slot_tick()
        self.config_entry.async_on_unload(self._cancel_timers)

    def _schedule_publish_check(self) -> None:
        """Schedule an extra refresh around the time next-day prices publish."""
        now_oslo = dt_util.utcnow().astimezone(self._oslo_tz)
        next_check = now_oslo.replace(
            hour=PUBLISH_CHECK_HOUR,
            minute=PUBLISH_CHECK_MINUTE,
            second=0,
            microsecond=0,
        )
        if next_check <= now_oslo:
            next_check += timedelta(days=1)

        self._publish_check_unsub = async_track_point_in_utc_time(
            self.hass,
            self._async_publish_check,
            next_check.astimezone(dt_util.UTC),
        )

    async def _async_publish_check(self, _now: datetime) -> None:
        """Refresh once around publish time, then reschedule for tomorrow."""
        self._schedule_publish_check()
        await self.async_request_refresh()

    def _schedule_slot_tick(self) -> None:
        """Schedule a listener notification at the next 15-minute boundary.

        This lets entities recompute ``native_value`` (the current slot's
        price) as time passes, even between price fetches.
        """
        next_tick = slot_start_for(dt_util.utcnow()) + timedelta(minutes=SLOT_MINUTES)
        self._slot_tick_unsub = async_track_point_in_utc_time(
            self.hass, self._async_slot_tick, next_tick
        )

    @callback
    def _async_slot_tick(self, _now: datetime) -> None:
        self._schedule_slot_tick()
        self.async_update_listeners()

    def _cancel_timers(self) -> None:
        if self._publish_check_unsub:
            self._publish_check_unsub()
            self._publish_check_unsub = None
        if self._slot_tick_unsub:
            self._slot_tick_unsub()
            self._slot_tick_unsub = None

    async def _async_update_data(self) -> dict[datetime, float]:
        """Fetch yesterday, today and tomorrow's prices (Nord Pool/CET days)."""
        today_oslo = dt_util.utcnow().astimezone(self._oslo_tz).date()

        prices: dict[datetime, float] = {}
        have_any = False
        for offset in (-1, 0, 1):
            day = today_oslo + timedelta(days=offset)
            try:
                day_prices = await self._async_fetch_day(day)
            except NordpoolUnavailableError as err:
                # Tomorrow's prices are simply not published yet; that's fine.
                # Today or yesterday missing is a real (if unusual) failure.
                if offset == 1:
                    continue
                raise UpdateFailed(str(err)) from err
            prices.update(day_prices)
            have_any = True

        if not have_any:
            msg = "Nord Pool returned no price data"
            raise UpdateFailed(msg)

        return prices

    async def _async_fetch_day(self, day: date) -> dict[datetime, float]:
        """Fetch one CET delivery day of prices, converted to cents/kWh."""
        try:
            response = await self.hass.services.async_call(
                NORDPOOL_DOMAIN,
                NORDPOOL_SERVICE_GET_PRICES_FOR_DATE,
                {
                    "config_entry": self.nordpool_entry_id,
                    "date": day.isoformat(),
                    "areas": [self.area],
                },
                blocking=True,
                return_response=True,
            )
        except ServiceValidationError as err:
            raise NordpoolUnavailableError(str(err)) from err
        except HomeAssistantError as err:
            msg = f"Error calling nordpool.get_prices_for_date: {err}"
            raise UpdateFailed(msg) from err

        area_entries = (response or {}).get(self.area) or []
        if not area_entries:
            msg = f"No prices published yet for {day}"
            raise NordpoolUnavailableError(msg)

        vat_multiplier = 1 + self.vat_percent / 100
        day_prices: dict[datetime, float] = {}
        for entry in area_entries:
            start = dt_util.parse_datetime(entry["start"])
            end = dt_util.parse_datetime(entry["end"])
            if start is None or end is None:
                continue
            # Nord Pool reports per MWh: /1000 for kWh, *100 for cents.
            price = round(entry["price"] / 10 * vat_multiplier, 4)
            # Nord Pool's delivery periods aren't guaranteed to be 15 minutes
            # (an hourly market reports one entry per hour); fan each entry
            # out over every scheduler slot it actually covers.
            slot_start = dt_util.as_utc(start)
            slot_end = dt_util.as_utc(end)
            while slot_start < slot_end:
                day_prices[slot_start] = price
                slot_start += timedelta(minutes=SLOT_MINUTES)
        return day_prices

    def get_price(self, slot_start: datetime) -> float | None:
        """Return the known price for the slot starting at ``slot_start``."""
        if not self.data:
            return None
        return self.data.get(slot_start)


class NordpoolUnavailableError(HomeAssistantError):
    """Raised when Nord Pool has no prices for a requested day yet."""
