"""BedJet device communication handler with persistent connection management."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from bleak import BleakClient, BleakError
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection, BleakNotFoundError

from .const import (
    BEDJET_COMMAND_UUID,
    BEDJET_NAME_UUID,
    BEDJET_STATUS_UUID,
    BedJetMode,
    BedJetPreset,
    CONNECTION_TIMEOUT,
    CONNECTION_WATCHDOG_INTERVAL,
    MAX_FAN_SPEED,
    MAX_TEMP,
    MIN_FAN_SPEED,
    MIN_TEMP,
    MODE_MAP,
    FAN_STEP,
    RECONNECT_INTERVAL_BASE,
    RECONNECT_INTERVAL_MAX,
    RECONNECT_MAX_ATTEMPTS,
    REVERSE_MODE_MAP,
)

_LOGGER = logging.getLogger(__name__)


class BedJetDevice:
    """Representation of a BedJet device with persistent connection management.

    This class implements aggressive connection retention to ensure Home Assistant
    maintains control of the BedJet device even when other clients (like the phone app)
    attempt to connect. BLE devices typically only allow one connection at a time,
    so this implementation:

    1. Detects disconnections immediately via Bleak callback
    2. Automatically attempts to reconnect with exponential backoff
    3. Runs a watchdog task to verify and restore connections
    4. Provides connection state callbacks to notify Home Assistant
    """

    def __init__(
        self,
        ble_device: BLEDevice,
        ble_device_callback: Callable[[], BLEDevice | None] | None = None,
    ) -> None:
        """Initialize the BedJet device.

        Args:
            ble_device: The initial BLE device from Home Assistant's Bluetooth integration.
            ble_device_callback: Optional callback to get fresh BLE device reference.
                                This is useful when the device address changes or
                                Home Assistant needs to refresh the device handle.
        """
        self.ble_device = ble_device
        self._ble_device_callback = ble_device_callback
        self.client: BleakClient | None = None
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._connection_callbacks: list[Callable[[bool], None]] = []
        self._lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()

        # State variables
        self._name: str | None = None
        self._current_temp: float | None = None
        self._target_temp: float | None = None
        self._mode: str | None = None
        self._fan_speed: int | None = None
        self._time_remaining: int | None = None
        self._connected = False

        # Reconnection management
        self._reconnect_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._reconnect_attempts = 0
        self._should_reconnect = True
        self._last_disconnect_reason: str | None = None
        self._shutting_down = False

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

    @property
    def reconnect_attempts(self) -> int:
        """Return the number of reconnection attempts since last successful connection."""
        return self._reconnect_attempts

    def add_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Add a callback for state updates."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Remove a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def add_connection_callback(self, callback: Callable[[bool], None]) -> None:
        """Add a callback for connection state changes.

        The callback receives True when connected, False when disconnected.
        """
        self._connection_callbacks.append(callback)

    def remove_connection_callback(self, callback: Callable[[bool], None]) -> None:
        """Remove a connection callback."""
        if callback in self._connection_callbacks:
            self._connection_callbacks.remove(callback)

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

    def _notify_connection_callbacks(self, connected: bool) -> None:
        """Notify all connection callbacks of state change."""
        for callback in self._connection_callbacks:
            try:
                callback(connected)
            except Exception as err:
                _LOGGER.exception("Error in connection callback: %s", err)

    def _on_disconnect(self, client: BleakClient) -> None:
        """Handle disconnection from the BedJet device.

        This callback is triggered by Bleak when the connection is lost,
        whether due to the device going out of range, another client
        (like the phone app) taking over, or any other disconnection reason.
        """
        self._connected = False
        self._last_disconnect_reason = "BLE disconnection detected"
        _LOGGER.warning(
            "BedJet %s disconnected (may have been taken over by another client)",
            self._name or self.ble_device.address
        )

        # Notify listeners of disconnection
        self._notify_connection_callbacks(False)

        # Schedule reconnection if we should still be connected
        if self._should_reconnect and not self._shutting_down:
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt."""
        if self._reconnect_task is not None and not self._reconnect_task.done():
            _LOGGER.debug("Reconnection already scheduled, skipping")
            return

        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Reconnection loop with exponential backoff.

        This loop will continuously attempt to reconnect to the BedJet device
        using exponential backoff. It will run until:
        1. A successful connection is established
        2. Maximum attempts reached (if configured)
        3. The device is being shut down
        """
        while self._should_reconnect and not self._shutting_down:
            # Calculate backoff delay
            delay = min(
                RECONNECT_INTERVAL_BASE * (2 ** self._reconnect_attempts),
                RECONNECT_INTERVAL_MAX
            )

            _LOGGER.info(
                "BedJet %s: Scheduling reconnection attempt %d in %d seconds",
                self._name or self.ble_device.address,
                self._reconnect_attempts + 1,
                delay
            )

            await asyncio.sleep(delay)

            if not self._should_reconnect or self._shutting_down:
                break

            self._reconnect_attempts += 1

            # Check max attempts
            if RECONNECT_MAX_ATTEMPTS > 0 and self._reconnect_attempts > RECONNECT_MAX_ATTEMPTS:
                _LOGGER.error(
                    "BedJet %s: Maximum reconnection attempts (%d) reached, giving up",
                    self._name or self.ble_device.address,
                    RECONNECT_MAX_ATTEMPTS
                )
                break

            try:
                # Refresh BLE device reference if callback is available
                if self._ble_device_callback:
                    fresh_device = self._ble_device_callback()
                    if fresh_device:
                        self.ble_device = fresh_device
                        _LOGGER.debug("Refreshed BLE device reference")

                await self.connect()
                _LOGGER.info(
                    "BedJet %s: Reconnection successful after %d attempts",
                    self._name or self.ble_device.address,
                    self._reconnect_attempts
                )
                self._reconnect_attempts = 0
                break

            except Exception as err:
                _LOGGER.warning(
                    "BedJet %s: Reconnection attempt %d failed: %s",
                    self._name or self.ble_device.address,
                    self._reconnect_attempts,
                    err
                )

    async def _watchdog_loop(self) -> None:
        """Connection watchdog loop.

        This loop periodically checks the connection state and triggers
        reconnection if needed. It serves as a backup to the disconnect
        callback in case a disconnection is not properly detected.
        """
        while not self._shutting_down:
            await asyncio.sleep(CONNECTION_WATCHDOG_INTERVAL)

            if self._shutting_down:
                break

            # Check if we think we're connected but actually aren't
            if self._connected and self.client is not None:
                try:
                    if not self.client.is_connected:
                        _LOGGER.warning(
                            "BedJet %s: Watchdog detected stale connection, triggering reconnect",
                            self._name or self.ble_device.address
                        )
                        self._connected = False
                        self._notify_connection_callbacks(False)
                        if self._should_reconnect:
                            self._schedule_reconnect()
                except Exception as err:
                    _LOGGER.debug("Watchdog connection check error: %s", err)

            # If we should be connected but aren't, and no reconnect is running
            elif (
                self._should_reconnect
                and not self._connected
                and (self._reconnect_task is None or self._reconnect_task.done())
            ):
                _LOGGER.debug(
                    "BedJet %s: Watchdog scheduling reconnection",
                    self._name or self.ble_device.address
                )
                self._schedule_reconnect()

    def start_watchdog(self) -> None:
        """Start the connection watchdog task."""
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            _LOGGER.debug("Connection watchdog started")

    def stop_watchdog(self) -> None:
        """Stop the connection watchdog task."""
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            self._watchdog_task = None
            _LOGGER.debug("Connection watchdog stopped")

    async def connect(self) -> None:
        """Connect to the BedJet device."""
        async with self._connect_lock:
            if self.is_connected:
                _LOGGER.debug("Already connected to BedJet")
                return

            async with self._lock:
                try:
                    _LOGGER.debug(
                        "Connecting to BedJet %s",
                        self._name or self.ble_device.address
                    )

                    # Clean up any existing client
                    if self.client is not None:
                        try:
                            await self.client.disconnect()
                        except Exception:
                            pass
                        self.client = None

                    # Establish connection with disconnect callback
                    self.client = await establish_connection(
                        BleakClient,
                        self.ble_device,
                        self.ble_device.address,
                        disconnected_callback=self._on_disconnect,
                        timeout=CONNECTION_TIMEOUT,
                    )

                    # Subscribe to status notifications
                    await self.client.start_notify(
                        BEDJET_STATUS_UUID, self._handle_status_update
                    )

                    # Read device name
                    try:
                        name_data = await self.client.read_gatt_char(BEDJET_NAME_UUID)
                        self._name = name_data.decode("utf-8").strip()
                    except Exception as err:
                        _LOGGER.warning("Could not read device name: %s", err)
                        if not self._name:
                            self._name = f"BedJet ({self.ble_device.address})"

                    self._connected = True
                    self._reconnect_attempts = 0
                    _LOGGER.info("Connected to BedJet %s", self._name)

                    # Notify listeners of connection
                    self._notify_connection_callbacks(True)

                except BleakNotFoundError as err:
                    _LOGGER.warning(
                        "BedJet device %s not found (may be out of range or connected to another device): %s",
                        self._name or self.ble_device.address,
                        err
                    )
                    self._connected = False
                    raise
                except Exception as err:
                    _LOGGER.error("Failed to connect to BedJet: %s", err)
                    self._connected = False
                    raise

    async def disconnect(self) -> None:
        """Disconnect from the BedJet device."""
        self._shutting_down = True
        self._should_reconnect = False

        # Stop watchdog and reconnection tasks
        self.stop_watchdog()
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        async with self._lock:
            if self.client:
                try:
                    if self.client.is_connected:
                        await self.client.stop_notify(BEDJET_STATUS_UUID)
                        await self.client.disconnect()
                except Exception as err:
                    _LOGGER.warning("Error disconnecting: %s", err)
                finally:
                    self._connected = False
                    self.client = None

        _LOGGER.info("Disconnected from BedJet %s", self._name or self.ble_device.address)

    def _handle_status_update(self, handle: int, data: bytearray) -> None:
        """Handle status update from BedJet."""
        try:
            if len(data) >= 15:
                _LOGGER.debug("Received status data: %s", data.hex())

                # Parse temperature data (bytes 7 and 8)
                # Temperature formula: ((byte - 0x26) + 66) - ((byte - 0x26) / 9)
                if data[7] != 0 and data[7] != 0x26:  # Valid current temp
                    raw_current = data[7] - 0x26
                    self._current_temp = round((raw_current + 66) - (raw_current / 9))
                    _LOGGER.debug(
                        "Current temp byte: 0x%02x -> %s°F", data[7], self._current_temp
                    )

                if data[8] != 0 and data[8] != 0x26:  # Valid target temp
                    raw_target = data[8] - 0x26
                    self._target_temp = round((raw_target + 66) - (raw_target / 9))
                    _LOGGER.debug(
                        "Target temp byte: 0x%02x -> %s°F", data[8], self._target_temp
                    )

                # Parse time remaining (bytes 4, 5, 6 for hours, minutes, seconds)
                self._time_remaining = (data[4] * 3600) + (data[5] * 60) + data[6]

                # Parse fan speed (byte 10, multiply by 5 for percentage)
                if data[10] > 0:
                    self._fan_speed = data[10] * FAN_STEP
                    _LOGGER.debug(
                        "Fan speed byte: 0x%02x -> %s%%", data[10], self._fan_speed
                    )

                # Parse mode (bytes 13 and 14)
                old_mode = self._mode
                if len(data) >= 15:
                    if data[14] == 0x50 and data[13] == 0x14:
                        self._mode = "off"
                    elif data[14] == 0x34:
                        self._mode = "cool"
                    elif data[14] == 0x56:
                        self._mode = "turbo"
                    elif data[14] == 0x50 and data[13] == 0x2D:
                        self._mode = "heat"
                    elif data[14] == 0x3E:
                        self._mode = "dry"
                    elif data[14] == 0x43:
                        self._mode = "ext_ht"
                    else:
                        _LOGGER.debug(
                            "Unknown mode bytes: 0x%02x 0x%02x", data[13], data[14]
                        )

                if self._mode != old_mode:
                    _LOGGER.debug("Mode changed from %s to %s", old_mode, self._mode)

                self._notify_callbacks()

        except Exception as err:
            _LOGGER.error("Error parsing status data: %s", err)

    async def update(self) -> None:
        """Update device state by requesting current status."""
        if not self.is_connected:
            await self.connect()

        # Request current status - this may trigger a status notification
        try:
            await self._send_command([0x01, 0x00])  # Status request
        except Exception as err:
            _LOGGER.debug(
                "Status request failed (this is normal for some devices): %s", err
            )

    async def _send_command(self, command: list[int]) -> None:
        """Send a command to the BedJet."""
        if not self.is_connected:
            raise BleakError("Device not connected")

        try:
            command_bytes = bytearray(command)
            _LOGGER.debug("Sending command: %s", command_bytes.hex())
            await self.client.write_gatt_char(BEDJET_COMMAND_UUID, command_bytes)

            # Wait a moment for the command to be processed
            await asyncio.sleep(0.3)

        except Exception as err:
            _LOGGER.error("Failed to send command %s: %s", command, err)
            raise

    async def _send_command_with_retry(self, command: list[int], retries: int = 2) -> None:
        """Send a command with automatic reconnection on failure.

        Args:
            command: The command bytes to send.
            retries: Number of retry attempts if command fails.
        """
        last_error = None
        for attempt in range(retries + 1):
            try:
                if not self.is_connected:
                    await self.connect()
                await self._send_command(command)
                return
            except Exception as err:
                last_error = err
                if attempt < retries:
                    _LOGGER.warning(
                        "Command failed (attempt %d/%d), retrying: %s",
                        attempt + 1,
                        retries + 1,
                        err
                    )
                    # Force reconnection on retry
                    self._connected = False
                    await asyncio.sleep(0.5)

        if last_error:
            raise last_error

    async def set_mode(self, mode: str) -> None:
        """Set the BedJet mode."""
        if mode not in REVERSE_MODE_MAP:
            raise ValueError(f"Invalid mode: {mode}")

        mode_byte = REVERSE_MODE_MAP[mode]
        await self._send_command_with_retry([0x01, mode_byte])

    async def set_temperature(self, temperature: float) -> None:
        """Set the target temperature."""
        if not MIN_TEMP <= temperature <= MAX_TEMP:
            raise ValueError(
                f"Temperature {temperature} out of range {MIN_TEMP}-{MAX_TEMP}"
            )

        # Convert temperature to BedJet format
        # Reverse engineering: temp_byte = ((temp - 66) + (temp - 66) / 9) + 0x26
        temp_offset = temperature - 66
        temp_byte = int(temp_offset + (temp_offset / 9) + 0x26)

        # Ensure byte is in valid range
        temp_byte = max(0, min(255, temp_byte))

        _LOGGER.debug(
            "Setting temperature %s°F (byte: 0x%02x)", temperature, temp_byte
        )
        await self._send_command_with_retry([0x03, temp_byte])

    async def set_fan_speed(self, speed: int) -> None:
        """Set the fan speed percentage."""
        if not MIN_FAN_SPEED <= speed <= MAX_FAN_SPEED:
            raise ValueError(
                f"Fan speed {speed} out of range {MIN_FAN_SPEED}-{MAX_FAN_SPEED}"
            )

        # Convert percentage to BedJet format
        fan_byte = round(speed / FAN_STEP) - 1
        await self._send_command_with_retry([0x07, fan_byte])

    async def set_timer(self, minutes: int) -> None:
        """Set the timer in minutes."""
        if minutes < 0 or minutes > 600:  # Max 10 hours
            raise ValueError(f"Timer {minutes} out of range 0-600")

        hours = minutes // 60
        mins = minutes % 60
        await self._send_command_with_retry([0x02, hours, mins])

    async def activate_preset(self, preset: int) -> None:
        """Activate a memory preset (1, 2, or 3)."""
        if preset not in [1, 2, 3]:
            raise ValueError(f"Invalid preset: {preset}")

        preset_byte = BedJetPreset.M1 + (preset - 1)
        await self._send_command_with_retry([0x01, preset_byte])

    def update_ble_device(self, ble_device: BLEDevice) -> None:
        """Update the BLE device reference.

        This should be called when Home Assistant detects the device
        with a fresh BLE device handle.
        """
        self.ble_device = ble_device
        _LOGGER.debug("BLE device reference updated for %s", self._name or ble_device.address)
