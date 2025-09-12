"""The BedJet integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .bedjet_device import BedJetDevice
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE]

type BedJetConfigEntry = ConfigEntry[BedJetDevice]

async def async_setup_entry(hass: HomeAssistant, entry: BedJetConfigEntry) -> bool:
    """Set up BedJet from a config entry."""
    mac_address = entry.data[CONF_MAC]
    
    # Find the Bluetooth device
    ble_device = bluetooth.async_ble_device_from_address(
        hass, mac_address.upper(), connectable=True
    )
    
    if not ble_device:
        raise ConfigEntryNotReady(
            f"Could not find BedJet device with address {mac_address}"
        )
    
    # Create the device instance
    device = BedJetDevice(ble_device)
    
    try:
        await device.connect()
        await device.update()
    except Exception as err:
        raise ConfigEntryNotReady(f"Failed to connect to BedJet: {err}") from err
    
    entry.runtime_data = device
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: BedJetConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.disconnect()
    
    return unload_ok
