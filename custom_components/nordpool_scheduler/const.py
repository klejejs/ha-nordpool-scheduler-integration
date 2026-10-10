"""Constants for the Nordpool Scheduler integration."""

from datetime import time
from typing import Final

DOMAIN: Final = "nordpool_scheduler"

# Config entry data / options keys
CONF_SCHEDULER_NAME: Final = "scheduler_name"
CONF_TARGET_ENTITY: Final = "target_entity"
CONF_DEFAULT_STATE: Final = "default_state"
CONF_NORDPOOL_ENTRY_ID: Final = "nordpool_config_entry_id"
CONF_AREA: Final = "area"
CONF_VAT_PERCENT: Final = "vat_percent"
CONF_CONTROL_MODE: Final = "control_mode"

# Supported target domains (all support turn_on/turn_off)
SUPPORTED_DOMAINS: Final = ["switch", "input_boolean", "light", "fan", "climate"]

STATE_DEFAULT_OFF: Final = "off"
STATE_DEFAULT_ON: Final = "on"

CONTROL_MODE_ON_CHANGE: Final = "on_change"
CONTROL_MODE_ENFORCE: Final = "enforce"
CONTROL_MODES: Final = [CONTROL_MODE_ON_CHANGE, CONTROL_MODE_ENFORCE]

SLOT_MINUTES: Final = 15
DEFAULT_VAT_PERCENT: Final = 21

PRICE_UNIT: Final = "c/kWh"

DEFAULT_RUN_HOURS: Final = 2.0
DEFAULT_WINDOW_START: Final = time(17, 0)
DEFAULT_WINDOW_END: Final = time(23, 0)
DEFAULT_MAX_RUNS: Final = 1

SLOT_SOURCE_OVERRIDE: Final = "override"
SLOT_SOURCE_AUTO: Final = "auto"
SLOT_SOURCE_DEFAULT: Final = "default"

# The upstream Nord Pool integration we depend on for prices
NORDPOOL_DOMAIN: Final = "nordpool"
NORDPOOL_SERVICE_GET_PRICES_FOR_DATE: Final = "get_prices_for_date"
NORDPOOL_TIMEZONE_NAME: Final = "Europe/Oslo"  # CET/CEST, used for publish scheduling

# Our services
SERVICE_SET_SLOTS: Final = "set_slots"
SERVICE_CLEAR_SCHEDULE: Final = "clear_schedule"

ATTR_CONFIG_ENTRY: Final = "config_entry"
ATTR_SLOTS: Final = "slots"
ATTR_START: Final = "start"
ATTR_STATE: Final = "state"

SLOT_STATE_ON: Final = "on"
SLOT_STATE_OFF: Final = "off"
SLOT_STATE_DEFAULT: Final = "default"
SLOT_STATES: Final = [SLOT_STATE_ON, SLOT_STATE_OFF, SLOT_STATE_DEFAULT]

STORAGE_VERSION: Final = 1
STORAGE_KEY_PREFIX: Final = f"{DOMAIN}.schedule"
STATS_STORAGE_KEY_PREFIX: Final = f"{DOMAIN}.stats"
DESIRED_STATE_STORAGE_KEY_PREFIX: Final = f"{DOMAIN}.desired_state"

# How far back/forward of "now" a requested slot may be
MAX_SLOT_LOOKAHEAD_DAYS: Final = 2
