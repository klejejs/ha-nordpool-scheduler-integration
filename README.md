# Nordpool Scheduler

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub Release](https://img.shields.io/github/v/release/klejejs/ha-nordpool-scheduler-integration)](https://github.com/klejejs/ha-nordpool-scheduler-integration/releases)
[![Validate](https://github.com/klejejs/ha-nordpool-scheduler-integration/actions/workflows/validate.yml/badge.svg)](https://github.com/klejejs/ha-nordpool-scheduler-integration/actions/workflows/validate.yml)
[![Lint](https://github.com/klejejs/ha-nordpool-scheduler-integration/actions/workflows/lint.yml/badge.svg)](https://github.com/klejejs/ha-nordpool-scheduler-integration/actions/workflows/lint.yml)
[![License](https://img.shields.io/github/license/klejejs/ha-nordpool-scheduler-integration)](LICENSE)

A Home Assistant integration that turns an entity on or off in 15-minute slots, priced by Nord Pool. Each scheduler has a default state (on or off), an optional auto mode that runs the entity in the cheapest slots of each day, and a list of slot overrides. At every quarter hour it applies whichever one covers the current slot.

Prices come from Home Assistant's built-in [Nord Pool integration](https://www.home-assistant.io/integrations/nordpool/), so there's no extra account or API key.

Pair it with the [Nordpool Scheduler Card](https://github.com/klejejs/ha-nordpool-scheduler-card) to see the prices and click slots on and off from a dashboard.

## Requirements

- Home Assistant 2026.6.0 or newer
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

Go to **Settings** → **Devices & services** → **Add integration** → **Nordpool Scheduler**, then choose what to add:

- **Scheduler** turns an entity on and off by price.
- **Prices only** just supplies prices, for showing them on a dashboard with the [card](https://github.com/klejejs/ha-nordpool-scheduler-card). It only asks for the Nord Pool source and area, and creates only price sensors: the current price, e.g. `sensor.nordpool_scheduler_prices_lv_electricity_price`, and the four [average price](#average-price) sensors. Each area can have one prices entry. **Configure** on it only changes the VAT percentage.

A scheduler asks for:

| Field | Description |
|---|---|
| Scheduler name | A name for this scheduler, used in its entity IDs |
| Target entity | The entity to control: a `switch`, `input_boolean`, `light`, `fan` or `climate` |
| Default state | What the entity does in a slot with no override while auto mode is off: **Default OFF** or **Default ON** |
| Nord Pool source | The Nord Pool integration entry to take prices from |
| Area | Asked only when the Nord Pool entry covers more than one area |

Add one scheduler per entity. An entity can only have one scheduler.

**Configure** on an existing scheduler changes:

| Option | Default | Description |
|---|---|---|
| Target entity | | The entity to control |
| Default state | Default OFF | The state for slots with no override while auto mode is off |
| Manual toggles | Only act when the schedule changes | **Only act when the schedule changes** leaves an entity you toggled by hand alone until the schedule wants something different or you change the current slot. **Enforce every 15 minutes** re-applies the schedule at every slot. |
| VAT percentage | 21 | Added on top of the Nord Pool price |

## Entities

Each scheduler creates one device with sixteen entities. For a scheduler named "Boiler":

| Entity | Description |
|---|---|
| `sensor.nordpool_scheduler_boiler_electricity_price` | The current slot's price in cents (1/100 of your Nord Pool currency) per kWh, VAT included. Attributes: `area`, `vat_percent`. |
| `sensor.nordpool_scheduler_boiler_average_price_today` | The average price while the target was on, in c/kWh. Also `_this_week`, `_this_month` and `_this_year`. See [Average price](#average-price). |
| `binary_sensor.nordpool_scheduler_boiler_scheduled_on` | On when the schedule wants the target on for the current slot. Attributes: `target_entity`, `target_state`, and `source` (`override`, `auto` or `default`). |
| `sensor.nordpool_scheduler_boiler_schedule` | Disabled by default. Publishes what the card shows as its `schedule` attribute, for a [second instance](#another-home-assistant-instance) that mirrors this one. The state is the start of the current slot. |
| `switch.nordpool_scheduler_boiler_scheduler_enabled` | Turn it off to pause the scheduler. The target is left as it is until you turn the switch back on. |
| `switch.nordpool_scheduler_boiler_auto_mode` | Auto mode, off by default. See [Auto mode](#auto-mode). |
| `number.nordpool_scheduler_boiler_auto_hours_per_day` | Hours a day auto mode runs the target, in 15-minute steps. Default 2. |
| `number.nordpool_scheduler_boiler_auto_max_price` | Auto mode skips a picked slot above this price, in c/kWh. 0 turns the limit off. |
| `number.nordpool_scheduler_boiler_auto_cheap_price` | Auto mode also runs every slot at or below this price, in c/kWh. 0 turns it off. |
| `switch.nordpool_scheduler_boiler_auto_hour_range` | Off by default. Turn it on to have auto mode only run the target between the start and end times. |
| `time.nordpool_scheduler_boiler_auto_start_time` | Where the hour range starts. Default 17:00. |
| `time.nordpool_scheduler_boiler_auto_end_time` | Where the hour range ends. Default 23:00. |
| `switch.nordpool_scheduler_boiler_auto_cheap_price_all_day` | Off by default. Turn it on to also run slots at or below **Auto cheap price** outside the hour range. |
| `switch.nordpool_scheduler_boiler_auto_run_limit` | Off by default. Turn it on to cap how many separate runs auto mode makes each day, for a target like a boiler that shouldn't start often. |
| `number.nordpool_scheduler_boiler_auto_max_runs_per_day` | How many runs a day **Auto run limit** allows. Default 1. |

The auto mode switches, numbers and times keep their values across restarts.

A prices-only entry's schedule sensor works the same way.

## Auto mode

With auto mode on, the scheduler picks which slots run instead of using the default state:

- Each local day, midnight to midnight in Home Assistant's time zone, runs in its cheapest slots, adding up to **Auto hours per day**. A tie goes to the earlier slot.
- A picked slot priced above **Auto max price** doesn't run, so on an expensive day the target can run for less than its hours.
- Every slot at or below **Auto cheap price** runs, even past the hours.
- With **Auto hour range** on, the hours are only picked between **Auto start time** and **Auto end time**, and every slot outside them is off. Cheap slots outside the range stay off too, unless **Auto cheap price all day** is on. An end time before the start time wraps past midnight, but each day is still picked on its own: 22:00 to 06:00 covers that day's 00:00 to 06:00 and 22:00 to midnight. Equal start and end times cover the whole day.
- With **Auto run limit** on, the hours run in at most **Auto max runs per day** stretches of back-to-back slots, the cheapest such stretches of the day: at 1, two hours run as one unbroken two-hour run. A run never spans a slot above **Auto max price**, so the target can run for less than its hours. A slot at or below **Auto cheap price** only runs when it lengthens one of these runs, never as a run of its own. Each day counts its runs on its own, so a range that wraps past midnight is two stretches of the same day.
- A day is only decided once every one of its slots has a price. Until then, for example tomorrow before Nord Pool publishes, its slots follow the default state, except those outside an **Auto hour range**, which are off.
- An override always wins over auto mode's pick.

Turning auto mode on or off, or changing one of its settings, takes effect for the current slot at once.

## Average price

The average price sensors report what the target's running time has cost per kWh so far today, this week, this month and this year. Each slot's price counts for as long as the target was on during it. The periods follow Home Assistant's time zone, and weeks start on Monday.

- The target counts as on in any state other than `off`, `unavailable` or `unknown`, whether the scheduler or someone else turned it on.
- A sensor is unknown until the target has run in its period. Its `running_hours` attribute is how long the target ran in slots with a known price, and `period_start` is the period's first day.
- A prices-only entry has no target, so its sensors are the plain average of every slot's price so far in the period.
- Counting starts when the integration is installed or updated to this version. Time while Home Assistant is stopped isn't counted.
- The totals behind the averages are kept on disk for 400 days.

## How it works

- The day is split into 15-minute slots. A slot is either overridden **on**, overridden **off**, or follows auto mode's pick when auto mode is on and the default state otherwise.
- At 00, 15, 30 and 45 past each hour the scheduler works out what the current slot wants and turns the target on or off. Changing an override, auto mode or one of its settings re-checks the current slot straight away. Changing the current slot's override also switches the target to match it, even if you toggled the target by hand.
- With **Only act when the schedule changes**, it only calls `turn_on` or `turn_off` when the wanted state differs from the previous slot's.
- After a restart or reload, **Only act when the schedule changes** picks up where it left off: the wanted state is saved on disk, and the target is only switched if the current slot wants something different from what it wanted before. A manual toggle survives the restart. On a first install, and in **Enforce every 15 minutes**, it brings the target back in line with the current slot, switching it only if its state differs.
- A target that is `unavailable` or `unknown` is skipped for that slot.
- Overrides are stored on disk and survive restarts. Overrides for slots that have ended are removed.
- Prices are refreshed every hour, and again just after 13:00 CET when Nord Pool usually publishes the next day. Areas still on hourly prices have each hour's price copied to its four slots.

## Actions

### `nordpool_scheduler.set_slots`

Sets one or more slots to `on`, `off` or `default`. `default` removes the override, so the slot follows auto mode or the default state again. Each `start` must fall on a 15-minute boundary and lie between the current slot and two days ahead.

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

Removes every override, so every slot follows auto mode or the default state.

```yaml
action: nordpool_scheduler.clear_schedule
data:
  config_entry: 01JABCDEF0123456789ABCDEFG
```

`config_entry` is the scheduler's config entry ID. Pick the scheduler from the dropdown in the action editor and switch to YAML to see it.

## Another Home Assistant instance

The card normally asks this integration for its data directly, so it only works on the instance the integration runs on. To show a scheduler on a second instance that mirrors this one with [Remote Home-Assistant](https://github.com/custom-components/remote_homeassistant), have it publish that data as an entity:

1. On the instance that runs the scheduler, enable its **Schedule** sensor, e.g. `sensor.nordpool_scheduler_boiler_schedule`. It's a diagnostic entity, disabled by default.
2. On the mirroring instance, make sure Remote Home-Assistant mirrors the scheduler's entities, and proxies `nordpool_scheduler.set_slots` with a service prefix. With `entity_prefix: darzs_`, use `service_prefix: darzs_` as well, so the card finds `nordpool_scheduler.darzs_set_slots` without being told.
3. Point the card at the mirrored schedule sensor, e.g. `sensor.darzs_nordpool_scheduler_boiler_schedule`. See the card's README for the rest.

The attribute stays under 4 KB and this instance's recorder leaves it out. The mirroring instance doesn't know that, so exclude the mirrored sensor from its recorder:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.darzs_nordpool_scheduler_*_schedule
```

## Development

The repository includes a dev container with Python 3.14.

```bash
scripts/setup     # install requirements
scripts/develop   # run Home Assistant on :8123 with ./config and this integration loaded
scripts/lint      # ruff format and ruff check --fix
scripts/test      # install test requirements, lint and run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to submit changes.

## Releasing

Releases are made only through GitHub Releases. Pushing a tag on its own builds nothing.

Release Drafter keeps a draft release up to date on every merge to `main`. Its tag is the next minor version, or the next major one if a merged PR carries the `major` label. Its notes are grouped by PR label: `dependencies` (Renovate branches), `bug` (titles starting with "Fix") and `feature` (everything else). The labels are applied automatically when a PR opens, so relabel a PR before merging if it guessed wrong.

To release, publish that draft from the GitHub UI. If it should be a different version, change the tag, the release title and the "Full Changelog" link at the bottom of the notes together. The draft only fills them in once, so editing the tag alone leaves the other two pointing at the old version. The first release has no earlier one to count from, so set its version by hand.

Publishing runs the release workflow, which writes the release's tag into `manifest.json`, zips the integration and attaches `nordpool_scheduler.zip` to the release. That zip is what HACS installs. The `0.0.0` in the committed `manifest.json` is a placeholder and never needs editing.

## License

MIT, see [LICENSE](LICENSE). Started from ludeeus's [integration_blueprint](https://github.com/ludeeus/integration_blueprint).
