from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DOMAIN = "ha_zyxel"
DEFAULT_NAME = "Zyxel Device"
DEFAULT_HOST = "https://192.168.1.1"
DEFAULT_USERNAME = "admin"
# Default poll period. Each refresh hits several HTTPS/AES endpoints on the
# router; sub-30s intervals can keep a small CPE (e.g. FWA505) busy.
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 20

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Options (configurable via the integration's "Configure" dialog)
CONF_SCAN_INTERVAL = "scan_interval"
CONF_CONSIDER_HOME = "consider_home"
CONF_TRACK_ALL = "track_all"
DEFAULT_CONSIDER_HOME = 300
DEFAULT_TRACK_ALL = False

# Optional OID polls (each is an extra HTTPS/AES round-trip). Off by default.
CONF_POLL_TRAFFIC = "poll_traffic"
CONF_POLL_CARDPAGE = "poll_cardpage"
CONF_POLL_WIFI_MESH = "poll_wifi_mesh"
CONF_POLL_ONE_CONNECT = "poll_one_connect"
DEFAULT_POLL_TRAFFIC = False
DEFAULT_POLL_CARDPAGE = False
DEFAULT_POLL_WIFI_MESH = False
DEFAULT_POLL_ONE_CONNECT = False

# Always fetched: status, cellular, LAN hosts, LAN config.
CORE_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("status", "device"),
    ("cellwan_status", "cellular"),
    ("lanhosts", "lanhosts"),
    ("lan", "lan"),
)

# option key -> (OID path, coordinator data key)
OPTIONAL_ENDPOINTS: dict[str, tuple[str, str]] = {
    CONF_POLL_TRAFFIC: ("Traffic_Status", "traffic"),
    CONF_POLL_CARDPAGE: ("cardpage_status", "cardpage"),
    CONF_POLL_WIFI_MESH: ("wifi_easy_mesh", "wifi_mesh"),
    CONF_POLL_ONE_CONNECT: ("one_connect", "one_connect"),
}

OPTIONAL_POLL_DEFAULTS: dict[str, bool] = {
    CONF_POLL_TRAFFIC: DEFAULT_POLL_TRAFFIC,
    CONF_POLL_CARDPAGE: DEFAULT_POLL_CARDPAGE,
    CONF_POLL_WIFI_MESH: DEFAULT_POLL_WIFI_MESH,
    CONF_POLL_ONE_CONNECT: DEFAULT_POLL_ONE_CONNECT,
}


def endpoints_from_options(options: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    """Build the OID list for this config entry's options."""
    opts = options or {}
    endpoints = list(CORE_ENDPOINTS)
    for conf_key, pair in OPTIONAL_ENDPOINTS.items():
        if opts.get(conf_key, OPTIONAL_POLL_DEFAULTS[conf_key]):
            endpoints.append(pair)
    return tuple(endpoints)


def disabled_optional_data_roots(options: Mapping[str, Any] | None) -> frozenset[str]:
    """Coordinator data keys for optional endpoints that are turned off."""
    opts = options or {}
    disabled: set[str] = set()
    for conf_key, (_oid, data_key) in OPTIONAL_ENDPOINTS.items():
        if not opts.get(conf_key, OPTIONAL_POLL_DEFAULTS[conf_key]):
            disabled.add(data_key)
    return frozenset(disabled)
