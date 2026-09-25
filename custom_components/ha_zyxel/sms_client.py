"""Send SMS through Zyxel cellular routers using the nr7101 session.

The main integration authenticates with RSA/AES via nr7101. A separate
plaintext SMS login fails on modern firmwares (HTTP 401 "Invalid Username
or Password") even when sensor polling works. SMS therefore reuses the same
authenticated router object, cookies, sessionkey, and encryption.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

# Modem-side SMS can sit in the DAL queue; 10s is often too short (HTTP 504
# with ``{"result":"Timeout"}``).
_SMS_HTTP_TIMEOUT = 60


class ZyxelSmsClient:
    """Send SMS via the Zyxel ``cellwan_sms`` DAL endpoint."""

    def __init__(self, get_router: Callable[[], Any]) -> None:
        """``get_router`` returns the live nr7101 ``NR7101`` instance."""
        self._get_router = get_router

    def send_sms(self, number: str, text: str) -> tuple[bool, str]:
        """Send an SMS. Returns ``(ok, error_message)``."""
        return self._send_with_reauth(number, text, allow_reauth=True)

    def _send_with_reauth(
        self, number: str, text: str, *, allow_reauth: bool
    ) -> tuple[bool, str]:
        router = self._get_router()
        try:
            if not getattr(router, "sessionkey", None):
                if not router.login():
                    return False, "Router login failed"
        except Exception as err:  # noqa: BLE001
            return False, f"Router login failed: {err}"

        packed = _gsm_7bit_pack(text)
        payload = {
            "SMS_Format": 0,
            "SMS_CharacterSet": "GSM",
            "SMS_To": number,
            "SMS_ContentLength": len(text),
            "SMS_TimeStamp": "",
            "SMS_Content": packed.hex(),
            "SMS_Content_divLen": [len(text)],
            "SMS_Content_divData": [packed.hex()],
        }

        url = (
            f"{router.url}/cgi-bin/DAL?"
            f"oid=cellwan_sms&timedelay=1&sessionkey={router.sessionkey}"
        )

        if getattr(router, "encryption_required", False):
            body = router.encrypt_request(payload)
        else:
            body = json.dumps(payload, separators=(",", ":"))

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": router.url,
            "Referer": f"{router.url}/",
        }
        params = dict(router.params)
        # Override the shared poll timeout for this slow modem operation.
        params["timeout"] = _SMS_HTTP_TIMEOUT
        if "headers" in params:
            params["headers"] = {**params["headers"], **headers}
        else:
            params["headers"] = headers

        try:
            resp = requests.post(url, data=body.encode("utf-8"), **params)
        except requests.RequestException as err:
            return False, f"Request failed: {err}"

        try:
            raw = resp.json()
        except Exception:  # noqa: BLE001
            raw = {}

        try:
            if (
                getattr(router, "encryption_required", False)
                and isinstance(raw, dict)
                and "content" in raw
            ):
                data = router.decrypt_response(raw)
            else:
                data = raw
        except Exception:  # noqa: BLE001
            data = raw if isinstance(raw, dict) else {}

        if isinstance(data, dict) and data.get("result") == "ZCFG_SUCCESS":
            return True, ""

        # Stale/evicted session: Zyxel often answers 401 with a misleading
        # "Invalid Username or Password" even when credentials are fine.
        auth_failed = resp.status_code == 401 or (
            isinstance(data, dict)
            and "invalid" in str(data.get("result", "")).lower()
        )
        if allow_reauth and auth_failed:
            _LOGGER.info("SMS auth rejected; re-login and retry once")
            router.sessionkey = None
            try:
                router.clear_cookies()
            except Exception:  # noqa: BLE001
                pass
            try:
                # Fresh NR7101 instance is created by the caller on poll failure;
                # here we only re-login on the current object.
                if not router.login():
                    return False, f"HTTP {resp.status_code} / body {resp.text}"
            except Exception as err:  # noqa: BLE001
                return False, f"Re-login failed: {err}"
            return self._send_with_reauth(number, text, allow_reauth=False)

        return False, f"HTTP {resp.status_code} / body {resp.text}"


def _gsm_7bit_pack(text: str) -> bytes:
    """Pack text into GSM 7-bit septets."""
    septets = [ord(char) & 0x7F for char in text]
    packed: list[int] = []
    acc = 0
    bits = 0
    for septet in septets:
        acc |= (septet & 0x7F) << bits
        bits += 7
        while bits >= 8:
            packed.append(acc & 0xFF)
            acc >>= 8
            bits -= 8
    if bits > 0:
        packed.append(acc & 0xFF)
    return bytes(packed)
