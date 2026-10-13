"""The rules a set of auto mode time windows must follow."""

from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING

from homeassistant.exceptions import ServiceValidationError

from .auto import in_window
from .const import DOMAIN, SLOT_MINUTES

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .auto import AutoWindow

type Problem = tuple[str, dict[str, str]]

SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES
WHOLE_DAY_END = time(23, 59)


def window_label(window: AutoWindow) -> str:
    """Return a window as its From and To."""
    return f"{window.start:%H:%M} to {window.end:%H:%M}"


def _hours(hours: float) -> str:
    return f"{hours:g} h"


def _slots(hours: float) -> int:
    return round(hours * 60) // SLOT_MINUTES


def covered_slots(window: AutoWindow) -> frozenset[int]:
    """Return which of a nominal day's slots, by index from 00:00, a window covers."""
    return frozenset(
        index
        for index in range(SLOTS_PER_DAY)
        if in_window(
            time(index * SLOT_MINUTES // 60, index * SLOT_MINUTES % 60), window
        )
    )


def _on_boundary(at: time, *, end: bool) -> bool:
    if at.second or at.microsecond:
        return False
    return at.minute % SLOT_MINUTES == 0 or (end and at == WHOLE_DAY_END)


def window_problems(
    windows: Sequence[AutoWindow], *, runs_limited: bool, max_runs: float
) -> list[Problem]:
    """Return every rule the windows break, as translation keys and placeholders."""
    if not windows:
        return [("windows_empty", {})]

    covers = [covered_slots(window) for window in windows]
    problems = [
        problem
        for window, cover in zip(windows, covers, strict=True)
        for problem in _own_problems(window, cover)
    ]

    for i, cover in enumerate(covers):
        for j in range(i):
            if covers[j] == cover:
                problems.append(
                    (
                        "windows_duplicate",
                        {
                            "window": window_label(windows[j]),
                            "other": window_label(windows[i]),
                        },
                    )
                )
                break

    if not any(key == "window_hours_too_long" for key, _ in problems) and (
        unfit := _unfittable(windows, covers)
    ):
        problems.append(
            (
                "windows_hours_overflow",
                {"windows": ", ".join(window_label(window) for window in unfit)},
            )
        )

    if runs_limited:
        problems += run_limit_problems(windows, runs_limited=True, max_runs=max_runs)
    return problems


def _own_problems(window: AutoWindow, cover: frozenset[int]) -> list[Problem]:
    """Return the rules one window breaks on its own."""
    problems: list[Problem] = []
    label = {"window": window_label(window)}
    for at, end in ((window.start, False), (window.end, True)):
        if not _on_boundary(at, end=end):
            problems.append(
                ("window_time_not_aligned", {**label, "time": at.isoformat()})
            )
    covered = {**label, "covered": _hours(len(cover) * SLOT_MINUTES / 60)}
    if _slots(window.hours) > len(cover):
        problems.append(
            ("window_hours_too_long", {**covered, "hours": _hours(window.hours)})
        )
    if _slots(window.min_run_hours) > len(cover):
        problems.append(
            (
                "window_min_run_too_long",
                {**covered, "min_run": _hours(window.min_run_hours)},
            )
        )
    if window.hours > 0 and window.min_run_hours > window.hours:
        problems.append(
            (
                "window_min_run_above_hours",
                {
                    **label,
                    "min_run": _hours(window.min_run_hours),
                    "hours": _hours(window.hours),
                },
            )
        )
    if window.max_price > 0 and window.cheap_price > window.max_price:
        problems.append(
            (
                "window_cheap_above_max",
                {
                    **label,
                    "cheap_price": f"{window.cheap_price:g}",
                    "max_price": f"{window.max_price:g}",
                },
            )
        )
    if window.hours == 0 and window.cheap_price == 0:
        problems.append(("window_does_nothing", label))
    return problems


def run_limit_problems(
    windows: Sequence[AutoWindow], *, runs_limited: bool, max_runs: float
) -> list[Problem]:
    """Return the problems of the run limit with these windows."""
    problems: list[Problem] = []
    if max_runs != int(max_runs):
        problems.append(("max_runs_not_whole", {"max_runs": f"{max_runs:g}"}))
    running = sum(1 for window in windows if _slots(window.hours) > 0)
    if runs_limited and running > max_runs:
        problems.append(
            (
                "windows_too_many_runs",
                {"count": str(running), "max_runs": f"{max_runs:g}"},
            )
        )
    return problems


def _unfittable(
    windows: Sequence[AutoWindow], covers: Sequence[frozenset[int]]
) -> list[AutoWindow]:
    """Return windows whose hours add up to more than the slots they cover together.

    Each window needs its hours in slots no other window took, so this
    matches every needed slot to a covered one and, when one can't be,
    returns the windows that compete for the slots it could have had.
    """
    needs = [i for i, window in enumerate(windows) for _ in range(_slots(window.hours))]
    holder: dict[int, int] = {}

    def place(need: int, seen: set[int]) -> bool:
        for slot in sorted(covers[needs[need]]):
            if slot in seen:
                continue
            seen.add(slot)
            if slot not in holder or place(holder[slot], seen):
                holder[slot] = need
                return True
        return False

    for need in range(len(needs)):
        seen: set[int] = set()
        if not place(need, seen):
            competing = {needs[need]} | {needs[holder[slot]] for slot in seen}
            return [windows[i] for i in sorted(competing)]
    return []


def raise_first(problems: list[Problem]) -> None:
    """Raise the first problem as a service validation error."""
    if problems:
        key, placeholders = problems[0]
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders=placeholders,
        )
