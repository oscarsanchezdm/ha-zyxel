"""HTTP client for sending SMS through Zyxel cellular routers."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Optional, Tuple

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(InsecureRequestWarning)

_LOGGER = logging.getLogger(__name__)


class ZyxelSmsClient:
    """Send SMS via the Zyxel cellwan_sms DAL endpoint."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        session: Optional[requests.Session] = None,
        verify_ssl: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = session or requests.Session()
        self.session.verify = verify_ssl
        self.sessionkey: Optional[str] = None

    def ensure_logged_in(self) -> bool:
        """Log in using Base64 password (FWA505-style) with MD5/plain fallbacks."""
        if self.sessionkey:
            return True

        try:
            self.session.get(f"{self.base_url}/", timeout=5)
            self.session.get(f"{self.base_url}/login", timeout=5)
            self.session.get(f"{self.base_url}/getRSAPublickKey", timeout=5)
        except Exception:  # noqa: BLE001 - best-effort warm-up
            pass

        b64_pwd = base64.b64encode(self.password.encode("utf-8")).decode("ascii")
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/login",
        }
        payload = {
            "Input_Account": self.username,
            "Input_Passwd": b64_pwd,
            "currLang": "en",
            "RememberPassword": 0,
            "SHA512_password": False,
        }

        if self._try_login(payload, headers):
            return True

        md5_pwd = hashlib.md5(self.password.encode("utf-8")).hexdigest()
        for attempt in (
            {"Input_Passwd": md5_pwd, "SHA512_password": False},
            {"Input_Passwd": self.password, "SHA512_password": False},
        ):
            payload.update(attempt)
            if self._try_login(payload, headers):
                return True

        if self.base_url.startswith("https://"):
            try_base = "http://" + self.base_url.split("://", 1)[1]
            try:
                self.session.get(f"{try_base}/", timeout=5)
            except Exception:  # noqa: BLE001
                pass
            resp = self.session.post(
                f"{try_base}/UserLogin",
                data=json.dumps({**payload, "Input_Passwd": b64_pwd}),
                headers=headers,
                timeout=10,
            )
            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                data = {}
            if data.get("result") == "ZCFG_SUCCESS" and data.get("sessionkey"):
                self.base_url = try_base.rstrip("/")
                self.sessionkey = data["sessionkey"]
                return True

        return False

    def _try_login(self, payload: dict, headers: dict) -> bool:
        resp = self.session.post(
            f"{self.base_url}/UserLogin",
            data=json.dumps(payload),
            headers=headers,
            timeout=10,
        )
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = {}
        if data.get("result") == "ZCFG_SUCCESS" and data.get("sessionkey"):
            self.sessionkey = data["sessionkey"]
            return True
        return False

    @staticmethod
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

    def send_sms(self, number: str, text: str) -> Tuple[bool, str]:
        """Send an SMS. Returns (ok, error_message)."""
        if not self.ensure_logged_in():
            return False, "Session key unavailable"

        packed = self._gsm_7bit_pack(text)
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
            f"{self.base_url}/cgi-bin/DAL?"
            f"oid=cellwan_sms&timedelay=1&sessionkey={self.sessionkey}"
        )
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        }
        resp = self.session.post(url, data=json.dumps(payload), headers=headers, timeout=10)
        try:
            ok = resp.json().get("result") == "ZCFG_SUCCESS"
        except Exception:  # noqa: BLE001
            ok = False

        if ok:
            return True, ""
        return False, f"HTTP {resp.status_code} / body {resp.text}"
