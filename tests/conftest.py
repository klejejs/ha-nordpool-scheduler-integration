"""Fixtures for Nordpool Scheduler tests."""

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler.const import (
    CONF_DEFAULT_STATE,
    CONF_SCHEDULER_NAME,
    CONF_TARGET_SWITCH,
    DEFAULT_STATE_OFF,
    DOMAIN,
)


# This fixture enables loading custom integrations in all tests.
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Enable custom integrations for all tests."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SCHEDULER_NAME: "test_scheduler",
            CONF_TARGET_SWITCH: "switch.test_switch",
            CONF_DEFAULT_STATE: DEFAULT_STATE_OFF,
        },
        entry_id="test_entry_id",
        unique_id="test_scheduler_switch.test_switch",
    )


@pytest.fixture
def mock_nordpool_response() -> str:
    """Return a mock Nordpool CSV response."""
    return """timestamp_start;timestamp_end;price
2024-01-01 00:00:00;2024-01-01 01:00:00;10.5
2024-01-01 01:00:00;2024-01-01 02:00:00;11.2
2024-01-01 02:00:00;2024-01-01 03:00:00;9.8
2024-01-01 03:00:00;2024-01-01 04:00:00;8.5
2024-01-01 04:00:00;2024-01-01 05:00:00;7.9
2024-01-01 05:00:00;2024-01-01 06:00:00;8.2
2024-01-01 06:00:00;2024-01-01 07:00:00;12.5
2024-01-01 07:00:00;2024-01-01 08:00:00;15.8
2024-01-01 08:00:00;2024-01-01 09:00:00;18.2
2024-01-01 09:00:00;2024-01-01 10:00:00;17.5
2024-01-01 10:00:00;2024-01-01 11:00:00;16.8
2024-01-01 11:00:00;2024-01-01 12:00:00;15.2
2024-01-01 12:00:00;2024-01-01 13:00:00;14.5
2024-01-01 13:00:00;2024-01-01 14:00:00;13.8
2024-01-01 14:00:00;2024-01-01 15:00:00;14.2
2024-01-01 15:00:00;2024-01-01 16:00:00;15.5
2024-01-01 16:00:00;2024-01-01 17:00:00;17.8
2024-01-01 17:00:00;2024-01-01 18:00:00;19.2
2024-01-01 18:00:00;2024-01-01 19:00:00;18.5
2024-01-01 19:00:00;2024-01-01 20:00:00;17.2
2024-01-01 20:00:00;2024-01-01 21:00:00;15.8
2024-01-01 21:00:00;2024-01-01 22:00:00;14.2
2024-01-01 22:00:00;2024-01-01 23:00:00;12.5
2024-01-01 23:00:00;2024-01-02 00:00:00;11.2"""


@pytest.fixture
def mock_aiohttp_session(mock_nordpool_response: str) -> Generator:
    """Mock aiohttp ClientSession."""
    mock_response = Mock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value=mock_nordpool_response)

    mock_session = Mock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock()
    mock_session.get = Mock(return_value=mock_response)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock()

    with patch("aiohttp.ClientSession", return_value=mock_session):
        yield mock_session


@pytest.fixture
async def mock_switch(hass: HomeAssistant) -> None:
    """Set up a mock switch."""
    hass.states.async_set("switch.test_switch", "off")
