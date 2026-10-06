# Nordpool Scheduler

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub Release](https://img.shields.io/github/v/release/klejejs/ha-nordpool-scheduler-integration)](https://github.com/klejejs/ha-nordpool-scheduler-integration/releases)
[![Validate](https://github.com/klejejs/ha-nordpool-scheduler-integration/actions/workflows/validate.yml/badge.svg)](https://github.com/klejejs/ha-nordpool-scheduler-integration/actions/workflows/validate.yml)
[![Lint](https://github.com/klejejs/ha-nordpool-scheduler-integration/actions/workflows/lint.yml/badge.svg)](https://github.com/klejejs/ha-nordpool-scheduler-integration/actions/workflows/lint.yml)
[![License](https://img.shields.io/github/license/klejejs/ha-nordpool-scheduler-integration)](LICENSE)

A Home Assistant integration that turns an entity on or off in 15-minute slots, priced by Nord Pool. Each scheduler has a default state (on or off) and a list of slot overrides. At every quarter hour it applies whichever one covers the current slot.

Prices come from Home Assistant's built-in [Nord Pool integration](https://www.home-assistant.io/integrations/nordpool/), so there's no extra account or API key.

Pair it with the [Nordpool Scheduler Card](https://github.com/klejejs/ha-nordpool-scheduler-card) to see the prices and click slots on and off from a dashboard.

## Requirements

- Home Assistant 2025.10.1 or newer
- The [Nord Pool integration](https://www.home-assistant.io/integrations/nordpool/), set up with the area you buy electricity in

## Installation

### HACS

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=klejejs&repository=ha-nordpool-scheduler-integration&category=integration)

Or by hand:

1. HACS → the three-dot menu → **Custom repositories**
2. Add `https://github.com/klejejs/ha-nordpool-scheduler-integration` with the category **Integration**
3. Install **Nordpool Scheduler** and restart Home Assistant

### Manual

1. Download `nordpool_scheduler.zip` from the [latest release](https://github.com/klejejs/ha-nordpool-scheduler-integration/releases/latest)
2. Unzip it into `custom_components/nordpool_scheduler` in your Home Assistant configuration directory
3. Restart Home Assistant

## Configuration

Go to **Settings** → **Devices & services** → **Add integration** → **Nordpool Scheduler**, then fill in:

| Field | Description |
|---|---|
| Scheduler name | A name for this scheduler, used in its entity IDs |
| Target entity | The entity to control: a `switch`, `input_boolean`, `light`, `fan` or `climate` |
| Default state | What the entity does in a slot with no override: **Default OFF** or **Default ON** |
| Nord Pool source | The Nord Pool integration entry to take prices from |
| Area | Asked only when the Nord Pool entry covers more than one area |

Add one scheduler per entity. An entity can only have one scheduler.

**Configure** on an existing scheduler changes:

| Option | Default | Description |
|---|---|---|
| Target entity | | The entity to control |
| Default state | Default OFF | The state for slots with no override |
| Manual toggles | Only act when the schedule changes | **Only act when the schedule changes** leaves an entity you toggled by hand alone until the schedule wants something different. **Enforce every 15 minutes** re-applies the schedule at every slot. |
| VAT percentage | 21 | Added on top of the Nord Pool price |

## Entities

Each scheduler creates one device with three entities. For a scheduler named "Boiler":

| Entity | Description |
|---|---|
| `sensor.nordpool_scheduler_boiler_electricity_price` | The current slot's price in your Nord Pool currency per kWh, VAT included. Attributes: `area`, `vat_percent`. |
| `binary_sensor.nordpool_scheduler_boiler_scheduled_on` | On when the schedule wants the target on for the current slot. Attributes: `target_entity`, `target_state`. |
| `switch.nordpool_scheduler_boiler_scheduler_enabled` | Turn it off to pause the scheduler. The target is left as it is until you turn the switch back on. |

## How it works

- The day is split into 15-minute slots. A slot is either overridden **on**, overridden **off**, or follows the **default** state.
- At 00, 15, 30 and 45 past each hour the scheduler works out what the current slot wants and turns the target on or off.
- With **Only act when the schedule changes**, it only calls `turn_on` or `turn_off` when the wanted state differs from the previous slot's.
- After a restart or reload it brings the target back in line with the current slot, switching it only if its state differs. A manual change that goes against the current slot is undone at that point.
- A target that is `unavailable` or `unknown` is skipped for that slot.
- Overrides are stored on disk and survive restarts. Overrides for slots that have ended are removed.
- Prices are refreshed every hour, and again just after 13:00 CET when Nord Pool usually publishes the next day. Areas still on hourly prices have each hour's price copied to its four slots.

## Actions

### `nordpool_scheduler.set_slots`

Sets one or more slots to `on`, `off` or `default`. `default` removes the override. Each `start` must fall on a 15-minute boundary and lie between the current slot and two days ahead.

```yaml
action: nordpool_scheduler.set_slots
data:
  config_entry: 01JABCDEF0123456789ABCDEFG
  slots:
    - start: "2026-10-07T02:00:00+03:00"
      state: "on"
    - start: "2026-10-07T02:15:00+03:00"
      state: "on"
    - start: "2026-10-07T18:00:00+03:00"
      state: "default"
```

### `nordpool_scheduler.clear_schedule`

Removes every override, so every slot follows the default state.

```yaml
action: nordpool_scheduler.clear_schedule
data:
  config_entry: 01JABCDEF0123456789ABCDEFG
```

`config_entry` is the scheduler's config entry ID. Pick the scheduler from the dropdown in the action editor and switch to YAML to see it.

## Example: run in tomorrow's cheapest two hours

This uses the Nord Pool integration's own `get_prices_for_date` action to read tomorrow's prices, then switches on the eight cheapest slots. Replace the two config entry IDs and the area with your own.

It assumes the scheduler is set to **Default OFF** and has no other overrides for tomorrow: `set_slots` only changes the slots it is given and leaves every other slot as it is. It also relies on Nord Pool's 15-minute day-ahead prices, so that each price entry is one slot.

```yaml
automation:
  - alias: "Boiler: schedule the cheapest slots tomorrow"
    triggers:
      - trigger: time
        at: "14:00:00"
    actions:
      - action: nordpool.get_prices_for_date
        data:
          config_entry: YOUR_NORDPOOL_ENTRY_ID
          date: "{{ (now() + timedelta(days=1)).date() }}"
          areas: LV
        response_variable: prices
      - action: nordpool_scheduler.set_slots
        data:
          config_entry: YOUR_SCHEDULER_ENTRY_ID
          slots: >
            {% set ns = namespace(slots=[]) %}
            {% for p in (prices.LV | sort(attribute='price'))[:8] %}
              {% set ns.slots = ns.slots + [{"start": p.start, "state": "on"}] %}
            {% endfor %}
            {{ ns.slots }}
```

## Upgrading from 1.x

Version 1 read prices from a CSV feed rather than the Nord Pool integration, and its schedulers can't be migrated automatically. After upgrading, set up the Nord Pool integration, then remove each old scheduler and add it again.

## Development

The repository includes a dev container with Python 3.13.

```bash
scripts/setup     # install requirements
scripts/develop   # run Home Assistant on :8123 with ./config and this integration loaded
scripts/lint      # ruff format and ruff check --fix
scripts/test      # install test requirements, lint and run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to submit changes.

## Releasing

Push a tag such as `v2.1.0`. The release workflow writes that version into `manifest.json`, zips the integration and publishes a GitHub release with `nordpool_scheduler.zip` attached, which is what HACS installs. The `0.0.0` in the committed `manifest.json` is a placeholder and never needs editing.

## License

MIT, see [LICENSE](LICENSE). Started from ludeeus's [integration_blueprint](https://github.com/ludeeus/integration_blueprint).
