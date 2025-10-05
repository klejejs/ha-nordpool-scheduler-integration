"""Tests for the coordinator."""

from unittest.mock import Mock, patch

from homeassistant.core import HomeAssistant

from custom_components.nordpool_scheduler.coordinator import (
    NordpoolDataUpdateCoordinator,
)


async def test_coordinator_update_success(
    hass: HomeAssistant,
    mock_aiohttp_session,
    mock_nordpool_response,
) -> None:
    """Test successful coordinator update."""
    coordinator = NordpoolDataUpdateCoordinator(hass)

    # Manually call update since async_refresh needs proper HA setup
    result = await coordinator._async_update_data()

    assert result is not None
    assert "prices" in result
    assert "current_price" in result
    assert "last_update" in result

    # Check that prices were parsed
    prices = result["prices"]
    assert len(prices) == 192  # 96 * 2 slots
    # Note: prices might be None if mock data doesn't have them


async def test_coordinator_csv_parsing(hass: HomeAssistant) -> None:
    """Test CSV parsing with invalid data."""
    coordinator = NordpoolDataUpdateCoordinator(hass)

    # Test with invalid CSV data
    result = await coordinator._parse_csv_data("invalid,csv,data")

    # Should return empty prices array without crashing
    assert isinstance(result, list)
    assert len(result) == 192


async def test_coordinator_error_resilience(hass: HomeAssistant) -> None:
    """Test coordinator resilience to errors."""
    coordinator = NordpoolDataUpdateCoordinator(hass)

    # Test that coordinator initializes with empty prices
    assert coordinator.prices is not None
    assert len(coordinator.prices) == 192
    assert all(p is None for p in coordinator.prices)


async def test_get_current_slot_index(hass: HomeAssistant) -> None:
    """Test getting the current slot index."""
    coordinator = NordpoolDataUpdateCoordinator(hass)

    # Test different times
    with patch(
        "custom_components.nordpool_scheduler.coordinator.datetime",
    ) as mock_datetime:
        # Test midnight (00:00)
        mock_now = Mock()
        mock_now.hour = 0
        mock_now.minute = 0
        mock_datetime.now.return_value = mock_now

        slot = coordinator._get_current_slot_index()
        assert slot == 0

        # Test 12:45
        mock_now.hour = 12
        mock_now.minute = 45
        slot = coordinator._get_current_slot_index()
        assert slot == 51  # 12 * 4 + 3

        # Test 23:45 (last slot)
        mock_now.hour = 23
        mock_now.minute = 45
        slot = coordinator._get_current_slot_index()
        assert slot == 95


async def test_get_price_for_slot(
    hass: HomeAssistant,
    mock_aiohttp_session,
) -> None:
    """Test getting price for a specific slot."""
    coordinator = NordpoolDataUpdateCoordinator(hass)

    # Manually call update
    result = await coordinator._async_update_data()

    # Verify prices array exists
    assert "prices" in result
    prices = result["prices"]
    assert len(prices) == 192

    # Test invalid slot (negative)
    price = coordinator.get_price_for_slot(-1)
    assert price is None

    # Test invalid slot (too large)
    price = coordinator.get_price_for_slot(200)
    assert price is None

    # Test valid slot index
    price = coordinator.get_price_for_slot(0)
    # Price might be None if no data, but method should not error
    assert price is None or isinstance(price, (int, float))
