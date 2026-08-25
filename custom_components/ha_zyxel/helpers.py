"""Shared helpers for the Zyxel integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac

from .const import CONF_TRACK_ALL, DEFAULT_TRACK_ALL


def lan_hosts(coordinator) -> dict[str, dict]:
    """Return {formatted_mac: host_record} from the coordinator's lanhosts data."""
    block = (coordinator.data or {}).get("lanhosts")
    hosts = block.get("lanhosts") if isinstance(block, dict) else None
    result: dict[str, dict] = {}
    if isinstance(hosts, list):
        for host in hosts:
            mac = host.get("PhysAddress")
            if mac:
                result[format_mac(mac)] = host
    return result


def known_network_macs(hass: HomeAssistant) -> set[str]:
    """MACs already present on any device in the Home Assistant device registry."""
    registry = dr.async_get(hass)
    macs: set[str] = set()
    for device in registry.devices.values():
        for conn_type, value in device.connections:
            if conn_type == CONNECTION_NETWORK_MAC:
                macs.add(format_mac(value))
    return macs


def registered_tracker_macs(hass: HomeAssistant, entry_id: str) -> set[str]:
    """MACs that already have a device_tracker entity for this config entry."""
    registry = er.async_get(hass)
    macs: set[str] = set()
    for reg in er.async_entries_for_config_entry(registry, entry_id):
        if reg.domain != "device_tracker" or not reg.unique_id:
            continue
        macs.add(format_mac(reg.unique_id))
    return macs


def trackable_macs(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator,
    *,
    track_all: bool | None = None,
) -> set[str]:
    """MACs that should get per-client entities.

    With track_all enabled: every LAN host the router reports.
    With track_all disabled: only hosts HA already knows (device registry) or that
    already have a tracker entity for this integration (so reload keeps them).
    """
    hosts = set(lan_hosts(coordinator))
    if track_all is None:
        track_all = entry.options.get(CONF_TRACK_ALL, DEFAULT_TRACK_ALL)
    if track_all:
        return hosts
    allowed = known_network_macs(hass) | registered_tracker_macs(hass, entry.entry_id)
    return hosts & allowed
