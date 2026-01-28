"""The BedJet integration with persistent connection management."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .bedjet_device import BedJetDevice
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE]

type BedJetConfigEntry = ConfigEntry[BedJetDevice]


async def async_setup_entry(hass: HomeAssistant, entry: BedJetConfigEntry) -> bool:
    """Set up BedJet from a config entry."""
    mac_address = entry.data[CONF_MAC]

    def get_ble_device() -> bluetooth.BLEDevice | None:
        """Get fresh BLE device reference from Home Assistant.

        This callback is used by the BedJet device to refresh its BLE device
        reference when attempting to reconnect after a disconnection.
        """
        return bluetooth.async_ble_device_from_address(
            hass, mac_address.upper(), connectable=True
        )

    # Find the Bluetooth device
    ble_device = get_ble_device()

    if not ble_device:
        raise ConfigEntryNotReady(
            f"Could not find BedJet device with address {mac_address}"
        )

    # Create the device instance with BLE refresh callback
    device = BedJetDevice(ble_device, ble_device_callback=get_ble_device)

    try:
        await device.connect()
        await device.update()
    except Exception as err:
        raise ConfigEntryNotReady(f"Failed to connect to BedJet: {err}") from err

    # Start the connection watchdog to maintain persistent connection
    device.start_watchdog()

    entry.runtime_data = device

    # Register callback to handle BLE device updates from Home Assistant
    @callback
    def _async_update_ble_device(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Handle BLE device updates from Home Assistant's Bluetooth integration."""
        if service_info.address.upper() == mac_address.upper():
            device.update_ble_device(service_info.device)
            _LOGGER.debug(
                "Updated BLE device reference for %s from Bluetooth callback",
                mac_address
            )

    # Register for Bluetooth updates for this device
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble_device,
            bluetooth.BluetoothCallbackMatcher(address=mac_address.upper()),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    # Clean up on Home Assistant stop
    async def _async_on_hass_stop(event: Event) -> None:
        """Handle Home Assistant stopping."""
        await device.disconnect()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_on_hass_stop)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: BedJetConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.disconnect()

    return unload_ok
