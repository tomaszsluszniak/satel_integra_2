"""Support for Satel Integra zone states- represented as binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from slugify import slugify

from . import (
    CONF_OUTPUTS,
    CONF_INPUT_NAME,
    CONF_INPUT_TYPE,
    CONF_INPUTS,
    DATA_SATEL,
    SIGNAL_OUTPUTS_UPDATED,
    SIGNAL_ZONES_UPDATED,
    CONF_PARTITION,
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Satel Integra binary sensor devices."""
    if not discovery_info:
        return

    configured_zones = discovery_info[CONF_INPUTS]
    partition_id = discovery_info[CONF_PARTITION]
    controller = hass.data[f"{DATA_SATEL}_partition_{partition_id}"]

    devices = []

    for input_num, device_config_data in configured_zones.items():
        input_type = device_config_data[CONF_INPUT_TYPE]
        input_name = device_config_data[CONF_INPUT_NAME]
        input_unique_id = slugify(f"partition_{partition_id}_{device_config_data[CONF_INPUT_NAME]}", separator="_")
        device = SatelIntegraBinarySensor(
            controller, input_num, input_unique_id, input_name, input_type, SIGNAL_ZONES_UPDATED
        )
        devices.append(device)

    configured_outputs = discovery_info[CONF_OUTPUTS]

    for input_num, device_config_data in configured_outputs.items():
        input_type = device_config_data[CONF_INPUT_TYPE]
        input_name = device_config_data[CONF_INPUT_NAME]
        input_unique_id = slugify(f"partition_{partition_id}_{device_config_data[CONF_INPUT_NAME]}", separator="_")
        device = SatelIntegraBinarySensor(
            controller, input_num, input_unique_id, input_name, input_type, SIGNAL_OUTPUTS_UPDATED
        )
        devices.append(device)

    async_add_entities(devices)


class SatelIntegraBinarySensor(BinarySensorEntity):
    """Representation of an Satel Integra binary sensor."""

    _attr_should_poll = False

    def __init__(
        self, controller, device_number, attr_unique_id, device_name, input_type, react_to_signal
    ):
        """Initialize the binary_sensor."""
        self._device_number = device_number
        self._attr_unique_id = attr_unique_id
        self._name = device_name
        self._input_type = input_type
        self._state = 0
        self._react_to_signal = react_to_signal
        self._satel = controller

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        if self._react_to_signal == SIGNAL_OUTPUTS_UPDATED:
            if self._device_number in self._satel.violated_outputs:
                self._state = 1
            else:
                self._state = 0
        else:
            if self._device_number in self._satel.violated_zones:
                self._state = 1
            else:
                self._state = 0
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._react_to_signal, self._devices_updated
            )
        )

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    @property
    def icon(self):
        """Icon for device by its type."""
        if self._input_type is BinarySensorDeviceClass.SMOKE:
            return "mdi:fire"

    @property
    def is_on(self):
        """Return true if sensor is on."""
        return self._state == 1

    @property
    def device_class(self):
        """Return the class of this sensor, from DEVICE_CLASSES."""
        return self._input_type

    @callback
    def _devices_updated(self, inputs):
        """Update the zone's state, if needed."""
        if self._device_number in inputs and self._state != inputs[self._device_number]:
            self._state = inputs[self._device_number]
            self.async_write_ha_state()