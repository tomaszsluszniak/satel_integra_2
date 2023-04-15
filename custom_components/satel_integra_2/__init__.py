"""Support for Satel Integra devices."""

import collections
import logging

from satel_integra.satel_integra import AsyncSatel
import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

DEFAULT_ALARM_NAME = "satel_integra_2"
DEFAULT_PORT = 7094
DEFAULT_CONF_ARM_HOME_MODE = 1
DEFAULT_DEVICE_ZONE = 1
DEFAULT_INPUT_TYPE = "motion"

_LOGGER = logging.getLogger(__name__)

DOMAIN = "satel_integra"

DATA_SATEL = "satel_integra"

CONF_DEVICE_CODE = "code"
CONF_PARTITIONS = "partitions"
CONF_ZONES = "zones"
CONF_ARM_HOME_MODE = "arm_home_mode"
CONF_INPUT_NAME = "name"
CONF_INPUT_TYPE = "type"
CONF_INPUTS = "inputs"
CONF_OUTPUTS = "outputs"
CONF_SWITCHABLE_OUTPUTS = "switchable_outputs"

INPUTS = "inputs"

SIGNAL_PANEL_MESSAGE = f"{DOMAIN}.panel_message"
SIGNAL_PANEL_ARM_AWAY = f"{DOMAIN}.panel_arm_away"
SIGNAL_PANEL_ARM_HOME = f"{DOMAIN}.panel_arm_home"
SIGNAL_PANEL_DISARM = f"{DOMAIN}.panel_disarm"

SIGNAL_ZONES_UPDATED = f"{DOMAIN}.zones_updated"
SIGNAL_OUTPUTS_UPDATED = f"{DOMAIN}.outputs_updated"

INPUT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_INPUT_NAME): cv.string,
        vol.Optional(CONF_INPUT_TYPE, default=DEFAULT_INPUT_TYPE): cv.string,
    }
)
EDITABLE_OUTPUT_SCHEMA = vol.Schema({vol.Required(CONF_INPUT_NAME): cv.string})

ZONE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_INPUT_NAME): cv.string,
        vol.Optional(CONF_INPUTS, default={}): {vol.Coerce(int): INPUT_SCHEMA},
        vol.Optional(CONF_OUTPUTS, default={}): {vol.Coerce(int): INPUT_SCHEMA},
        vol.Optional(CONF_SWITCHABLE_OUTPUTS, default={}): {
            vol.Coerce(int): EDITABLE_OUTPUT_SCHEMA
        },
    }
)

PARTITION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_INPUT_NAME): cv.string,
        vol.Optional(CONF_ARM_HOME_MODE, default=DEFAULT_CONF_ARM_HOME_MODE): vol.In(
            [0, 1, 2, 3]
        ),
        vol.Optional(CONF_ZONES, default={}): {vol.Coerce(int): ZONE_SCHEMA}
    }
)


def is_alarm_code_necessary(value):
    """Check if alarm code must be configured."""
    if value.get(CONF_SWITCHABLE_OUTPUTS) and CONF_DEVICE_CODE not in value:
        raise vol.Invalid("You need to specify alarm code to use switchable_outputs")

    return value


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
                vol.Optional(CONF_DEVICE_CODE): cv.string,
                vol.Required(CONF_PARTITIONS, default={}): {
                    vol.Coerce(int): PARTITION_SCHEMA
                }                
            },
            is_alarm_code_necessary,
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Satel Integra component."""
    conf = config[DOMAIN]
    host = conf.get(CONF_HOST)
    port = conf.get(CONF_PORT)
    partitions = conf.get(CONF_PARTITIONS)

    @callback
    def alarm_status_update_callback():
        """Send status update received from alarm to Home Assistant."""
        _LOGGER.debug("Sending request to update panel state")
        async_dispatcher_send(hass, SIGNAL_PANEL_MESSAGE)

    @callback
    def inputs_update_callback(status):
        """Update input objects as per notification from the alarm."""
        _LOGGER.debug("Inputs callback, status: %s", status)
        async_dispatcher_send(hass, SIGNAL_ZONES_UPDATED, status[INPUTS])

    @callback
    def outputs_update_callback(status):
        """Update zone objects as per notification from the alarm."""
        _LOGGER.debug("Outputs updated callback , status: %s", status)
        async_dispatcher_send(hass, SIGNAL_OUTPUTS_UPDATED, status[CONF_OUTPUTS])

    for partition_id in partitions.keys():
        partition = partitions[partition_id]

        zones = partition.get(CONF_ZONES)

        inputs = partition.get(CONF_INPUTS)
        outputs = partition.get(CONF_OUTPUTS)
        switchable_outputs = partition.get(CONF_SWITCHABLE_OUTPUTS)

        monitored_outputs = collections.OrderedDict(
            list(outputs.items()) + list(switchable_outputs.items())
        )

        controller = AsyncSatel(host, port, hass.loop, inputs, monitored_outputs, zones)

        hass.data[f"{DATA_SATEL}_partition_{partition_id}"] = controller

        result = await controller.connect()

        if not result:
            return False

        @callback
        def _close(*_):
            controller.close()

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _close)

        _LOGGER.debug("Arm home config: %s, mode: %s ", conf, conf.get(CONF_ARM_HOME_MODE))

        hass.async_create_task(
            async_load_platform(hass, Platform.ALARM_CONTROL_PANEL, DOMAIN, conf, config)
        )

        hass.async_create_task(
            async_load_platform(
                hass,
                Platform.BINARY_SENSOR,
                DOMAIN,
                {CONF_INPUTS: inputs, CONF_OUTPUTS: outputs},
                config,
            )
        )

        hass.async_create_task(
            async_load_platform(
                hass,
                Platform.SWITCH,
                DOMAIN,
                {
                    CONF_SWITCHABLE_OUTPUTS: switchable_outputs,
                    CONF_DEVICE_CODE: conf.get(CONF_DEVICE_CODE),
                },
                config,
            )
        )

        # Create a task instead of adding a tracking job, since this task will
        # run until the connection to satel_integra is closed.
        hass.loop.create_task(controller.keep_alive())
        hass.loop.create_task(
            controller.monitor_status(
                alarm_status_update_callback, inputs_update_callback, outputs_update_callback
            )
        )
        return True