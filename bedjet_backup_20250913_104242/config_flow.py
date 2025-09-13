"""Config flow for BedJet integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_MAC

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class BedJetConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BedJet."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_device: dict[str, Any] | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        
        self._discovery_info = discovery_info
        self._discovered_device = {
            "name": discovery_info.advertisement.local_name or discovery_info.name,
            "mac": discovery_info.address,
        }
        
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_device["name"],
                data={CONF_MAC: self._discovered_device["mac"]},
            )

        placeholders = {"name": self._discovered_device["name"]}
        self.context["title_placeholders"] = placeholders

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders=placeholders,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mac_address = user_input[CONF_MAC]
            await self.async_set_unique_id(mac_address)
            self._abort_if_unique_id_configured()

            # Try to find the device
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, mac_address.upper(), connectable=True
            )
            
            if not ble_device:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"BedJet ({mac_address})",
                    data={CONF_MAC: mac_address},
                )

        # Show discovered devices
        current_addresses = self._async_current_ids()
        discovered_devices = []
        
        for discovery_info in async_discovered_service_info(self.hass):
            if (
                discovery_info.address in current_addresses
                or not discovery_info.advertisement.local_name
                or not discovery_info.advertisement.local_name.startswith("BEDJET")
            ):
                continue
            
            discovered_devices.append(
                f"{discovery_info.advertisement.local_name} ({discovery_info.address})"
            )

        data_schema = vol.Schema({vol.Required(CONF_MAC): str})
        
        if discovered_devices:
            data_schema = vol.Schema({
                vol.Required(CONF_MAC): vol.In(
                    {device.split("(")[1].rstrip(")"): device for device in discovered_devices}
                )
            })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )
