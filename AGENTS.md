# Nordpool Scheduler integration

A Home Assistant custom integration that switches an entity in 15-minute Nord Pool price slots. Run `scripts/test` (lint and pytest) before committing.

## Keep the card's info dialog complete

- A user-facing change here (a new option, entity, auto mode setting, or a change to how slots are picked or the target is switched) also needs the card updated: the info dialog in `src/info.ts` of [ha-nordpool-scheduler-card](https://github.com/klejejs/ha-nordpool-scheduler-card), which explains every feature and how they combine, and the card's README. Open that change alongside this one.
- Explain how the new behaviour interacts with the existing ones, not only what it does on its own.
- Keep this repo's `README.md` in step.

This file and `.github/copilot-instructions.md` carry the same rules; change both together.
