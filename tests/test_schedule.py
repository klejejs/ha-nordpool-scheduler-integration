"""Tests for ScheduleStore."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from custom_components.nordpool_scheduler.schedule import ScheduleStore

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

SLOT_A = datetime(2026, 1, 1, 8, 30, tzinfo=UTC)
SLOT_B = datetime(2026, 1, 1, 8, 45, tzinfo=UTC)


async def test_set_get_clear(hass: HomeAssistant) -> None:
    """Overrides can be set, read back, and cleared."""
    store = ScheduleStore(hass, "entry1")
    await store.async_load()

    assert store.get(SLOT_A) is None

    store.set_slot(SLOT_A, state=True)
    store.set_slot(SLOT_B, state=False)
    assert store.get(SLOT_A) is True
    assert store.get(SLOT_B) is False
    assert store.as_dict() == {SLOT_A: True, SLOT_B: False}

    store.set_slot(SLOT_A, state=None)
    assert store.get(SLOT_A) is None
    assert SLOT_A not in store.as_dict()

    store.clear()
    assert store.as_dict() == {}


async def test_prune_ended_keeps_current_and_future_slots(hass: HomeAssistant) -> None:
    """Only overrides for slots that have fully ended are dropped."""
    store = ScheduleStore(hass, "entry1")
    await store.async_load()

    past = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)  # ended by 08:30
    current = datetime(2026, 1, 1, 8, 30, tzinfo=UTC)
    future = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    for slot in (past, current, future):
        store.set_slot(slot, state=True)

    store.prune_ended(datetime(2026, 1, 1, 8, 31, tzinfo=UTC))

    assert store.get(past) is None
    assert store.get(current) is True
    assert store.get(future) is True


async def test_persists_across_instances(hass: HomeAssistant) -> None:
    """Saved overrides are readable by a fresh ScheduleStore for the same entry."""
    store = ScheduleStore(hass, "entry1")
    await store.async_load()
    store.set_slot(SLOT_A, state=True)
    await hass.async_block_till_done()
    # Force the delayed save to happen now.
    await store._store.async_save({SLOT_A.isoformat(): "on"})

    reloaded = ScheduleStore(hass, "entry1")
    await reloaded.async_load()
    assert reloaded.get(SLOT_A) is True
