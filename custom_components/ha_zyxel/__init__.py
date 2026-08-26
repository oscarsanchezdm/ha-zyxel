"""The Zyxel integration."""
import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from custom_components.ha_zyxel.api import create_router, fetch_status
from custom_components.ha_zyxel.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from custom_components.ha_zyxel.migrate import async_migrate_unique_ids
from custom_components.ha_zyxel.services import async_setup_services, async_unload_services
from custom_components.ha_zyxel.sms_client import ZyxelSmsClient

_LOGGER = logging.getLogger(__name__)

# Block excessive nr7101 debug logging
nr7101_logger = logging.getLogger("nr7101.nr7101")
nr7101_logger.setLevel(logging.WARNING)

PLATFORMS = ["sensor", "button", "device_tracker", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Zyxel integration from a config entry."""
    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    try:
        router = await hass.async_add_executor_job(
            create_router, host, username, password
        )
    except Exception as ex:
        _LOGGER.error("Could not connect to Zyxel router: %s", ex)
        raise ConfigEntryNotReady from ex

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    sms_client = ZyxelSmsClient(host, username, password)

    hass.data.setdefault(DOMAIN, {})
    entry_data = {
        "router": router,
        "sms_client": sms_client,
    }
    hass.data[DOMAIN][entry.entry_id] = entry_data

    def _fetch():
        """Fetch router data; recreate the session once on failure (self-heal)."""
        client = entry_data["router"]
        try:
            return fetch_status(client)
        except Exception as err:  # noqa: BLE001 - desync/timeout/etc.
            _LOGGER.debug("Zyxel fetch failed, recreating session: %s", err)
            client = create_router(host, username, password)
            entry_data["router"] = client
            return fetch_status(client)

    async def async_update_data():
        # No asyncio timeout wrapper: each HTTP call is bounded by REQUEST_TIMEOUT
        # and DataUpdateCoordinator serialises refreshes, so the executor job always
        # finishes before the next one starts -> no overlapping threads / session desync.
        try:
            return await hass.async_add_executor_job(_fetch)
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error communicating with router: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )

    await coordinator.async_config_entry_first_refresh()
    entry_data["coordinator"] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Migrate legacy unique_ids before platforms recreate entities.
    await async_migrate_unique_ids(hass, entry.entry_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_services(hass)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change (scan interval, etc.)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        async_unload_services(hass)

    return unload_ok
