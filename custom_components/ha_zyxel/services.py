"""Home Assistant services for ha_zyxel."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_SMS = "send_sms"
ATTR_NUMBER = "number"
ATTR_TEXT = "text"
ATTR_DEVICE_ID = "device_id"

SMS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NUMBER): cv.string,
        vol.Required(ATTR_TEXT): cv.string,
        vol.Optional(ATTR_DEVICE_ID): cv.string,
    }
)


def _resolve_sms_client(hass: HomeAssistant, device_id: str | None):
    """Pick the SMS client for a config entry, or the first available one."""
    domain_data = hass.data.get(DOMAIN, {})
    if device_id:
        entry_data = domain_data.get(device_id)
        if entry_data and entry_data.get("sms_client"):
            return entry_data["sms_client"]
        _LOGGER.error("No Zyxel SMS client for device_id=%s", device_id)
        return None

    for entry_data in domain_data.values():
        if entry_data.get("sms_client"):
            return entry_data["sms_client"]

    _LOGGER.error("No Zyxel SMS client available")
    return None


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register domain services once."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_SMS):
        return

    async def handle_send_sms(call: ServiceCall) -> None:
        client = _resolve_sms_client(hass, call.data.get(ATTR_DEVICE_ID))
        if client is None:
            return

        ok, error = await hass.async_add_executor_job(
            client.send_sms, call.data[ATTR_NUMBER], call.data[ATTR_TEXT]
        )
        if not ok:
            _LOGGER.error("Error sending SMS: %s", error)

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_SMS, handle_send_sms, schema=SMS_SCHEMA
    )


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove domain services when the last config entry unloads."""
    if hass.data.get(DOMAIN):
        return
    if hass.services.has_service(DOMAIN, SERVICE_SEND_SMS):
        hass.services.async_remove(DOMAIN, SERVICE_SEND_SMS)
