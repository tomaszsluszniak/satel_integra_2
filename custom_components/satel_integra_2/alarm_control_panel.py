"""Support for Satel Integra alarm, using ETHM module."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import logging

from satel_integra.satel_integra import AlarmState

import homeassistant.components.alarm_control_panel as alarm
from homeassistant.components.alarm_control_panel import AlarmControlPanelEntityFeature
from homeassistant.const import (
    STATE_ALARM_ARMED_AWAY,
    STATE_ALARM_ARMED_HOME,
    STATE_ALARM_DISARMED,
    STATE_ALARM_PENDING,
    STATE_ALARM_TRIGGERED,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import (
    CONF_ARM_HOME_MODE,
    CONF_ZONES,
    CONF_PARTITIONS,
    CONF_INPUT_NAME,
    DATA_SATEL,
    SIGNAL_PANEL_MESSAGE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up for Satel Integra alarm panels."""
    if not discovery_info:
        return

    configured_partitions = discovery_info[CONF_PARTITIONS]
    
    devices = []

    for partition_id, device_config_data in configured_partitions.items():
        controller = hass.data[f"{DATA_SATEL}_partition_{partition_id}"]

        partition_name = device_config_data[CONF_INPUT_NAME]
        arm_home_mode = device_config_data.get(CONF_ARM_HOME_MODE)
        zones = [int(z) for z in device_config_data.get(CONF_ZONES).keys()]

        device = SatelIntegraAlarmPanel(
            controller, partition_name, arm_home_mode, partition_id, zones
        )
        devices.append(device)

    async_add_entities(devices)


class SatelIntegraAlarmPanel(alarm.AlarmControlPanelEntity):
    """Representation of an AlarmDecoder-based alarm panel."""

    _attr_code_format = alarm.CodeFormat.NUMBER
    _attr_should_poll = False
    _attr_state: str | None
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
    )

    def __init__(self, controller, name, arm_home_mode, partition_id, zones):
        """Initialize the alarm panel."""
        self._attr_name = name
        self._arm_home_mode = arm_home_mode
        self._partition_id = partition_id
        self._satel = controller
        self.zones = zones

    async def async_added_to_hass(self) -> None:
        """Update alarm status and register callbacks for future updates."""
        _LOGGER.debug("Starts listening for panel messages")
        self._update_alarm_status()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_PANEL_MESSAGE, self._update_alarm_status
            )
        )

    @callback
    def _update_alarm_status(self):
        """Handle alarm status update."""
        state = self._read_alarm_state()
        _LOGGER.debug("Got status update, current status: %s", state)
        if state != self._attr_state:
            self._attr_state = state
            self.async_write_ha_state()
        else:
            _LOGGER.debug("Ignoring alarm status message, same state")

    def _read_alarm_state(self):
        """Read current status of the alarm and translate it into HA status."""

        if not self._satel.connected:
            return None

        _LOGGER.debug("State map of Satel: %s", self._satel.partition_states)

        TRIGGERED_STATES = [AlarmState.TRIGGERED, AlarmState.TRIGGERED_FIRE]
        for _state in TRIGGERED_STATES:
            if (any(zone in self._satel.partition_states.get(_state, []) for zone in self.zones)):
                return STATE_ALARM_TRIGGERED
            
        COUNTDOWN_STATES = [AlarmState.ENTRY_TIME, AlarmState.EXIT_COUNTDOWN_OVER_10, AlarmState.EXIT_COUNTDOWN_UNDER_10]
        for _state in COUNTDOWN_STATES:
            if (any(zone in self._satel.partition_states.get(_state, []) for zone in self.zones)):
                return STATE_ALARM_PENDING
        
        ARMED_HOME_STATES = [AlarmState.ARMED_MODE1, AlarmState.ARMED_MODE2, AlarmState.ARMED_MODE3]
        for _state in ARMED_HOME_STATES:
            if (any(zone in self._satel.partition_states.get(_state, []) for zone in self.zones)):
                return STATE_ALARM_ARMED_HOME
            
        if (any(zone in self._satel.partition_states.get(AlarmState.ARMED_MODE0, []) for zone in self.zones)):
            return STATE_ALARM_ARMED_AWAY
        
        return STATE_ALARM_DISARMED

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        if not code:
            _LOGGER.debug("Code was empty or None")
            return

        clear_alarm_necessary = self._attr_state == STATE_ALARM_TRIGGERED

        _LOGGER.debug("Disarming, self._attr_state: %s", self._attr_state)

        await self._satel.disarm(code, self.zones)

        if clear_alarm_necessary:
            # Wait 1s before clearing the alarm
            await asyncio.sleep(1)
            await self._satel.clear_alarm(code, self.zones)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""
        _LOGGER.debug("Arming away")

        if code:
            await self._satel.arm(code, self.zones)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""
        _LOGGER.debug("Arming home")

        if code:
            await self._satel.arm(code, self.zones, self._arm_home_mode)