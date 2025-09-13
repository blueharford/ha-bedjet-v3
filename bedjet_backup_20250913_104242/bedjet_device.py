"""BedJet device communication handler."""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any, Callable

from bleak import BleakClient, BleakError
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from .const import (
    BEDJET_COMMAND_UUID,
    BEDJET_NAME_UUID,
    BEDJET_STATUS_UUID,
    BedJetMode,
    MAX_FAN_SPEED,
    MAX_TEMP,
    MIN_FAN_SPEED,
    MIN_TEMP,
    MODE_MAP,
    FAN_STEP,
    REVERSE_MODE_MAP,
)

_LOGGER = logging.getLogger(__name__)

class BedJetDevice:
    """Representation of a BedJet device."""

    def __init__(self, ble_device: BLEDevice) -> None:
        """Initialize the BedJet device."""
        self.ble_device = ble_device
        self.client: BleakClient | None = None
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._lock = asyncio.Lock()
        
        # State variables
        self._name: str | None = None
        self._current_temp: float | None = None
        self._target_temp: float | None = None
        self._mode: str | None = None
        self._fan_speed: int | None = None
        self._time_remaining: int | None = None
        self._connected = False

    @property
    def name(self) -> str | None:
        """Return the device name."""
        return self._name

    @property
    def mac_address(self) -> str:
        """Return the MAC address."""
        return self.ble_device.address

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._current_temp

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self._target_temp

    @property
    def mode(self) -> str | None:
        """Return the current mode."""
        return self._mode

    @property
    def fan_speed(self) -> int | None:
        """Return the current fan speed percentage."""
        return self._fan_speed

    @property
    def time_remaining(self) -> int | None:
        """Return the time remaining in seconds."""
        return self._time_remaining

    @property
    def is_connected(self) -> bool:
        """Return True if connected."""
        return self._connected and self.client is not None and self.client.is_connected

    def add_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Add a callback for state updates."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Remove a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify_callbacks(self) -> None:
        """Notify all callbacks of state change."""
        data = {
            "current_temp": self._current_temp,
            "target_temp": self._target_temp,
            "mode": self._mode,
            "fan_speed": self._fan_speed,
            "time_remaining": self._time_remaining,
        }
        for callback in self._callbacks:
            try:
                callback(data)
            except Exception as err:
                _LOGGER.exception("Error in callback: %s", err)

    async def connect(self) -> None:
        """Connect to the BedJet device."""
        async with self._lock:
            try:
                self.client = await establish_connection(
                    BleakClient, self.ble_device, self.ble_device.address
                )
                
                # Subscribe to status notifications
                await self.client.start_notify(BEDJET_STATUS_UUID, self._handle_status_update)
                
                # Read device name
                try:
                    name_data = await self.client.read_gatt_char(BEDJET_NAME_UUID)
                    self._name = name_data.decode("utf-8").strip()
                except Exception as err:
                    _LOGGER.warning("Could not read device name: %s", err)
                    self._name = f"BedJet ({self.ble_device.address})"
                
                self._connected = True
                _LOGGER.info("Connected to BedJet %s", self._name)
                
            except Exception as err:
                _LOGGER.error("Failed to connect to BedJet: %s", err)
                self._connected = False
                raise

    async def disconnect(self) -> None:
        """Disconnect from the BedJet device."""
        async with self._lock:
            if self.client and self.client.is_connected:
                try:
                    await self.client.stop_notify(BEDJET_STATUS_UUID)
                    await self.client.disconnect()
                except Exception as err:
                    _LOGGER.warning("Error disconnecting: %s", err)
                finally:
                    self._connected = False
                    self.client = None

    def _handle_status_update(self, handle: int, data: bytearray) -> None:
        """Handle status update from BedJet."""
        try:
            if len(data) >= 15:
                # Parse temperature data (bytes 7 and 8)
                # Temperature formula: ((byte - 0x26) + 66) - ((byte - 0x26) / 9)
                if data[7] != 0:
                    raw_current = data[7] - 0x26
                    self._current_temp = round((raw_current + 66) - (raw_current / 9))
                
                if data[8] != 0:
                    raw_target = data[8] - 0x26
                    self._target_temp = round((raw_target + 66) - (raw_target / 9))
                
                # Parse time remaining (bytes 4, 5, 6 for hours, minutes, seconds)
                self._time_remaining = (data[4] * 3600) + (data[5] * 60) + data[6]
                
                # Parse fan speed (byte 10, multiply by 5 for percentage)
                self._fan_speed = data[10] * FAN_STEP
                
                # Parse mode (bytes 13 and 14)
                if len(data) >= 15:
                    if data[14] == 0x50 and data[13] == 0x14:
                        self._mode = "off"
                    elif data[14] == 0x34:
                        self._mode = "cool"
                    elif data[14] == 0x56:
                        self._mode = "turbo"
                    elif data[14] == 0x50 and data[13] == 0x2d:
                        self._mode = "heat"
                    elif data[14] == 0x3e:
                        self._mode = "dry"
                    elif data[14] == 0x43:
                        self._mode = "ext_ht"
                
                self._notify_callbacks()
                
        except Exception as err:
            _LOGGER.error("Error parsing status data: %s", err)

    async def update(self) -> None:
        """Update device state by requesting current status."""
        if not self.is_connected:
            await self.connect()

    async def _send_command(self, command: list[int]) -> None:
        """Send a command to the BedJet."""
        if not self.is_connected:
            raise BleakError("Device not connected")
        
        try:
            await self.client.write_gatt_char(BEDJET_COMMAND_UUID, bytearray(command))
        except Exception as err:
            _LOGGER.error("Failed to send command %s: %s", command, err)
            raise

    async def set_mode(self, mode: str) -> None:
        """Set the BedJet mode."""
        if mode not in REVERSE_MODE_MAP:
            raise ValueError(f"Invalid mode: {mode}")
        
        mode_byte = REVERSE_MODE_MAP[mode]
        await self._send_command([0x01, mode_byte])

    async def set_temperature(self, temperature: float) -> None:
        """Set the target temperature."""
        if not MIN_TEMP <= temperature <= MAX_TEMP:
            raise ValueError(f"Temperature {temperature} out of range {MIN_TEMP}-{MAX_TEMP}")
        
        # Convert temperature to BedJet format
        temp_byte = int((temperature - 60) / 9) + (temperature - 66) + 0x26
        await self._send_command([0x03, temp_byte])

    async def set_fan_speed(self, speed: int) -> None:
        """Set the fan speed percentage."""
        if not MIN_FAN_SPEED <= speed <= MAX_FAN_SPEED:
            raise ValueError(f"Fan speed {speed} out of range {MIN_FAN_SPEED}-{MAX_FAN_SPEED}")
        
        # Convert percentage to BedJet format
        fan_byte = round(speed / FAN_STEP) - 1
        await self._send_command([0x07, fan_byte])

    async def set_timer(self, minutes: int) -> None:
        """Set the timer in minutes."""
        if minutes < 0 or minutes > 600:  # Max 10 hours
            raise ValueError(f"Timer {minutes} out of range 0-600")
        
        hours = minutes // 60
        mins = minutes % 60
        await self._send_command([0x02, hours, mins])

    async def activate_preset(self, preset: int) -> None:
        """Activate a memory preset (1, 2, or 3)."""
        if preset not in [1, 2, 3]:
            raise ValueError(f"Invalid preset: {preset}")
        
        preset_byte = BedJetPreset.M1 + (preset - 1)
        await self._send_command([0x01, preset_byte])
