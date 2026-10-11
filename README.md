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
| Stop sensor | | Optional. A `binary_sensor`, `input_boolean` or `switch` that keeps the target off while it is on. See [Stop sensor](#stop-sensor). |
| VAT percentage | 21 | Added on top of the Nord Pool price |

## Entities

Each scheduler creates one device with eleven entities. For a scheduler named "Boiler":

| Entity | Description |
|---|---|
| `sensor.nordpool_scheduler_boiler_electricity_price` | The current slot's price in cents (1/100 of your Nord Pool currency) per kWh, VAT included. Attributes: `area`, `vat_percent`. |
| `sensor.nordpool_scheduler_boiler_average_price_today` | The average price while the target was on, in c/kWh. Also `_this_week`, `_this_month` and `_this_year`. See [Average price](#average-price). |
| `binary_sensor.nordpool_scheduler_boiler_scheduled_on` | On when the schedule wants the target on for the current slot. Attributes: `target_entity`, `target_state`, and `source` (`override`, `auto`, `default`, or `stopped` while the [stop sensor](#stop-sensor) is on). |
| `sensor.nordpool_scheduler_boiler_schedule` | Disabled by default. Publishes what the card shows as its `schedule` attribute, for a [second instance](#another-home-assistant-instance) that mirrors this one. The state is the start of the current slot. |
| `switch.nordpool_scheduler_boiler_scheduler_enabled` | Turn it off to pause the scheduler. The target is left as it is until you turn the switch back on. |
| `switch.nordpool_scheduler_boiler_auto_mode` | Auto mode, off by default. See [Auto mode](#auto-mode). |
| `switch.nordpool_scheduler_boiler_auto_run_limit` | Off by default. Turn it on to make each [time window](#time-windows)'s hours run back to back, and to cap how many separate runs auto mode makes each day, for a target like a boiler or floor heating that shouldn't start often. |
| `number.nordpool_scheduler_boiler_auto_max_runs_per_day` | How many runs a day **Auto run limit** allows. Default 1. |

The auto mode switches and number keep their values across restarts. The [time windows](#time-windows) aren't entities: set them from the card or with [`set_auto_windows`](#nordpool_schedulerset_auto_windows).

A prices-only entry's schedule sensor works the same way.

## Auto mode

With auto mode on, the scheduler picks which slots run instead of using the default state. It runs the target in a list of **time windows**, each for its own time in the cheapest slots inside it.

What stays global and what each window sets:

| Global | Per time window |
|---|---|
| **Auto mode**, on or off | **From** and **To**, the time of day it covers |
| **Auto run limit**, on or off | **Run for**, the hours it runs in its cheapest slots |
| **Auto max runs per day** | **Max price**: the slots it picks for its hours are never above this. 0 turns it off. |
| | **Cheap price**: its slots at or below this run too. 0 turns it off. |

A new scheduler starts with one window, 00:00 to 23:59 for 2 hours, with no price limits: the target runs in the two cheapest hours of each day.

### Time windows

- **From and To.** A To before From wraps past midnight, so 20:00 to 00:00 is 20:00 to midnight. From equal to To, or 00:00 to 23:59, is the whole day. Each local day, midnight to midnight in Home Assistant's time zone, is picked on its own, so a window that wraps past midnight is two stretches of the same day.
- **Run for.** Each window runs its hours in its cheapest slots, a tie going to the earlier slot. The day runs for the windows' hours added together.
- **Narrowest first.** Windows are picked from the shortest From to To up, so a morning window takes its slots before a whole-day window fills in around it.
- **Max price.** A window never picks a slot above its max price for its hours, so on an expensive day it can run for less than its hours, or not at all. With **Auto run limit** off, a cheap price set above the max price still runs its cheap slots; with the run limit on, cheap slots stay at or below the max price too.
- **Cheap price.** Every slot in a window at or below its cheap price runs too, even past the hours. A window that runs for 0 hours picks nothing, but its cheap price still applies, so a whole-day window with 0 hours and a cheap price runs every cheap slot of the day.
- **Outside every window** the target is off.
- Windows can overlap. Each picks on its own, and a slot runs if any window picks it.
- A day is only decided once every one of its slots has a price. Until then, for example tomorrow before Nord Pool publishes, slots inside a window that runs for some time follow the default state, and every other slot is off.
- An override always wins over auto mode's pick.

### Run limit

With **Auto run limit** on, each window's hours run in back-to-back stretches, and the whole day makes at most **Auto max runs per day** of them.

- Every window that runs for some time gets at least one run. The narrower windows go first, and a window can use more runs only when the limit leaves enough for the windows after it.
- If more windows run for some time than the limit allows, each still gets its one run, so the day makes more runs than the limit.
- A window's slots that join onto a run made earlier lengthen it without counting as another run.
- A run never spans a slot above that window's max price.
- A slot at or below a cheap price only runs when it lengthens a run, never as a run of its own.

Turning auto mode on or off, changing the run limit or changing the windows takes effect for the current slot at once.

### Examples

**Bathroom floor: morning, evening and once more.** Auto run limit on, at most 3 runs, and three windows:

| From | To | Run for | Max price | Cheap price |
|---|---|---|---|---|
| 06:00 | 08:00 | 45 min | 25 | 0 |
| 19:00 | 22:00 | 1 h | 15 | 3 |
| 00:00 | 23:59 | 15 min | 15 | 0 |

1. 06:00 to 08:00 is the narrowest, so it goes first: the cheapest 45 unbroken minutes between 06:00 and 08:00 that don't cost more than 25 c/kWh.
2. 19:00 to 22:00 goes next: its cheapest unbroken hour at no more than 15 c/kWh. Any slot next to that hour at 3 c/kWh or less runs too.
3. The whole-day window gets the third run: its cheapest 15 minutes at no more than 15 c/kWh, anywhere in the day. If that slot sits next to the morning or evening run, it lengthens that run instead.
4. On a day where nothing outside the morning costs 15 c/kWh or less, the evening and whole-day windows don't run, and only the morning run happens.

**One evening run, and up to two more at any time.** Auto run limit on, at most 3 runs:

| From | To | Run for |
|---|---|---|
| 20:00 | 00:00 | 1 h |
| 00:00 | 23:59 | 1.5 h |

1. The evening window is the narrower one, so its cheapest hour between 20:00 and midnight is picked first, as one run.
2. The whole-day window can then make up to two more runs, so the 1.5 hours go to the cheapest slots in at most two stretches: two runs, one longer run, or added onto the evening run.
3. Two more runs is a maximum, not a promise. To always run twice more, use two windows instead, such as 00:00 to 12:00 and 12:00 to 20:00. To keep the extra runs out of the evening, end the wide window at 20:00.

**A range with cheap slots all day.** One window 17:00 to 23:00 for 2 hours, and a second window 00:00 to 23:59 for 0 hours with a cheap price of 3. The target runs the two cheapest hours between 17:00 and 23:00, and any slot of the day at 3 c/kWh or less.

### Coming from an older version

Auto mode used to have a single **Auto hours per day**, **Auto max price** and **Auto cheap price** for the whole day, and an **Auto hour range** with **Auto cheap price all day**. Updating turns them into time windows that pick exactly the same slots, and removes those seven entities:

- Without an hour range, they become one window 00:00 to 23:59 with the same hours and prices.
- With an hour range, they become one window over the range. With cheap price all day on as well, a second window 00:00 to 23:59 for 0 hours, with the same prices, keeps the cheap slots outside the range running.

Automations that set the removed entities should call [`set_auto_windows`](#nordpool_schedulerset_auto_windows) instead.

## Stop sensor

Electric floor heating can run all day on cheap prices, but once the bathroom is warm enough there is no point heating it. The scheduler doesn't read temperatures itself. Instead, under **Configure**, pick a **Stop sensor**: any `binary_sensor`, `input_boolean` or `switch`. While it is on, the target is kept off. A [Threshold](https://www.home-assistant.io/integrations/threshold/) helper on the bathroom's temperature, on above 26 °C, does the job.

- It wins over everything: auto mode's picks, the default state and your overrides.
- The target turns off as soon as the stop sensor turns on, and the current slot is applied again as soon as it turns off, without waiting for the next quarter hour.
- A stop sensor that is `unavailable`, `unknown` or missing is ignored, so the schedule carries on.
- While **Scheduler enabled** is off the stop sensor does nothing either, and the card doesn't show it as stopped.
- The schedule itself doesn't change: the card's grid keeps showing what would run, and auto mode doesn't pick extra slots to make up time lost to a stop.
- With **Only act when the schedule changes**, the target is brought in line once when the stop starts, once when it ends, and at a restart while it is on, so a target turned on by hand is turned off too. A manual toggle in between is left alone. With **Enforce every 15 minutes**, the target is turned off again at every slot while the stop sensor is on.

## Average price

The average price sensors report what the target's running time has cost per kWh so far today, this week, this month and this year. Each slot's price counts for as long as the target was on during it. The periods follow Home Assistant's time zone, and weeks start on Monday.

- The target counts as on in any state other than `off`, `unavailable` or `unknown`, whether the scheduler or someone else turned it on.
- A sensor is unknown until the target has run in its period. Its `running_hours` attribute is how long the target ran in slots with a known price, and `period_start` is the period's first day.
- A prices-only entry has no target, so its sensors are the plain average of every slot's price so far in the period.
- Counting starts when the integration is installed or updated to this version. Time while Home Assistant is stopped isn't counted.
- The totals behind the averages are kept on disk for 400 days.

## How it works

- The day is split into 15-minute slots. A slot is either overridden **on**, overridden **off**, or follows auto mode's pick when auto mode is on and the default state otherwise.
- At 00, 15, 30 and 45 past each hour the scheduler works out what the current slot wants and turns the target on or off. While the [stop sensor](#stop-sensor) is on it wants off, whatever the slot says. Changing an override, auto mode or one of its settings re-checks the current slot straight away. Changing the current slot's override also switches the target to match it, even if you toggled the target by hand.
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

### `nordpool_scheduler.set_auto_windows`

Replaces every [time window](#time-windows) auto mode runs in. `max_price` and `cheap_price` are optional and default to 0, which turns them off. An empty list leaves auto mode nothing to run.

```yaml
action: nordpool_scheduler.set_auto_windows
data:
  config_entry: 01JABCDEF0123456789ABCDEFG
  windows:
    - start: "06:00"
      end: "08:00"
      hours: 0.75
      max_price: 25
    - start: "20:00"
      end: "00:00"
      hours: 1
```

`config_entry` is the scheduler's config entry ID. Pick the scheduler from the dropdown in the action editor and switch to YAML to see it.

## Another Home Assistant instance

The card normally asks this integration for its data directly, so it only works on the instance the integration runs on. To show a scheduler on a second instance that mirrors this one with [Remote Home-Assistant](https://github.com/custom-components/remote_homeassistant), have it publish that data as an entity:

1. On the instance that runs the scheduler, enable its **Schedule** sensor, e.g. `sensor.nordpool_scheduler_boiler_schedule`. It's a diagnostic entity, disabled by default.
2. On the mirroring instance, make sure Remote Home-Assistant mirrors the scheduler's entities, and proxies `nordpool_scheduler.set_slots` and `nordpool_scheduler.set_auto_windows` with a service prefix. With `entity_prefix: darzs_`, use `service_prefix: darzs_` as well, so the card finds `nordpool_scheduler.darzs_set_slots` and `nordpool_scheduler.darzs_set_auto_windows` without being told.
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

The [card](https://github.com/klejejs/ha-nordpool-scheduler-card)'s ⓘ button explains every feature and how they combine, from its `src/info.ts`. A user-facing change here, such as a new option, entity or auto mode behaviour, also updates that file and the card's README.

## Releasing

Releases are made only through GitHub Releases. Pushing a tag on its own builds nothing.

Release Drafter keeps a draft release up to date on every merge to `main`. Its tag is the next minor version, or the next major one if a merged PR carries the `major` label. Its notes are grouped by PR label: `dependencies` (Renovate branches), `bug` (titles starting with "Fix") and `feature` (everything else). The labels are applied automatically when a PR opens, so relabel a PR before merging if it guessed wrong.

To release, publish that draft from the GitHub UI. If it should be a different version, change the tag, the release title and the "Full Changelog" link at the bottom of the notes together. The draft only fills them in once, so editing the tag alone leaves the other two pointing at the old version. The first release has no earlier one to count from, so set its version by hand.

Publishing runs the release workflow, which writes the release's tag into `manifest.json`, zips the integration and attaches `nordpool_scheduler.zip` to the release. That zip is what HACS installs. The `0.0.0` in the committed `manifest.json` is a placeholder and never needs editing.

## License

MIT, see [LICENSE](LICENSE). Started from ludeeus's [integration_blueprint](https://github.com/ludeeus/integration_blueprint).
