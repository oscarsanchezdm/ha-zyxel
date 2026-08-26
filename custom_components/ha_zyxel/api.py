"""Synchronous helpers for communicating with Zyxel devices."""

from __future__ import annotations

import logging
from typing import Any

from nr7101 import nr7101

from .const import CORE_ENDPOINTS

_LOGGER = logging.getLogger(__name__)

# Bound every HTTP call. nr7101 sets no request timeouts, so a hung request
# would otherwise pile up worker threads that share the router's one session
# and desync its AES key (shows up as "decrypt" errors that never heal).
REQUEST_TIMEOUT = 15


class ZyxelAuthenticationError(Exception):
    """Raised when the router rejects the supplied credentials."""


class ZyxelConnectionError(Exception):
    """Raised when no usable data can be fetched from the router."""


def create_router(host: str, username: str, password: str) -> Any:
    """Create a router with isolated cookies and a per-request timeout.

    nr7101 currently uses a mutable dictionary as its default ``params``
    argument. Passing a new dictionary explicitly prevents cookies from a
    config-flow instance being reused by the config-entry instance, where
    they would be paired with a different AES key.
    """
    return nr7101.NR7101(host, username, password, {"timeout": REQUEST_TIMEOUT})


def authenticate(router: Any) -> None:
    """Log in and verify that nr7101 received a session key."""
    try:
        login_success = router.login()
    except Exception as err:
        raise ZyxelConnectionError("Unable to complete router login") from err

    if not login_success or not getattr(router, "sessionkey", None):
        raise ZyxelAuthenticationError("The router rejected the credentials")


def _parse_traffic_object(obj: dict[str, Any] | None) -> dict[str, Any]:
    """Convert Traffic_Status interface arrays to a keyed dictionary."""
    if not obj or "ipIface" not in obj or "ipIfaceSt" not in obj:
        return {}

    return {
        interface["X_ZYXEL_IfName"]: status
        for interface, status in zip(obj["ipIface"], obj["ipIfaceSt"])
        if "X_ZYXEL_IfName" in interface
    }


def _fetch_available_endpoints(
    router: Any,
    endpoints: tuple[tuple[str, str], ...],
) -> tuple[dict[str, Any], Exception | None]:
    """Fetch the given endpoints once without an unbounded retry loop."""
    result: dict[str, Any] = {}
    last_error: Exception | None = None

    for endpoint, key in endpoints:
        try:
            data = router.get_json_object(endpoint)
            if endpoint == "Traffic_Status":
                data = _parse_traffic_object(data)
            if data:
                result[key] = data
        except Exception as err:  # Different firmware exposes different endpoints.
            last_error = err
            _LOGGER.debug("Zyxel endpoint %s is unavailable: %s", endpoint, err)

            # Invalid UTF-8 after AES decryption means the cookie/session and
            # AES key no longer match. Continuing would emit the same error for
            # every endpoint, so reauthenticate immediately.
            if "Failed to process decrypted response" in str(err):
                break

    return result, last_error


def fetch_status(
    router: Any,
    endpoints: tuple[tuple[str, str], ...] | None = None,
) -> dict[str, Any]:
    """Return available router data, reauthenticating once when necessary.

    ``endpoints`` defaults to core OIDs only (enough for config-flow validation).
    Runtime polling should pass ``endpoints_from_options(entry.options)``.
    """
    if endpoints is None:
        endpoints = CORE_ENDPOINTS

    if not getattr(router, "sessionkey", None):
        authenticate(router)

    last_error: Exception | None = None
    for attempt in range(2):
        result, last_error = _fetch_available_endpoints(router, endpoints)
        if result:
            return result

        if attempt == 0:
            router.sessionkey = None
            authenticate(router)

    raise ZyxelConnectionError(
        "The router returned no supported status data"
    ) from last_error


