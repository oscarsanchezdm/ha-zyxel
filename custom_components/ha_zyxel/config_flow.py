"""Config flow for Zyxel integration."""
import logging

import voluptuous as vol

from homeassistant import config_entries, core
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

from .api import (
    ZyxelAuthenticationError,
    ZyxelConnectionError,
    create_router,
    fetch_status,
)
from .const import (
    CONF_CONSIDER_HOME,
    CONF_POLL_CARDPAGE,
    CONF_POLL_ONE_CONNECT,
    CONF_POLL_TRAFFIC,
    CONF_POLL_WIFI_MESH,
    CONF_SCAN_INTERVAL,
    CONF_TRACK_ALL,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_HOST,
    DEFAULT_POLL_CARDPAGE,
    DEFAULT_POLL_ONE_CONNECT,
    DEFAULT_POLL_TRAFFIC,
    DEFAULT_POLL_WIFI_MESH,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRACK_ALL,
    DEFAULT_USERNAME,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Block excessive nr7101 debug logging
nr7101_logger = logging.getLogger("nr7101.nr7101")
nr7101_logger.setLevel(logging.WARNING)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: core.HomeAssistant, data):
    """Validate that the user input allows us to connect."""

    try:
        router = await hass.async_add_executor_job(
            create_router,
            data[CONF_HOST],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
        )

        await hass.async_add_executor_job(fetch_status, router)
    except (ZyxelAuthenticationError, ZyxelConnectionError):
        raise
    except Exception as ex:
        _LOGGER.error("Unable to connect to Zyxel device: %s", ex)
        raise ZyxelConnectionError from ex

    return {"title": f"Zyxel device: ({data[CONF_HOST]})"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Zyxel devices."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    @staticmethod
    @core.callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return OptionsFlowHandler()

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        success = False

        if user_input is not None:
            host = user_input[CONF_HOST]

            # sanitize entry
            if not host.startswith("http://") and not host.startswith("https://"):
                host = f"https://{host}"
                user_input[CONF_HOST] = host

            try:
                info = await validate_input(self.hass, user_input)
                success = True
            except ZyxelAuthenticationError:
                errors["base"] = "invalid_auth"
            except ZyxelConnectionError as err:
                _LOGGER.error("Connection attempt failed: %s", err)
                errors["base"] = "cannot_connect"

            if not success and "https" not in user_input["host"]:
                _LOGGER.info("User specified http but it failed, trying https...")
                user_input["host"] = user_input["host"].replace("http://", "https://")
                try:
                    info = await validate_input(self.hass, user_input)
                    success = True
                except ZyxelAuthenticationError:
                    errors["base"] = "invalid_auth"
                except ZyxelConnectionError:
                    errors["base"] = "cannot_connect"
                except Exception as e:  # pylint: disable=broad-except
                    _LOGGER.exception("Second attempt failed: %s", e)
                    errors["base"] = "unknown"

        if success:
            return self.async_create_entry(title=info["title"], data=user_input)
        else:
            return self.async_show_form(
                step_id="user", data_schema=DATA_SCHEMA, errors=errors
            )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Zyxel options: poll interval, tracking, and optional OID polls."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)
                ),
                vol.Optional(
                    CONF_CONSIDER_HOME,
                    default=opts.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=86400)),
                vol.Optional(
                    CONF_TRACK_ALL,
                    default=opts.get(CONF_TRACK_ALL, DEFAULT_TRACK_ALL),
                ): bool,
                vol.Optional(
                    CONF_POLL_TRAFFIC,
                    default=opts.get(CONF_POLL_TRAFFIC, DEFAULT_POLL_TRAFFIC),
                ): bool,
                vol.Optional(
                    CONF_POLL_CARDPAGE,
                    default=opts.get(CONF_POLL_CARDPAGE, DEFAULT_POLL_CARDPAGE),
                ): bool,
                vol.Optional(
                    CONF_POLL_WIFI_MESH,
                    default=opts.get(CONF_POLL_WIFI_MESH, DEFAULT_POLL_WIFI_MESH),
                ): bool,
                vol.Optional(
                    CONF_POLL_ONE_CONNECT,
                    default=opts.get(CONF_POLL_ONE_CONNECT, DEFAULT_POLL_ONE_CONNECT),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
