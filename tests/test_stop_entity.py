"""Tests for the stop entity, which holds the target off while it is on."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.nordpool_scheduler.const import (
    CONF_CONTROL_MODE,
    CONF_DEFAULT_STATE,
    CONF_STOP_ENTITY,
    CONF_TARGET_ENTITY,
    CONF_VAT_PERCENT,
    CONTROL_MODE_ENFORCE,
    CONTROL_MODE_ON_CHANGE,
    DOMAIN,
    STATE_DEFAULT_ON,
)
from custom_components.nordpool_scheduler.util import slot_start_for

from .conftest import OSLO_TZ, setup_scheduler_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from pytest_homeassistant_custom_component.typing import WebSocketGenerator

STOP = "binary_sensor.bathroom_too_hot"
SCHEDULED_ON = "binary_sensor.nordpool_scheduler_test_scheduled_on"
PRICE_SENSOR = "sensor.nordpool_scheduler_test_electricity_price"


async def _setup_with_stop(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    nordpool_prices: dict[date, list],
    *,
    stop_state: str | None = "off",
    **options: str,
) -> None:
    """Set up a Default ON scheduler whose stop entity is ``STOP``."""
    if stop_state is not None:
        hass.states.async_set(STOP, stop_state)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_DEFAULT_STATE: STATE_DEFAULT_ON,
            CONF_STOP_ENTITY: STOP,
            **options,
        },
    )
    await setup_scheduler_entry(hass, entry, nordpool_prices)


async def _set_stop(hass: HomeAssistant, state: str, **attributes: str) -> None:
    hass.states.async_set(STOP, state, attributes)
    await hass.async_block_till_done()


async def test_options_flow_sets_and_clears_stop_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The stop entity is optional, and leaving it empty removes it."""
    hass.states.async_set(STOP, "off")
    await setup_scheduler_entry(hass, mock_config_entry, nordpool_prices)
    base = {
        CONF_TARGET_ENTITY: mock_target,
        CONF_DEFAULT_STATE: "off",
        CONF_CONTROL_MODE: CONTROL_MODE_ON_CHANGE,
        CONF_VAT_PERCENT: 21,
    }

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, CONF_STOP_ENTITY: STOP}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert mock_config_entry.options[CONF_STOP_ENTITY] == STOP
    assert mock_config_entry.runtime_data.stop_entity == STOP

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], base)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert CONF_STOP_ENTITY not in mock_config_entry.options
    assert mock_config_entry.runtime_data.stop_entity is None


async def test_options_flow_rejects_bad_stop_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A stop entity that doesn't exist, or is the target itself, is refused."""
    await setup_scheduler_entry(hass, mock_config_entry, nordpool_prices)
    base = {
        CONF_TARGET_ENTITY: mock_target,
        CONF_DEFAULT_STATE: "off",
        CONF_CONTROL_MODE: CONTROL_MODE_ON_CHANGE,
        CONF_VAT_PERCENT: 21,
    }

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, CONF_STOP_ENTITY: "binary_sensor.missing"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_stop_entity"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, CONF_STOP_ENTITY: mock_target}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "stop_is_target"}


async def test_stop_entity_turns_target_off_and_back_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The target goes off as soon as the stop entity turns on, and back after."""
    await _setup_with_stop(hass, mock_config_entry, nordpool_prices)
    assert hass.states.get(mock_target).state == "on"

    await _set_stop(hass, "on")
    assert hass.states.get(mock_target).state == "off"
    scheduled = hass.states.get(SCHEDULED_ON)
    assert scheduled.state == "off"
    assert scheduled.attributes["source"] == "stopped"

    await _set_stop(hass, "off")
    assert hass.states.get(mock_target).state == "on"
    assert hass.states.get(SCHEDULED_ON).attributes["source"] == "default"


async def test_stop_entity_beats_an_override(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A slot overridden on is still held off while the stop entity is on."""
    await _setup_with_stop(
        hass, mock_config_entry, nordpool_prices, default_state="off"
    )
    await hass.services.async_call(
        DOMAIN,
        "set_slots",
        {
            "config_entry": mock_config_entry.entry_id,
            "slots": [
                {
                    "start": slot_start_for(datetime.now(OSLO_TZ)).isoformat(),
                    "state": "on",
                }
            ],
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(mock_target).state == "on"

    await _set_stop(hass, "on")
    assert hass.states.get(mock_target).state == "off"

    await _set_stop(hass, "off")
    assert hass.states.get(mock_target).state == "on"


async def test_stop_entity_starts_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """A stop entity already on at setup keeps the target off from the start."""
    await _setup_with_stop(hass, mock_config_entry, nordpool_prices, stop_state="on")
    assert hass.states.get(mock_target).state == "off"


async def test_unavailable_or_missing_stop_entity_is_ignored(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The schedule runs as usual while the stop entity reports nothing."""
    await _setup_with_stop(hass, mock_config_entry, nordpool_prices, stop_state=None)
    assert hass.states.get(mock_target).state == "on"

    await _set_stop(hass, "on")
    assert hass.states.get(mock_target).state == "off"

    await _set_stop(hass, "unavailable")
    assert hass.states.get(mock_target).state == "on"


async def test_enforce_mode_keeps_target_off_while_stopped(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """In enforce mode a target turned on by hand goes off at the next slot."""
    await _setup_with_stop(
        hass,
        mock_config_entry,
        nordpool_prices,
        stop_state="on",
        control_mode=CONTROL_MODE_ENFORCE,
    )
    hass.states.async_set(mock_target, "on")

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=15))
    await hass.async_block_till_done()
    assert hass.states.get(mock_target).state == "off"


async def test_stop_attribute_change_does_nothing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """Only a change between on and not on re-checks the target."""
    await _setup_with_stop(hass, mock_config_entry, nordpool_prices)
    calls = async_capture_events(hass, EVENT_CALL_SERVICE)

    await _set_stop(hass, "off", friendly_name="Bathroom too hot")
    await _set_stop(hass, "unavailable")

    assert not [
        call for call in calls if call.data["service"] in ("turn_on", "turn_off")
    ]


async def test_snapshot_reports_stop_entity(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_config_entry: MockConfigEntry,
    mock_nordpool_service: None,
    mock_target: str,
    nordpool_prices: dict[date, list],
) -> None:
    """The card's snapshot names the stop entity and whether it is stopping."""
    await _setup_with_stop(hass, mock_config_entry, nordpool_prices)
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "nordpool_scheduler/subscribe", "entity_id": PRICE_SENSOR}
    )
    assert (await client.receive_json())["success"]
    snapshot = (await client.receive_json())["event"]
    assert snapshot["stop_entity"] == STOP
    assert snapshot["stopped"] is False

    await _set_stop(hass, "on")
    snapshot = (await client.receive_json())["event"]
    assert snapshot["stopped"] is True
    current = next(
        slot
        for slot in snapshot["slots"]
        if slot["start"] == snapshot["now_slot_start"]
    )
    assert current["effective"] == "on"
