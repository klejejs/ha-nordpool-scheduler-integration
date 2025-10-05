# Nordpool Scheduler Integration for Home Assistant

> **Note:** This project is entirely vibe coded and written by AI. 🤖✨

A custom Home Assistant integration that automatically schedules entity operations based on Nordpool electricity prices. This integration fetches real-time electricity prices and provides a scheduling system to control switches, lights, fans, climate devices, and template toggles during specific time slots.

## Features

- **Real-time Price Fetching**: Automatically fetches Nordpool electricity prices from CSV feed
- **Price Sensor**: Provides a sensor with current electricity price and all prices for today/tomorrow
- **Internal Scheduling**: Manages 96 internal time slots (15-minute intervals for 24 hours)
- **Multiple Entity Types**: Supports switches, input_boolean (template toggles), lights, fans, and climate devices
- **Multiple Instances**: Support for multiple schedulers with different target entities
- **Service Calls**: Programmatic control via Home Assistant services
- **Price Statistics**: Automatically calculates min, max, and average prices

## Installation

### HACS (Recommended)

1. Add this repository to HACS as a custom repository
2. Search for "Nordpool Scheduler" in HACS
3. Click "Install"
4. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/nordpool_scheduler` directory to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

The integration is configured through the Home Assistant UI:

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Nordpool Scheduler"
4. Enter:
   - **Scheduler Name**: A friendly name for this scheduler instance
   - **Target Entity**: The entity to control (supports: switch, input_boolean, light, fan, climate)
   - **Default State**: Choose the default behavior:
     - **Default OFF**: Entity is OFF by default, turns ON only when scheduled
     - **Default ON**: Entity is ON by default, turns OFF only when scheduled

You can add multiple instances of the integration to control different entities.

## Usage

### Sensor

After setup, a sensor entity will be created:
- **Entity ID**: `sensor.<scheduler_name>_electricity_price`
- **State**: Current electricity price (EUR/kWh)
- **Attributes**:
  - `prices`: Array of 192 price values (today + tomorrow, 15-minute intervals)
  - `current_slot`: Current time slot index (0-95)
  - `min_price`: Minimum price in the dataset
  - `max_price`: Maximum price in the dataset
  - `avg_price`: Average price in the dataset
  - `entry_id`: Config entry ID for service calls
  - `scheduler_name`: Name of the scheduler
  - `default_state`: Configured default state (`on` or `off`)
  - `target_entity_state`: Current state of the target entity (e.g., `on`, `off`, `unavailable`)
  - `scheduled_overrides`: List of explicitly scheduled time slots with their states
  - `scheduled_overrides_count`: Number of scheduled override slots

### Services

The integration provides three services for programmatic control:

#### `nordpool_scheduler.set_schedule`

Set the schedule for specific time slots. These schedules **override** the default state.

**Service Data:**
```yaml
entry_id: "your_entry_id"  # Found in sensor attributes
slots:
  "0": true    # Slot 0 (00:00) - explicitly turn ON
  "4": true    # Slot 4 (01:00) - explicitly turn ON
  "8": false   # Slot 8 (02:00) - explicitly turn OFF
  "32": true   # Slot 32 (08:00) - explicitly turn ON
  # Unscheduled slots will use the configured default state
```

**Example:**
```yaml
service: nordpool_scheduler.set_schedule
data:
  entry_id: "abc123def456"
  slots:
    "0": true
    "20": true
    "40": false
```

#### `nordpool_scheduler.clear_schedule`

Clear all scheduled time slots. After clearing, all slots will use the configured default state.

**Service Data:**
```yaml
entry_id: "your_entry_id"
```

**Example:**
```yaml
service: nordpool_scheduler.clear_schedule
data:
  entry_id: "abc123def456"
```

#### `nordpool_scheduler.get_schedule`

Get the current schedule (returns schedule state).

**Service Data:**
```yaml
entry_id: "your_entry_id"
```

### Time Slots

The day is divided into 96 time slots (15-minute intervals):
- Slot 0 = 00:00
- Slot 1 = 00:15
- Slot 2 = 00:30
- Slot 3 = 00:45
- Slot 4 = 01:00
- ...
- Slot 95 = 23:45

To calculate a slot index: `slot_index = hour * 4 + (minute // 15)`

### Automation Behavior

The integration operates based on the **default state** you configured:

#### Default OFF Mode (Traditional Behavior)
- Unscheduled slots: Entity is OFF
- Schedule slot as `true`: Entity turns ON
- Schedule slot as `false`: Entity turns OFF

#### Default ON Mode (Inverted Behavior)
- Unscheduled slots: Entity is ON
- Schedule slot as `true`: Entity turns ON
- Schedule slot as `false`: Entity turns OFF

**Key Features:**
- At each 15-minute mark, the integration checks if a schedule override exists for that slot
- If scheduled, it uses the scheduled state
- If not scheduled, it uses the configured default state
- After triggering, the previous slot's schedule is automatically cleared to allow re-scheduling
- Works with all supported entity types: switches, input_boolean, lights, fans, and climate devices

## Example Automations

### Turn on during cheapest hours

```yaml
automation:
  - alias: "Schedule heating during cheap hours"
    trigger:
      - platform: time
        at: "14:00:00"  # When tomorrow's prices are available
    action:
      - service: nordpool_scheduler.clear_schedule
        data:
          entry_id: !secret scheduler_entry_id
      - service: nordpool_scheduler.set_schedule
        data:
          entry_id: !secret scheduler_entry_id
          slots: >
            {% set prices = state_attr('sensor.heater_scheduler_electricity_price', 'prices') %}
            {% set sorted_indices = range(96) | list |
               sort(attribute=prices.__getitem__) %}
            {% set cheapest_slots = sorted_indices[:8] %}  # 8 cheapest slots = 2 hours
            {{ dict.fromkeys(cheapest_slots | map('string'), true) }}
```

### Manual override in Lovelace

Create buttons to toggle specific time slots using the service calls above.

## Future Frontend Component

This integration is designed to work with a future custom frontend component that will provide:
- Visual time slot selection interface
- Price visualization graph
- Easy schedule management
- Quick preset selection

The backend (this integration) is fully functional and ready for frontend integration.

## Data Source

Electricity prices are fetched from: `https://nordpool.didnt.work/nordpool-lv-excel.csv`

**Important Notes:**
- CSV prices are in EUR/kWh **without VAT**
- The integration automatically adds 21% VAT to all prices
- **CSV timestamps are in Europe/Riga (Latvia) timezone** and are automatically converted to UTC
- This ensures correct price matching regardless of your Home Assistant timezone settings

### Acknowledgments

Special thanks to the creator and maintainer of **[nordpool.didnt.work](https://nordpool.didnt.work)** for providing the free Nordpool electricity price data API that makes this integration possible! 🙏

## Development

### Running Tests

```bash
# Install test dependencies
pip install -r requirements_test.txt

# Run tests
pytest

# Run tests with coverage
pytest --cov=custom_components.nordpool_scheduler --cov-report=html
```

### Project Structure

```
custom_components/nordpool_scheduler/
├── __init__.py          # Integration setup and scheduling logic
├── config_flow.py       # Configuration flow
├── const.py             # Constants
├── coordinator.py       # Data fetching coordinator
├── sensor.py            # Price sensor
├── manifest.json        # Integration metadata
├── services.yaml        # Service definitions
└── translations/
    └── en.json          # English translations
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License.

## Support

For issues, questions, or feature requests, please use the GitHub issue tracker.
