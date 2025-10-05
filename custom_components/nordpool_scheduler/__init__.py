"""The Nordpool Scheduler integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.event import async_track_time_change

from .const import (
    ATTR_ENTRY_ID,
    ATTR_SCHEDULE,
    ATTR_SLOTS,
    CONF_DEFAULT_STATE,
    CONF_TARGET_SWITCH,
    DEFAULT_STATE_OFF,
    DEFAULT_STATE_ON,
    DOMAIN,
    MINUTES_PER_SLOT,
    SERVICE_CLEAR_SCHEDULE,
    SERVICE_GET_SCHEDULE,
    SERVICE_SET_SCHEDULE,
    SLOTS_PER_DAY,
)
from .coordinator import NordpoolDataUpdateCoordinator

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nordpool Scheduler from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create coordinator if it doesn't exist (shared across all config entries)
    if "coordinator" not in hass.data[DOMAIN]:
        coordinator = NordpoolDataUpdateCoordinator(hass)
        await coordinator.async_config_entry_first_refresh()
        hass.data[DOMAIN]["coordinator"] = coordinator

    coordinator = hass.data[DOMAIN]["coordinator"]

    # Store entry data
    # Schedule is a dict (key: slot index, value: desired state)
    # If a slot is not in the dict, use the default_state from config
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "config": entry.data,
        "schedule": {},  # Dict[int, bool] - only store overrides
        "listeners": [],
    }

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up time-based automation listeners
    await _async_setup_automations(hass, entry)

    # Register services if not already registered
    if not hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
        await _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Remove listeners
    if entry.entry_id in hass.data[DOMAIN]:
        for listener in hass.data[DOMAIN][entry.entry_id]["listeners"]:
            listener()
        hass.data[DOMAIN][entry.entry_id]["listeners"].clear()

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_setup_automations(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up internal time-based automations for each 15-minute slot."""
    entry_data = hass.data[DOMAIN][entry.entry_id]

    # Create a listener for each 15-minute slot
    for slot in range(SLOTS_PER_DAY):
        hour = slot // 4
        minute = (slot % 4) * MINUTES_PER_SLOT

        # Create the automation callback
        @callback
        def automation_callback(_now: datetime, slot_index: int = slot) -> None:
            """Handle the automation trigger."""
            _LOGGER.debug(
                "Automation triggered for entry %s at slot %d (%02d:%02d)",
                entry.entry_id,
                slot_index,
                slot_index // 4,
                (slot_index % 4) * MINUTES_PER_SLOT,
            )

            entry_data = hass.data[DOMAIN].get(entry.entry_id)
            if not entry_data:
                return

            schedule = entry_data["schedule"]
            config = entry_data["config"]
            target = config[CONF_TARGET_SWITCH]
            default_state = config.get(CONF_DEFAULT_STATE, DEFAULT_STATE_OFF)

            # Determine the desired switch state for this slot
            # If slot is in schedule dict, use that value
            # Otherwise, use default_state
            if slot_index in schedule:
                desired_state = schedule[slot_index]
            else:
                desired_state = default_state == DEFAULT_STATE_ON

            # Turn on or off based on desired state
            service = "turn_on" if desired_state else "turn_off"
            # Extract domain from entity_id (e.g., "switch.my_switch" -> "switch")
            domain = target.split(".")[0]
            hass.async_create_task(
                hass.services.async_call(
                    domain,
                    service,
                    {"entity_id": target},
                ),
            )

            # Remove the previous slot from schedule (to allow re-scheduling)
            prev_slot = (slot_index - 1) % SLOTS_PER_DAY
            schedule.pop(prev_slot, None)

        # Register the listener
        listener = async_track_time_change(
            hass,
            automation_callback,
            hour=hour,
            minute=minute,
            second=0,
        )

        entry_data["listeners"].append(listener)

    _LOGGER.info(
        "Set up %d time-based automations for entry %s",
        SLOTS_PER_DAY,
        entry.entry_id,
    )


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register services for the integration."""

    async def handle_set_schedule(call: ServiceCall) -> None:
        """Handle the set_schedule service call."""
        entry_id = call.data[ATTR_ENTRY_ID]
        slots = call.data[ATTR_SLOTS]

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Invalid entry_id: %s", entry_id)
            return

        entry_data = hass.data[DOMAIN][entry_id]

        # Update schedule - store only the overrides
        for slot_index, enabled in slots.items():
            slot_int = int(slot_index)
            if 0 <= slot_int < SLOTS_PER_DAY:
                # Store the override state for this slot
                entry_data["schedule"][slot_int] = bool(enabled)

        _LOGGER.debug("Updated schedule for entry %s: %s", entry_id, slots)

    async def handle_clear_schedule(call: ServiceCall) -> None:
        """Handle the clear_schedule service call."""
        entry_id = call.data[ATTR_ENTRY_ID]

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Invalid entry_id: %s", entry_id)
            return

        entry_data = hass.data[DOMAIN][entry_id]
        entry_data["schedule"] = {}  # Clear all overrides

        _LOGGER.debug("Cleared schedule for entry %s", entry_id)

    async def handle_get_schedule(call: ServiceCall) -> dict[str, dict] | None:
        """Handle the get_schedule service call."""
        entry_id = call.data[ATTR_ENTRY_ID]

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Invalid entry_id: %s", entry_id)
            return None

        entry_data = hass.data[DOMAIN][entry_id]
        schedule = entry_data["schedule"]

        return {ATTR_SCHEDULE: schedule}

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        handle_set_schedule,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTRY_ID): str,
                vol.Required(ATTR_SLOTS): {str: bool},
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_SCHEDULE,
        handle_clear_schedule,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTRY_ID): str,
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SCHEDULE,
        handle_get_schedule,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTRY_ID): str,
            },
        ),
    )

    _LOGGER.info("Registered services for %s", DOMAIN)
