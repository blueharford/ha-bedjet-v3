"""Climate platform for BedJet integration."""
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
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

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

HVAC_MODE_TO_BEDJET = {v: k for k, v in BEDJET_MODE_TO_HVAC.items()}

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
    """Update coordinator for BedJet device."""

    def __init__(self, hass: HomeAssistant, device: BedJetDevice) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.device = device

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
            }
        except Exception as err:
            _LOGGER.error("Error updating data: %s", err)
            raise

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
    )

    def __init__(self, coordinator: BedJetUpdateCoordinator, device: BedJetDevice) -> None:
        """Initialize the climate device."""
        super().__init__(coordinator)
        self.device = device
        self._attr_unique_id = device.mac_address.replace(":", "").lower()
        self._attr_name = device.name or f"BedJet ({device.mac_address})"
        
        # Set up device callback
        self.device.add_callback(self._handle_device_update)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device.mac_address)},
            name=self._attr_name,
            manufacturer=MANUFACTURER,
            model="BedJet V3",
            connections={("bluetooth", self.device.mac_address)},
        )

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
            return BEDJET_MODE_TO_HVAC[mode]
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
        attrs = {}
        if self.device.time_remaining is not None:
            attrs["time_remaining"] = self.device.time_remaining
        return attrs

    @callback
    def _handle_device_update(self, data: dict[str, Any]) -> None:
        """Handle device state update."""
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        
        try:
            await self.device.set_temperature(temperature)
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
        except Exception as err:
            _LOGGER.error("Failed to set HVAC mode: %s", err)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        try:
            # Extract percentage from string like "50%"
            speed = int(fan_mode.rstrip("%"))
            await self.device.set_fan_speed(speed)
        except (ValueError, AttributeError) as err:
            _LOGGER.error("Invalid fan mode %s: %s", fan_mode, err)
        except Exception as err:
            _LOGGER.error("Failed to set fan mode: %s", err)

    async def async_will_remove_from_hass(self) -> None:
        """Remove device callback when entity is removed."""
        self.device.remove_callback(self._handle_device_update)
