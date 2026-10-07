"""Tests that scheduling works across every supported target domain."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nordpool_scheduler.const import (
    CONF_AREA,
    CONF_DEFAULT_STATE,
    CONF_NORDPOOL_ENTRY_ID,
    CONF_SCHEDULER_NAME,
    CONF_TARGET_ENTITY,
    DOMAIN,
    STATE_DEFAULT_OFF,
)
from custom_components.nordpool_scheduler.control import async_apply_slot
from custom_components.nordpool_scheduler.util import slot_start_for

from .conftest import AREA, setup_scheduler_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.mark.parametrize(
    "target_entity",
    [
        "switch.test_device",
        "input_boolean.test_toggle",
        "light.test_light",
        "fan.test_fan",
        "climate.test_climate",
    ],
)
async def test_scheduling_turns_on_each_supported_domain(
    hass: HomeAssistant,
    mock_nordpool_entry: MockConfigEntry,
    mock_nordpool_service: None,
    nordpool_prices: dict[date, list],
    target_entity: str,
) -> None:
    """A slot scheduled on calls <domain>.turn_on for every supported domain."""
    hass.states.async_set(target_entity, "off")
    domain = target_entity.split(".")[0]

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SCHEDULER_NAME: "Test",
            CONF_TARGET_ENTITY: target_entity,
            CONF_DEFAULT_STATE: STATE_DEFAULT_OFF,
            CONF_NORDPOOL_ENTRY_ID: mock_nordpool_entry.entry_id,
            CONF_AREA: AREA,
        },
    )
    # Set up before registering the fakes: our own scheduler forwards to
    # Platform.SWITCH, which for the "switch" domain case would otherwise
    # load the real switch component and overwrite our fake handler.
    await setup_scheduler_entry(hass, entry, nordpool_prices)

    calls: list[str] = []
    hass.services.async_register(
        domain, "turn_on", lambda call: calls.append(call.service)
    )
    hass.services.async_register(domain, "turn_off", lambda _call: None)

    now = datetime.now(UTC)
    entry.runtime_data.schedule.set_slot(slot_start_for(now), state=True)
    await async_apply_slot(hass, entry, now)
    await hass.async_block_till_done()

    assert calls == ["turn_on"]
