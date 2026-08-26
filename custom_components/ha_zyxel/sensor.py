"""Support for Zyxel device sensors."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.ha_zyxel.const import CONF_TRACK_ALL, DEFAULT_TRACK_ALL, DOMAIN
from custom_components.ha_zyxel.helpers import lan_hosts, trackable_macs

_LOGGER = logging.getLogger(__name__)

# How far calculated boot time may drift before we accept a new value (reboot).
_STARTUP_STABILITY_SECONDS = 30

# status / cellwan_status often expose the same nested objects (CellIntfInfo,
# DeviceInfo, …). Treat those roots as one namespace for entity identity.
# cardpage_status is optional and keeps its ``cardpage.`` prefix so disabling
# that poll can remove its entities cleanly.
_DEDUP_ROOTS = frozenset({"device", "cellular"})
# Lower rank wins when the same relative path appears under several roots.
_ENDPOINT_PRIORITY = {
    "cellular": 0,
    "device": 1,
    "cardpage": 2,
    "traffic": 3,
    "lan": 4,
    "lanhosts": 5,
    "wifi_mesh": 6,
    "one_connect": 7,
}
# Define some known sensor types for proper configuration
KNOWN_SENSORS = {
    "Uptime": {
        "name": "Uptime",
        "unit": UnitOfTime.SECONDS,
        "icon": "mdi:clock-outline",
        "device_class": SensorDeviceClass.DURATION,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "UpTime": {
        "name": "Uptime",
        "unit": UnitOfTime.SECONDS,
        "icon": "mdi:clock-outline",
        "device_class": SensorDeviceClass.DURATION,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "INTF_RSSI": {
        "name": "Cellular RSSI",
        "unit": "dBm",
        "icon": "mdi:signal",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "INTF_PhyCell_ID": {
        "name": "Physical Cell ID",
        "unit": None,
        "icon": "mdi:antenna",
        "device_class": None,
        "state_class": None,
    },
    "INTF_RSRP": {
        "name": "Cellular Reference Signal Received Power",
        "unit": "dBm",
        "icon": "mdi:signal",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "INTF_RSRQ": {
        "name": "Cellular Reference Signal Received Quality",
        "unit": "dB",
        "icon": "mdi:signal",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "INTF_SINR": {
        "name": "Cellular Signal-to-Noise Ratio",
        "unit": "dB",
        "icon": "mdi:signal",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "INTF_MCS": {
        "name": "Cellular Modulation and Coding Scheme",
        "unit": "",
        "icon": "mdi:signal",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "INTF_CQI": {
        "name": "Cellular Channel Quality Indicator",
        "unit": "",
        "icon": "mdi:signal",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "INTF_RI": {
        "name": "Cellular Rank Indicator",
        "unit": "",
        "icon": "mdi:signal",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "INTF_PMI": {
        "name": "Cellular Precoding Matrix Indicator",
        "unit": "",
        "icon": "mdi:signal",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "NSA_PhyCellID": {
        "name": "NSA Physical Cell ID",
        "unit": None,
        "icon": "mdi:antenna",
        "device_class": None,
        "state_class": None,
    },
    "NSA_RSRP": {
        "name": "NSA Reference Signal Received Power",
        "unit": "dBm",
        "icon": "mdi:signal",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
        "state_class": SensorStateClass.MEASUREMENT
    },
    "NSA_RSRQ": {
        "name": "NSA Reference Signal Received Quality",
        "unit": "dB",
        "icon": "mdi:signal",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
        "state_class": SensorStateClass.MEASUREMENT
    },
    "NSA_RSSI": {
        "name": "NSA Reference Signal Strength Indicator",
        "unit": "dBm",
        "icon": "mdi:signal",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
        "state_class": SensorStateClass.MEASUREMENT
    },
    "NSA_SINR": {
        "name": "NSA Signal-to-Noise Ratio",
        "unit": "dB",
        "icon": "mdi:signal",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
        "state_class": SensorStateClass.MEASUREMENT
    },
    "X_ZYXEL_TEMPERATURE_AMBIENT": {
        "name": "Ambient Temperature",
        "unit": "°C",
        "icon": "mdi:thermometer",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT
    },
    "X_ZYXEL_TEMPERATURE_SDX": {
        "name": "SDX Temperature",
        "unit": "°C",
        "icon": "mdi:thermometer",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT
    },
    "X_ZYXEL_TEMPERATURE_CPU0": {
        "name": "CPU Temperature",
        "unit": "°C",
        "icon": "mdi:thermometer",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT
    },
    "BytesSent": {
        "name": "Bytes Sent",
        "unit": "B",
        "icon": "mdi:numeric-10-box",
        "device_class": SensorDeviceClass.DATA_SIZE,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "BytesReceived": {
        "name": "Bytes Received",
        "unit": "B",
        "icon": "mdi:numeric-10-box",
        "device_class": SensorDeviceClass.DATA_SIZE,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "PacketsSent": {
        "name": "Packets Sent",
        "unit": "packets",
        "icon": "mdi:swap-vertical",
        "device_class": None,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "PacketsReceived": {
        "name": "Packets Received",
        "unit": "packets",
        "icon": "mdi:swap-vertical",
        "device_class": None,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    # ProcessStatus.CPUUsage — must be numeric for history/statistics.
    # device_class left None: SensorDeviceClass.PERCENTAGE is not available on
    # all Home Assistant versions; unit "%" + MEASUREMENT is enough.
    "CPUUsage": {
        "name": "CPU Usage",
        "unit": "%",
        "icon": "mdi:cpu-64-bit",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "MemoryUsage": {
        "name": "Memory Usage",
        "unit": "%",
        "icon": "mdi:memory",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "MemUsage": {
        "name": "Memory Usage",
        "unit": "%",
        "icon": "mdi:memory",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
}


def _flatten_dict(d: dict, parent_key: str = "") -> dict:
    """Flatten a nested dictionary with dot notation for keys."""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}.{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key).items())
        else:
            items.append((new_key, v))
    return dict(items)


def _is_value_scalar(value: Any) -> bool:
    """Check if a value is a scalar (string, number, bool)."""
    return isinstance(value, (str, int, float, bool)) or value is None


def _known_sensor_config(leaf: str) -> dict | None:
    """Look up a curated sensor config, case-insensitive on the leaf key."""
    if leaf in KNOWN_SENSORS:
        return KNOWN_SENSORS[leaf]
    lowered = leaf.lower()
    for key, config in KNOWN_SENSORS.items():
        if key.lower() == lowered:
            return config
    return None


def _coerce_native_value(value: Any) -> Any:
    """Return ints/floats as numbers; coerce numeric strings; leave the rest.

    Zyxel firmware often encodes ProcessStatus.CPUUsage (and similar) as a
    string. Home Assistant only treats the entity as numeric when native_value
    is int/float, so we must coerce here.
    """
    if value is None or isinstance(value, bool):
        # bool is a subclass of int — keep switches/flags as non-numeric.
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            number = float(text)
        except ValueError:
            return value
        if number.is_integer() and "." not in text and "e" not in text.lower():
            return int(number)
        return number
    return value


def _sensor_identity(key: str) -> str:
    """Stable identity for entity unique_id / deduplication.

    For overlapping status dumps, drop the endpoint root so
    ``cellular.CellIntfInfo.Upstream`` and ``device.CellIntfInfo.Upstream``
    collapse to ``CellIntfInfo.Upstream``. Other endpoints keep the full path
    (``traffic.br0.BytesSent``, ``cardpage.…``).
    """
    root, sep, rest = key.partition(".")
    if sep and root in _DEDUP_ROOTS and rest:
        return rest
    return key


def _endpoint_rank(key: str) -> int:
    """Prefer cellular > device > cardpage when picking a duplicate's source."""
    return _ENDPOINT_PRIORITY.get(key.split(".", 1)[0], 99)


def _iter_unique_sensor_keys(data: dict | None) -> list[str]:
    """Flatten coordinator data and drop cross-endpoint duplicate paths."""
    best: dict[str, str] = {}
    for key, value in _flatten_dict(data or {}).items():
        if not _is_value_scalar(value):
            continue
        identity = _sensor_identity(key)
        previous = best.get(identity)
        if previous is None or _endpoint_rank(key) < _endpoint_rank(previous):
            best[identity] = key
    # Stable order for predictable entity setup.
    return [best[identity] for identity in sorted(best)]


def _read_path(data: Any, key: str) -> Any:
    """Walk a dotted path into nested dicts; raise KeyError if missing."""
    value = data
    for part in key.split("."):
        value = value[part]
    return value


def _parse_uptime_seconds(value: Any) -> int | None:
    """Coerce a router uptime field to whole seconds."""
    if value is None or value is False:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _find_uptime_seconds(data: dict | None) -> int | None:
    """Pick the best uptime reading from flattened coordinator data."""
    preferred: list[int] = []
    others: list[int] = []
    for key, value in _flatten_dict(data or {}).items():
        if key.split(".")[-1].lower() != "uptime":
            continue
        seconds = _parse_uptime_seconds(value)
        if seconds is None:
            continue
        if "device_info" in key.lower() or "deviceinfo" in key.lower():
            preferred.append(seconds)
        else:
            others.append(seconds)
    if preferred:
        return preferred[0]
    if others:
        return others[0]
    return None


def _find_memory_total_free(data: dict | None) -> tuple[float | None, float | None]:
    """Return (total, free) from MemoryStatus fields in coordinator data."""
    total: float | None = None
    free: float | None = None
    for key, value in _flatten_dict(data or {}).items():
        parts = key.split(".")
        if len(parts) < 2:
            continue
        if parts[-2].lower() != "memorystatus":
            continue
        leaf = parts[-1].lower()
        number = _coerce_native_value(value)
        if not isinstance(number, (int, float)):
            continue
        if leaf == "total":
            total = float(number)
        elif leaf == "free":
            free = float(number)
    return total, free


def _memory_usage_percent(data: dict | None) -> float | None:
    """Used RAM percentage from MemoryStatus Total/Free."""
    total, free = _find_memory_total_free(data)
    if total is None or free is None or total <= 0:
        return None
    used = total - free
    if used < 0:
        used = 0.0
    return round(used / total * 100.0, 1)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Zyxel sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Router telemetry: one entity per logical field (cross-endpoint duplicates
    # like cardpage.* vs device.* CellIntfInfo are collapsed).
    sensors = []
    for key in _iter_unique_sensor_keys(coordinator.data):
        sensor_config = _known_sensor_config(key.split(".")[-1])
        if sensor_config:
            sensors.append(ConfiguredZyxelSensor(coordinator, entry, key, sensor_config))
        else:
            sensors.append(GenericZyxelSensor(coordinator, entry, key))

    sensors.append(ZyxelConnectedClients(coordinator, entry))
    sensors.append(ZyxelStartupTime(coordinator, entry))
    sensors.append(ZyxelMemoryUsage(coordinator, entry))
    async_add_entities(sensors)

    # Per-client diagnostic sensors (signal / link rate), discovered dynamically
    # for the same MAC set as device trackers (respects track_all).
    tracked: set[str] = set()
    track_all = entry.options.get(CONF_TRACK_ALL, DEFAULT_TRACK_ALL)

    @callback
    def _discover_clients() -> None:
        new = []
        for mac in trackable_macs(hass, entry, coordinator, track_all=track_all):
            if mac not in tracked:
                tracked.add(mac)
                new.extend(
                    ZyxelClientAttrSensor(coordinator, mac, spec)
                    for spec in CLIENT_SENSOR_SPECS
                )
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_discover_clients))
    _discover_clients()


class AbstractZyxelSensor(CoordinatorEntity, SensorEntity):
    """Base class for Zyxel device sensors."""

    # Auto-generated router telemetry: diagnostic and off by default — a full
    # status dump creates a long tail of entities.
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry: ConfigEntry, key: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = key
        self._identity = _sensor_identity(key)
        # Identity-based unique_id so device/cellular duplicates share one entity.
        self._attr_unique_id = f"{entry.entry_id}_{self._identity}"
        self._attr_name = f"Zyxel {self._identity}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Zyxel ({entry.data['host']})",
            manufacturer="Zyxel",
            model="",
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False

        try:
            self._get_value_from_path()
            return True
        except (KeyError, AttributeError, TypeError):
            return False

    def _get_value_from_path(self) -> Any:
        """Read the preferred path, then the same relative path under other roots."""
        data = self.coordinator.data
        try:
            return _read_path(data, self._key)
        except (KeyError, TypeError):
            pass

        # Preferred endpoint missing this poll — try the other overlapping dumps.
        if self._identity == self._key:
            raise KeyError(self._key)
        root = self._key.split(".", 1)[0]
        for alt in sorted(_DEDUP_ROOTS, key=lambda r: _ENDPOINT_PRIORITY.get(r, 99)):
            if alt == root:
                continue
            try:
                return _read_path(data, f"{alt}.{self._identity}")
            except (KeyError, TypeError):
                continue
        raise KeyError(self._identity)

class ConfiguredZyxelSensor(AbstractZyxelSensor):
    """Representation of a configured (curated) Zyxel sensor."""

    # Even curated router fields stay off by default: a full status dump can
    # create dozens of entities (BytesSent per interface, cellular metrics, …).
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry: ConfigEntry, key: str, config: dict):
        """Initialize the sensor."""
        super().__init__(coordinator, entry, key)
        self._config = config
        self._attr_native_unit_of_measurement = config["unit"]
        self._attr_icon = config["icon"]
        self._attr_device_class = config["device_class"]
        self._attr_state_class = config["state_class"]

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        try:
            value = self._get_value_from_path()
        except (KeyError, AttributeError, TypeError):
            return None
        if self._attr_device_class == SensorDeviceClass.DURATION:
            return _parse_uptime_seconds(value)
        return _coerce_native_value(value)


class GenericZyxelSensor(AbstractZyxelSensor):
    """Representation of a generic Zyxel sensor."""

    @property
    def native_value(self):
        """Return the native value of the sensor (numeric when the payload allows)."""
        try:
            return _coerce_native_value(self._get_value_from_path())
        except (KeyError, AttributeError, TypeError):
            return None

    @property
    def state_class(self):
        """Expose MEASUREMENT for numeric values so HA records statistics."""
        value = self.native_value
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return SensorStateClass.MEASUREMENT
        return None

    @property
    def icon(self):
        """Return the icon."""
        return "mdi:router-wireless"

class ZyxelConnectedClients(CoordinatorEntity, SensorEntity):
    """Number of devices currently connected to the router."""

    _attr_icon = "mdi:lan-connect"
    _attr_name = "Connected devices"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_connected_clients"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Zyxel ({entry.data['host']})",
            manufacturer="Zyxel",
        )

    @property
    def native_value(self) -> int:
        return sum(1 for h in lan_hosts(self.coordinator).values() if h.get("Active"))


class ZyxelMemoryUsage(CoordinatorEntity, SensorEntity):
    """RAM used % derived from MemoryStatus.Total and MemoryStatus.Free."""

    _attr_name = "Memory Usage"
    _attr_icon = "mdi:memory"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_memory_usage"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Zyxel ({entry.data['host']})",
            manufacturer="Zyxel",
        )

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        return _memory_usage_percent(self.coordinator.data) is not None

    @property
    def native_value(self) -> float | None:
        return _memory_usage_percent(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        total, free = _find_memory_total_free(self.coordinator.data)
        used = (total - free) if total is not None and free is not None else None
        return {
            "total_kb": total,
            "free_kb": free,
            "used_kb": used,
        }


class ZyxelStartupTime(CoordinatorEntity, SensorEntity):
    """Boot timestamp derived from uptime; stable across poll jitter."""

    _attr_name = "Startup time"
    _attr_icon = "mdi:clock-start"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._startup: datetime | None = None
        self._attr_unique_id = f"{entry.entry_id}_startup_time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Zyxel ({entry.data['host']})",
            manufacturer="Zyxel",
        )
        self._refresh_startup()

    def _refresh_startup(self) -> None:
        uptime = _find_uptime_seconds(self.coordinator.data)
        if uptime is None:
            return
        calculated = (
            datetime.now(timezone.utc) - timedelta(seconds=uptime)
        ).replace(microsecond=0)
        if self._startup is None:
            self._startup = calculated
            return
        # Keep the previous stamp unless uptime reset (reboot) or large drift.
        if abs((calculated - self._startup).total_seconds()) >= _STARTUP_STABILITY_SECONDS:
            self._startup = calculated

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh_startup()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> datetime | None:
        return self._startup


class _ZyxelClientSensor(CoordinatorEntity, SensorEntity):
    """Base for per-client diagnostic sensors (attached to the client's device)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, mac: str):
        super().__init__(coordinator)
        self._mac = mac
        host = lan_hosts(coordinator).get(mac, {})
        friendly = host.get("curHostName") or host.get("HostName") or mac
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, mac)},
            default_name=friendly,
        )

    @property
    def _host(self) -> dict:
        return lan_hosts(self.coordinator).get(self._mac, {})


def _is_wifi(host: dict) -> bool:
    return "WiFi" in (host.get("Layer1Interface") or "")


def _nz(value):
    """Treat 0 / empty as no reading (avoids fake -0 dBm etc.)."""
    return value if value not in (None, 0, "") else None


def _wifi_only(fn):
    """Only return a value for Wi-Fi clients (None for wired)."""
    return lambda host: (fn(host) if _is_wifi(host) else None)


def _kbps_to_mbps(value):
    return round(value / 1000, 1) if isinstance(value, (int, float)) and value else None


# Per-client diagnostic sensors, one entity each. All disabled by default; enable
# the ones you want per device. "id" is stable — it forms the entity unique_id.
CLIENT_SENSOR_SPECS: list[dict] = [
    {"id": "rssi", "name": "Signal strength", "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
     "unit": "dBm", "state_class": SensorStateClass.MEASUREMENT,
     "fn": _wifi_only(lambda h: _nz(h.get("X_ZYXEL_RSSI")))},
    {"id": "snr", "name": "Signal-to-noise ratio", "unit": "dB", "icon": "mdi:signal",
     "state_class": SensorStateClass.MEASUREMENT,
     "fn": _wifi_only(lambda h: _nz(h.get("X_ZYXEL_SNR")))},
    {"id": "signal_quality", "name": "Signal quality", "unit": "%", "icon": "mdi:signal",
     "state_class": SensorStateClass.MEASUREMENT,
     "fn": _wifi_only(lambda h: _nz(h.get("X_ZYXEL_SignalStrength")))},
    {"id": "link_rate", "name": "Link rate", "device_class": SensorDeviceClass.DATA_RATE,
     "unit": "Mbit/s", "state_class": SensorStateClass.MEASUREMENT,
     "fn": lambda h: h.get("X_ZYXEL_PhyRate")},
    {"id": "downlink_rate", "name": "Downlink rate", "device_class": SensorDeviceClass.DATA_RATE,
     "unit": "Mbit/s", "state_class": SensorStateClass.MEASUREMENT,
     "fn": lambda h: _kbps_to_mbps(h.get("X_ZYXEL_LastDataDownlinkRate"))},
    {"id": "uplink_rate", "name": "Uplink rate", "device_class": SensorDeviceClass.DATA_RATE,
     "unit": "Mbit/s", "state_class": SensorStateClass.MEASUREMENT,
     "fn": lambda h: _kbps_to_mbps(h.get("X_ZYXEL_LastDataUplinkRate"))},
    {"id": "bytes_received", "name": "Bytes received", "device_class": SensorDeviceClass.DATA_SIZE,
     "unit": "B", "state_class": SensorStateClass.TOTAL_INCREASING,
     "fn": lambda h: h.get("X_ZYXEL_BytesReceived")},
    {"id": "bytes_sent", "name": "Bytes sent", "device_class": SensorDeviceClass.DATA_SIZE,
     "unit": "B", "state_class": SensorStateClass.TOTAL_INCREASING,
     "fn": lambda h: h.get("X_ZYXEL_BytesSent")},
    {"id": "connected_duration", "name": "Connected duration",
     "device_class": SensorDeviceClass.DURATION, "unit": "s",
     "state_class": SensorStateClass.MEASUREMENT,
     "fn": lambda h: h.get("X_ZYXEL_Duration")},
    {"id": "ip_address", "name": "IP address", "icon": "mdi:ip-network",
     "fn": lambda h: h.get("IPAddress") or None},
    {"id": "ssid", "name": "SSID", "icon": "mdi:wifi",
     "fn": _wifi_only(lambda h: h.get("WiFiname") or None)},
    {"id": "band", "name": "Band", "icon": "mdi:wifi",
     "fn": _wifi_only(lambda h: h.get("SupportedFrequencyBands") or None)},
    {"id": "network", "name": "Network", "icon": "mdi:wifi-cog",
     "fn": _wifi_only(lambda h: ("main" if h.get("X_ZYXEL_MainSSID") else "guest")
                      if "X_ZYXEL_MainSSID" in h else None)},
    {"id": "wifi_standard", "name": "Wi-Fi standard", "icon": "mdi:wifi",
     "fn": _wifi_only(lambda h: h.get("X_ZYXEL_OperatingStandard") or None)},
    {"id": "connection_type", "name": "Connection type", "icon": "mdi:lan",
     "fn": lambda h: ("wifi" if _is_wifi(h) else ("ethernet" if h.get("Layer1Interface") else None))},
    {"id": "device_type", "name": "Device type", "icon": "mdi:devices",
     "fn": lambda h: h.get("X_ZYXEL_HostType") or None},
    {"id": "address_source", "name": "Address source", "icon": "mdi:ip",
     "fn": lambda h: h.get("AddressSource") or None},
]


class ZyxelClientAttrSensor(_ZyxelClientSensor):
    """One diagnostic value for a client, driven by a CLIENT_SENSOR_SPECS entry."""

    def __init__(self, coordinator, mac: str, spec: dict):
        super().__init__(coordinator, mac)
        self._value_fn = spec["fn"]
        self._attr_unique_id = f"{mac}_{spec['id']}"
        self._attr_name = spec["name"]
        if spec.get("device_class"):
            self._attr_device_class = spec["device_class"]
        if spec.get("unit"):
            self._attr_native_unit_of_measurement = spec["unit"]
        if spec.get("state_class"):
            self._attr_state_class = spec["state_class"]
        if spec.get("icon"):
            self._attr_icon = spec["icon"]

    @property
    def native_value(self):
        try:
            return _coerce_native_value(self._value_fn(self._host))
        except Exception:  # noqa: BLE001 - one bad client must not break the platform
            return None
