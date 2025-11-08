"""The Nordpool Scheduler integration."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import voluptuous as vol
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.helpers.event import async_track_time_change

from .const import (
    ATTR_DATE,
    ATTR_ENABLED,
    ATTR_ENTRY_ID,
    ATTR_SCHEDULE,
    ATTR_SLOT_INDEX,
    ATTR_SLOTS,
    CONF_DEFAULT_STATE,
    CONF_SCHEDULE,
    CONF_TARGET_SWITCH,
    DEFAULT_STATE_OFF,
    DEFAULT_STATE_ON,
    DOMAIN,
    MAX_SCHEDULE_DAYS_AHEAD,
    MINUTES_PER_SLOT,
    SERVICE_CLEAR_SCHEDULE,
    SERVICE_GET_SCHEDULE,
    SERVICE_SET_SCHEDULE,
    SERVICE_SET_SLOT,
    SLOTS_PER_DAY,
)
from .coordinator import NordpoolDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


def _get_schedule_key(target_date: date, slot_index: int) -> str:
    """Create a schedule key from date and slot index."""
    return f"{target_date.isoformat()}_{slot_index}"


def _parse_schedule_key(key: str) -> tuple[date, int] | None:
    """Parse a schedule key into date and slot index.

    Returns None if the key is invalid or in old format.
    """
    try:
        date_str, slot_str = key.split("_")
        target_date = date.fromisoformat(date_str)
        slot_index = int(slot_str)
    except (ValueError, AttributeError):
        return None
    else:
        return target_date, slot_index


def _validate_schedule_date(target_date: date, riga_tz: ZoneInfo) -> bool:
    """Validate that the date is within allowed range (today or tomorrow)."""
    today = datetime.now(riga_tz).date()
    max_date = today + timedelta(days=MAX_SCHEDULE_DAYS_AHEAD)
    return today <= target_date <= max_date


def _clean_expired_overrides(schedule: dict, riga_tz: ZoneInfo) -> None:
    """Remove schedule overrides for past times."""
    now_riga = datetime.now(riga_tz)
    today = now_riga.date()
    current_slot = now_riga.hour * 4 + (now_riga.minute // 15)

    keys_to_remove = []
    for key in schedule:
        parsed = _parse_schedule_key(key)
        if not parsed:
            # Invalid format, remove it
            keys_to_remove.append(key)
            continue

        target_date, slot_index = parsed
        # Remove if date is in the past, or if today but slot has passed
        if target_date < today or (target_date == today and slot_index < current_slot):
            keys_to_remove.append(key)

    for key in keys_to_remove:
        schedule.pop(key, None)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nordpool Scheduler from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create coordinator if it doesn't exist (shared across all config entries)
    if "coordinator" not in hass.data[DOMAIN]:
        coordinator = NordpoolDataUpdateCoordinator(hass)
        await coordinator.async_config_entry_first_refresh()
        hass.data[DOMAIN]["coordinator"] = coordinator

    coordinator = hass.data[DOMAIN]["coordinator"]

    # Load persisted schedule from config entry
    # Keys are in "YYYY-MM-DD_slot" format (date-based scheduling)
    riga_tz = ZoneInfo("Europe/Riga")
    loaded_schedule = dict(entry.data.get(CONF_SCHEDULE, {}))

    # Clean up expired overrides (past dates/slots)
    _clean_expired_overrides(loaded_schedule, riga_tz)

    # Store entry data
    # Schedule is a dict (key: "YYYY-MM-DD_slot", value: desired state)
    # If a slot is not in the dict, use the default_state from config
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "config": entry.data,
        "schedule": loaded_schedule,  # Dict[str, bool] - date_slot format
        "listeners": [],
        "riga_tz": riga_tz,  # Store timezone for easy access
    }

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up time-based automation listeners
    await _async_setup_automations(hass, entry)

    # Set initial state based on current time slot and default state
    await _async_set_initial_state(hass, entry)

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

        # Check if this was the last config entry
        # If so, stop the shared coordinator to prevent unnecessary polling
        remaining_entries = [key for key in hass.data[DOMAIN] if key != "coordinator"]
        if not remaining_entries and "coordinator" in hass.data[DOMAIN]:
            coordinator = hass.data[DOMAIN]["coordinator"]
            await coordinator.async_shutdown()
            hass.data[DOMAIN].pop("coordinator")
            _LOGGER.info("Stopped shared coordinator - no config entries remain")

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
            riga_tz = entry_data["riga_tz"]

            # Calculate the schedule key for this slot at current date
            today = datetime.now(riga_tz).date()
            schedule_key = _get_schedule_key(today, slot_index)

            # Determine the desired switch state for this slot
            # If slot is in schedule dict, use that value
            # Otherwise, use default_state
            if schedule_key in schedule:
                desired_state = schedule[schedule_key]
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

            # Remove the current slot override after it's been used
            # This allows the slot to be re-scheduled and prevents stale overrides
            if schedule_key in schedule:
                schedule.pop(schedule_key)
                # Persist the removal to disk
                hass.async_create_task(_async_save_schedule(hass, entry.entry_id))

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


async def _async_set_initial_state(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set the initial state of the target entity based on current time slot."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    schedule = entry_data["schedule"]
    config = entry_data["config"]
    target = config[CONF_TARGET_SWITCH]
    default_state = config.get(CONF_DEFAULT_STATE, DEFAULT_STATE_OFF)
    riga_tz = entry_data["riga_tz"]

    # Get current slot index and date in Riga timezone
    now_riga = datetime.now(riga_tz)
    today = now_riga.date()
    current_slot = now_riga.hour * 4 + (now_riga.minute // 15)
    schedule_key = _get_schedule_key(today, current_slot)

    # Determine the desired state for current slot
    if schedule_key in schedule:
        desired_state = schedule[schedule_key]
    else:
        desired_state = default_state == DEFAULT_STATE_ON

    # Set the entity to the correct state
    service = "turn_on" if desired_state else "turn_off"
    domain = target.split(".")[0]

    _LOGGER.info(
        "Setting initial state for entry %s: slot %d (%02d:%02d) -> %s",
        entry.entry_id,
        current_slot,
        current_slot // 4,
        (current_slot % 4) * MINUTES_PER_SLOT,
        service,
    )

    try:
        await hass.services.async_call(
            domain,
            service,
            {"entity_id": target},
            blocking=True,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Could not set initial state for %s: %s (will be set at next slot change)",
            target,
            err,
        )


async def _async_save_schedule(hass: HomeAssistant, entry_id: str) -> None:
    """Save schedule to config entry for persistence across restarts."""
    if entry_id not in hass.data[DOMAIN]:
        return

    entry_data = hass.data[DOMAIN][entry_id]
    schedule = entry_data["schedule"]

    # Get the config entry
    entry = hass.config_entries.async_get_entry(entry_id)
    if not entry:
        _LOGGER.error("Config entry not found: %s", entry_id)
        return

    # Convert schedule dict to have string keys (required for JSON serialization)
    schedule_for_storage = {str(k): v for k, v in schedule.items()}

    # Update the config entry with the new schedule
    new_data = {**entry.data, CONF_SCHEDULE: schedule_for_storage}
    hass.config_entries.async_update_entry(entry, data=new_data)

    _LOGGER.debug("Persisted schedule for entry %s: %s", entry_id, schedule)


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register services for the integration."""

    async def handle_set_schedule(call: ServiceCall) -> None:
        """Handle the set_schedule service call."""
        entry_id = call.data[ATTR_ENTRY_ID]
        slots = call.data[ATTR_SLOTS]
        date_str = call.data.get(ATTR_DATE)  # Optional, defaults to today

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Invalid entry_id: %s", entry_id)
            return

        entry_data = hass.data[DOMAIN][entry_id]
        riga_tz = entry_data["riga_tz"]

        # Determine target date
        if date_str:
            try:
                target_date = date.fromisoformat(date_str)
            except ValueError:
                _LOGGER.exception(
                    "Invalid date format: %s (expected YYYY-MM-DD)", date_str
                )
                return
        else:
            target_date = datetime.now(riga_tz).date()

        # Validate date is within allowed range
        if not _validate_schedule_date(target_date, riga_tz):
            _LOGGER.error(
                "Date %s is outside allowed range (today or tomorrow only)",
                target_date,
            )
            return

        # Update schedule - store only the overrides with date-based keys
        for slot_index, enabled in slots.items():
            slot_int = int(slot_index)
            if 0 <= slot_int < SLOTS_PER_DAY:
                # Create date-based key and store the override
                schedule_key = _get_schedule_key(target_date, slot_int)
                entry_data["schedule"][schedule_key] = bool(enabled)

        # Clean up expired overrides
        _clean_expired_overrides(entry_data["schedule"], riga_tz)

        # Persist schedule to config entry
        await _async_save_schedule(hass, entry_id)

        _LOGGER.debug(
            "Updated schedule for entry %s on %s: %s",
            entry_id,
            target_date,
            slots,
        )

    async def handle_set_slot(call: ServiceCall) -> None:
        """Handle the set_slot service call."""
        entry_id = call.data[ATTR_ENTRY_ID]
        slot_index = call.data[ATTR_SLOT_INDEX]
        enabled = call.data[ATTR_ENABLED]
        date_str = call.data.get(ATTR_DATE)  # Optional, defaults to today

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Invalid entry_id: %s", entry_id)
            return

        if not 0 <= slot_index < SLOTS_PER_DAY:
            _LOGGER.error(
                "Invalid slot_index: %s (must be 0-%s)",
                slot_index,
                SLOTS_PER_DAY - 1,
            )
            return

        entry_data = hass.data[DOMAIN][entry_id]
        riga_tz = entry_data["riga_tz"]

        # Determine target date
        if date_str:
            try:
                target_date = date.fromisoformat(date_str)
            except ValueError:
                _LOGGER.exception(
                    "Invalid date format: %s (expected YYYY-MM-DD)", date_str
                )
                return
        else:
            target_date = datetime.now(riga_tz).date()

        # Validate date is within allowed range
        if not _validate_schedule_date(target_date, riga_tz):
            _LOGGER.error(
                "Date %s is outside allowed range (today or tomorrow only)",
                target_date,
            )
            return

        # Update the single slot with date-based key
        schedule_key = _get_schedule_key(target_date, slot_index)
        entry_data["schedule"][schedule_key] = bool(enabled)

        # Clean up expired overrides
        _clean_expired_overrides(entry_data["schedule"], riga_tz)

        # Persist schedule to config entry
        await _async_save_schedule(hass, entry_id)

        _LOGGER.debug(
            "Updated slot %s on %s to %s for entry %s",
            slot_index,
            target_date,
            enabled,
            entry_id,
        )

    async def handle_clear_schedule(call: ServiceCall) -> None:
        """Handle the clear_schedule service call."""
        entry_id = call.data[ATTR_ENTRY_ID]

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Invalid entry_id: %s", entry_id)
            return

        entry_data = hass.data[DOMAIN][entry_id]
        entry_data["schedule"] = {}  # Clear all overrides

        # Persist empty schedule to config entry
        await _async_save_schedule(hass, entry_id)

        _LOGGER.debug("Cleared schedule for entry %s", entry_id)

    async def handle_get_schedule(call: ServiceCall) -> ServiceResponse:
        """Handle the get_schedule service call."""
        entry_id = call.data[ATTR_ENTRY_ID]

        if entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Invalid entry_id: %s", entry_id)
            return {ATTR_SCHEDULE: {}}

        entry_data = hass.data[DOMAIN][entry_id]
        schedule = entry_data["schedule"]

        # Group schedule by date for better clarity
        schedule_by_date = {}
        for key, value in schedule.items():
            parsed = _parse_schedule_key(key)
            if parsed:
                target_date, slot_index = parsed
                date_str = target_date.isoformat()
                if date_str not in schedule_by_date:
                    schedule_by_date[date_str] = {}
                schedule_by_date[date_str][slot_index] = value

        return {ATTR_SCHEDULE: schedule_by_date}

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        handle_set_schedule,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTRY_ID): str,
                vol.Required(ATTR_SLOTS): {str: bool},
                vol.Optional(ATTR_DATE): str,
            },
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SLOT,
        handle_set_slot,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTRY_ID): str,
                vol.Required(ATTR_SLOT_INDEX): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=SLOTS_PER_DAY - 1),
                ),
                vol.Required(ATTR_ENABLED): bool,
                vol.Optional(ATTR_DATE): str,
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
        supports_response=SupportsResponse.ONLY,
    )

    _LOGGER.info("Registered services for %s", DOMAIN)
