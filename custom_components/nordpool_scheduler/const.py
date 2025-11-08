"""Constants for the Nordpool Scheduler integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "nordpool_scheduler"
NAME: Final = "Nordpool Scheduler"

# Configuration
CONF_SCHEDULER_NAME: Final = "scheduler_name"
CONF_TARGET_SWITCH: Final = "target_switch"
CONF_DEFAULT_STATE: Final = "default_state"
CONF_SCHEDULE: Final = "schedule"  # Persisted schedule overrides

# Supported entity domains (all support turn_on/turn_off)
SUPPORTED_DOMAINS: Final = ["switch", "input_boolean", "light", "fan", "climate"]

# Default state options
DEFAULT_STATE_ON: Final = "on"
DEFAULT_STATE_OFF: Final = "off"

# Data coordinator
UPDATE_INTERVAL: Final = timedelta(minutes=5)  # Check every 5 minutes for price updates

# Nordpool API
NORDPOOL_CSV_URL: Final = "https://nordpool.didnt.work/nordpool-lv-excel.csv"
VAT_MULTIPLIER: Final = 1.21  # 21% VAT

# Time slots (96 slots for 24 hours * 4 quarters)
SLOTS_PER_DAY: Final = 96
MINUTES_PER_SLOT: Final = 15
MAX_SCHEDULE_DAYS_AHEAD: Final = 1  # Allow scheduling today (0) and tomorrow (1)

# Services
SERVICE_SET_SCHEDULE: Final = "set_schedule"
SERVICE_SET_SLOT: Final = "set_slot"
SERVICE_CLEAR_SCHEDULE: Final = "clear_schedule"
SERVICE_GET_SCHEDULE: Final = "get_schedule"

# Attributes
ATTR_SCHEDULE: Final = "schedule"
ATTR_ENTRY_ID: Final = "entry_id"
ATTR_SLOTS: Final = "slots"
ATTR_SLOT_INDEX: Final = "slot_index"
ATTR_ENABLED: Final = "enabled"
ATTR_DATE: Final = "date"  # Format: YYYY-MM-DD
ATTR_PRICES: Final = "prices"
ATTR_CURRENT_PRICE: Final = "current_price"
