"""Shared entity helpers for Nordpool Scheduler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


def build_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Build the shared device a scheduler's entities belong to."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        entry_type=DeviceEntryType.SERVICE,
        name=entry.title,
    )
