"""DataUpdateCoordinator for Nordpool Scheduler."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import aiohttp
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    NORDPOOL_CSV_URL,
    SLOTS_PER_DAY,
    UPDATE_INTERVAL,
    VAT_MULTIPLIER,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# HTTP status constants
HTTP_OK = 200
CSV_FIELDS_COUNT = 3


class NordpoolDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Nordpool price data."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.prices: list[float | None] = [None] * (
            SLOTS_PER_DAY * 2
        )  # Today + tomorrow

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Nordpool."""
        try:
            async with asyncio.timeout(10):
                async with aiohttp.ClientSession() as session:
                    async with session.get(NORDPOOL_CSV_URL) as response:
                        if response.status != HTTP_OK:
                            msg = f"Error fetching Nordpool data: {response.status}"
                            raise UpdateFailed(msg)

                        csv_data = await response.text()
                        prices = await self._parse_csv_data(csv_data)

                        current_slot = self._get_current_slot_index()
                        current_price = (
                            prices[current_slot] if current_slot < len(prices) else None
                        )

                        return {
                            "prices": prices,
                            "current_price": current_price,
                            "last_update": datetime.now(UTC),
                        }
        except aiohttp.ClientError as err:
            msg = f"Error communicating with Nordpool API: {err}"
            raise UpdateFailed(msg) from err
        except TimeoutError as err:
            msg = f"Timeout fetching Nordpool data: {err}"
            raise UpdateFailed(msg) from err
        except Exception as err:
            msg = f"Unexpected error: {err}"
            raise UpdateFailed(msg) from err

    async def _parse_csv_data(self, csv_data: str) -> list[float | None]:
        """Parse CSV data from Nordpool."""
        try:
            # CSV times are in Europe/Riga (Latvia) timezone
            riga_tz = ZoneInfo("Europe/Riga")

            # Get start of today in UTC
            start_utc = datetime.now(UTC).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

            lines = csv_data.split("\n")[1:]  # Skip header
            rows = [line.split(";") for line in lines if line.strip()]

            parsed_data = []
            for row in rows:
                if len(row) == CSV_FIELDS_COUNT:
                    try:
                        # Nordpool CSV times are in Europe/Riga timezone (naive)
                        # Parse as naive datetime first
                        ts_start_naive = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                        ts_end_naive = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")

                        # Localize to Riga timezone then convert to UTC
                        ts_start_riga = ts_start_naive.replace(tzinfo=riga_tz)
                        ts_end_riga = ts_end_naive.replace(tzinfo=riga_tz)
                        ts_start_utc = ts_start_riga.astimezone(UTC)
                        ts_end_utc = ts_end_riga.astimezone(UTC)

                        # Only include data from today onwards (in UTC)
                        if ts_end_utc > start_utc:
                            # Calculate price with VAT in EUR/kWh
                            # CSV prices are already in EUR/kWh, just add VAT and round
                            price = round(float(row[2]) * VAT_MULTIPLIER, 4)
                            parsed_data.append(
                                {
                                    "ts_start": ts_start_utc.replace(tzinfo=None),
                                    "price": price,
                                },
                            )
                    except (ValueError, IndexError) as e:
                        _LOGGER.debug("Skipping invalid row: %s - %s", row, e)
                        continue

            parsed_data.sort(key=lambda x: x["ts_start"])

            # Extract just the prices and pad to 192 slots (2 days)
            prices = [item["price"] for item in parsed_data]
            padded_prices = [
                prices[i] if i < len(prices) else None for i in range(SLOTS_PER_DAY * 2)
            ]

            self.prices = padded_prices

        except Exception as err:
            _LOGGER.exception("Error parsing CSV data")
            msg = f"Error parsing CSV data: {err}"
            raise UpdateFailed(msg) from err
        else:
            return padded_prices

    def _get_current_slot_index(self) -> int:
        """Get the current slot index (0-95 for today)."""
        now = datetime.now(UTC)
        return now.hour * 4 + (now.minute // 15)

    def get_price_for_slot(self, slot_index: int) -> float | None:
        """Get price for a specific slot index."""
        if 0 <= slot_index < len(self.prices):
            return self.prices[slot_index]
        return None
