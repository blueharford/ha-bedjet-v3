"""Climate platform for BedJet integration with connection state awareness."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .bedjet_device import BedJetDevice
from .const import (
    DOMAIN,
    MANUFACTURER,
    MAX_FAN_SPEED,
    MAX_TEMP,
    MIN_FAN_SPEED,
    MIN_TEMP,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Map BedJet modes to HVAC modes
BEDJET_MODE_TO_HVAC = {
    "off": HVACMode.OFF,
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "turbo": HVACMode.HEAT,
    "dry": HVACMode.DRY,
    "ext_ht": HVACMode.HEAT,
}

# Map HVAC modes back to BedJet modes (handle multiple mappings)
HVAC_MODE_TO_BEDJET = {
    HVACMode.OFF: "off",
    HVACMode.COOL: "cool",
    HVACMode.HEAT: "heat",  # Default to regular heat, not turbo
    HVACMode.DRY: "dry",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BedJet climate platform."""
    device: BedJetDevice = entry.runtime_data

    # Create update coordinator
    coordinator = BedJetUpdateCoordinator(hass, device)
    await coordinator.async_config_entry_first_refresh()

    async_add_entities([BedJetClimate(coordinator, device)], True)


class BedJetUpdateCoordinator(DataUpdateCoordinator):
    """Update coordinator for BedJet device with connection awareness."""

    def __init__(self, hass: HomeAssistant, device: BedJetDevice) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.device = device
        self._last_connected_state = device.is_connected

        # Register for connection state changes
        device.add_connection_callback(self._on_connection_change)

    def _on_connection_change(self, connected: bool) -> None:
        """Handle connection state changes.

        This is called by the BedJet device when connection state changes,
        allowing us to immediately update Home Assistant's entity state.
        """
        if connected != self._last_connected_state:
            self._last_connected_state = connected
            _LOGGER.info(
                "BedJet connection state changed: %s",
                "connected" if connected else "disconnected"
            )
            # Schedule an immediate refresh to update entity state
            self.hass.async_create_task(self.async_request_refresh())

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        try:
            await self.device.update()
            return {
                "current_temp": self.device.current_temperature,
                "target_temp": self.device.target_temperature,
                "mode": self.device.mode,
                "fan_speed": self.device.fan_speed,
                "time_remaining": self.device.time_remaining,
                "is_connected": self.device.is_connected,
                "reconnect_attempts": self.device.reconnect_attempts,
            }
        except Exception as err:
            _LOGGER.warning("Error updating BedJet data: %s", err)
            # Return partial data with connection state even on error
            # This allows the entity to show as unavailable while still
            # providing diagnostic information
            return {
                "current_temp": self.device.current_temperature,
                "target_temp": self.device.target_temperature,
                "mode": self.device.mode,
                "fan_speed": self.device.fan_speed,
                "time_remaining": self.device.time_remaining,
                "is_connected": self.device.is_connected,
                "reconnect_attempts": self.device.reconnect_attempts,
            }


class BedJetClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a BedJet climate device."""

    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = 1.0
    _attr_min_humidity = 0
    _attr_max_humidity = 100
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.HEAT,
        HVACMode.COOL,
        HVACMode.DRY,
    ]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: BedJetUpdateCoordinator, device: BedJetDevice
    ) -> None:
        """Initialize the climate device."""
        super().__init__(coordinator)
        self.device = device
        self._attr_unique_id = device.mac_address.replace(":", "").lower()
        self._attr_name = None  # Use device name from device_info
        self._last_hvac_mode = HVACMode.HEAT  # Remember last non-off mode

        # Set up device callback for real-time updates
        self.device.add_callback(self._handle_device_update)

        # Set up connection callback for availability updates
        self.device.add_connection_callback(self._handle_connection_change)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device.mac_address)},
            name=self.device.name or f"BedJet ({self.device.mac_address})",
            manufacturer=MANUFACTURER,
            model="BedJet V3",
            connections={("bluetooth", self.device.mac_address)},
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.device.is_connected

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.device.current_temperature

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self.device.target_temperature

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current operation mode."""
        mode = self.device.mode
        if mode in BEDJET_MODE_TO_HVAC:
            hvac_mode = BEDJET_MODE_TO_HVAC[mode]
            # Remember last non-off mode for turn_on functionality
            if hvac_mode != HVACMode.OFF:
                self._last_hvac_mode = hvac_mode
            return hvac_mode
        return HVACMode.OFF

    @property
    def fan_mode(self) -> str | None:
        """Return the fan setting."""
        if self.device.fan_speed is not None:
            return f"{self.device.fan_speed}%"
        return None

    @property
    def fan_modes(self) -> list[str]:
        """Return the list of available fan modes."""
        return [f"{speed}%" for speed in range(MIN_FAN_SPEED, MAX_FAN_SPEED + 1, 5)]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {}
        if self.device.time_remaining is not None:
            attrs["time_remaining"] = self.device.time_remaining
            # Also provide formatted time remaining
            hours = self.device.time_remaining // 3600
            minutes = (self.device.time_remaining % 3600) // 60
            seconds = self.device.time_remaining % 60
            if hours > 0:
                attrs["time_remaining_formatted"] = f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                attrs["time_remaining_formatted"] = f"{minutes}m {seconds}s"
            else:
                attrs["time_remaining_formatted"] = f"{seconds}s"

        # Add connection diagnostic info
        if self.device.reconnect_attempts > 0:
            attrs["reconnect_attempts"] = self.device.reconnect_attempts

        return attrs

    @callback
    def _handle_device_update(self, data: dict[str, Any]) -> None:
        """Handle device state update from BLE notifications."""
        self.async_write_ha_state()

    @callback
    def _handle_connection_change(self, connected: bool) -> None:
        """Handle connection state change."""
        _LOGGER.debug(
            "BedJet climate entity received connection change: %s",
            "connected" if connected else "disconnected"
        )
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        try:
            await self.device.set_temperature(temperature)
            # Give the device time to process the command
            await asyncio.sleep(0.5)
            # Force an update to get the new state
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to set temperature: %s", err)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode not in HVAC_MODE_TO_BEDJET:
            _LOGGER.error("Unsupported HVAC mode: %s", hvac_mode)
            return

        bedjet_mode = HVAC_MODE_TO_BEDJET[hvac_mode]
        try:
            await self.device.set_mode(bedjet_mode)
            # Give the device time to process the command
            await asyncio.sleep(0.5)
            # Force an update to get the new state
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to set HVAC mode: %s", err)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        try:
            # Extract percentage from string like "50%"
            speed = int(fan_mode.rstrip("%"))
            await self.device.set_fan_speed(speed)
            # Give the device time to process the command
            await asyncio.sleep(0.5)
            # Force an update to get the new state
            await self.coordinator.async_request_refresh()
        except (ValueError, AttributeError) as err:
            _LOGGER.error("Invalid fan mode %s: %s", fan_mode, err)
        except Exception as err:
            _LOGGER.error("Failed to set fan mode: %s", err)

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        try:
            # Turn on using the last known mode (or default to heat)
            await self.device.set_mode(
                HVAC_MODE_TO_BEDJET.get(self._last_hvac_mode, "heat")
            )
            # Give the device time to process the command
            await asyncio.sleep(0.5)
            # Force an update to get the new state
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to turn on BedJet: %s", err)

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        try:
            await self.device.set_mode("off")
            # Give the device time to process the command
            await asyncio.sleep(0.5)
            # Force an update to get the new state
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to turn off BedJet: %s", err)

    async def async_will_remove_from_hass(self) -> None:
        """Remove device callbacks when entity is removed."""
        self.device.remove_callback(self._handle_device_update)
        self.device.remove_connection_callback(self._handle_connection_change)
        await super().async_will_remove_from_hass()
