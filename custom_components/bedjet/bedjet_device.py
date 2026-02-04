"""BedJet device communication handler with persistent connection management."""
from __future__ import annotations

import asyncio
import logging
import time
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

# Minimum time between connection attempts to avoid hammering the adapter
MIN_TIME_BETWEEN_CONNECTIONS = 10.0  # seconds


class BedJetDevice:
    """Representation of a BedJet device with persistent connection management.

    This class implements connection management to maintain the Home Assistant
    connection with the BedJet device. BLE devices only allow one connection,
    so when another client (like the phone app) connects, this implementation
    will wait and reconnect when available.

    Connection strategy:
    1. Detect disconnections via Bleak callback
    2. Wait with exponential backoff before attempting reconnection
    3. Use a watchdog as backup detection for stale connections
    4. Prevent multiple simultaneous connection attempts
    """

    def __init__(
        self,
        ble_device: BLEDevice,
        ble_device_callback: Callable[[], BLEDevice | None] | None = None,
    ) -> None:
        """Initialize the BedJet device."""
        self.ble_device = ble_device
        self._ble_device_callback = ble_device_callback
        self.client: BleakClient | None = None
        self._callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._connection_callbacks: list[Callable[[bool], None]] = []
        self._operation_lock = asyncio.Lock()

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
        self._shutting_down = False

        # Connection throttling
        self._last_connection_attempt: float = 0.0
        self._connecting = False  # Prevents concurrent connection attempts

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
        if not self._connected or self.client is None:
            return False
        try:
            return self.client.is_connected
        except Exception:
            return False

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
        """Add a callback for connection state changes."""
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
        """Handle disconnection from the BedJet device."""
        was_connected = self._connected
        self._connected = False

        if was_connected:
            _LOGGER.info(
                "BedJet %s disconnected",
                self._name or self.ble_device.address
            )
            # Notify listeners of disconnection
            self._notify_connection_callbacks(False)

        # Schedule reconnection if we should still be connected
        if self._should_reconnect and not self._shutting_down:
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt if not already scheduled."""
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return  # Already have a reconnection in progress

        if self._connecting:
            return  # Already attempting to connect

        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Reconnection loop with exponential backoff.

        Uses conservative timing to avoid overwhelming the Bluetooth adapter.
        """
        # Initial delay before first reconnection attempt
        initial_delay = max(
            RECONNECT_INTERVAL_BASE,
            MIN_TIME_BETWEEN_CONNECTIONS - (time.monotonic() - self._last_connection_attempt)
        )

        _LOGGER.info(
            "BedJet %s: Will attempt reconnection in %.0f seconds",
            self._name or self.ble_device.address,
            initial_delay
        )

        await asyncio.sleep(initial_delay)

        while self._should_reconnect and not self._shutting_down:
            if self.is_connected:
                _LOGGER.debug("Already connected, stopping reconnection loop")
                break

            if self._connecting:
                _LOGGER.debug("Connection already in progress, waiting...")
                await asyncio.sleep(5)
                continue

            self._reconnect_attempts += 1

            # Check max attempts (0 = unlimited)
            if RECONNECT_MAX_ATTEMPTS > 0 and self._reconnect_attempts > RECONNECT_MAX_ATTEMPTS:
                _LOGGER.error(
                    "BedJet %s: Maximum reconnection attempts (%d) reached",
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

                _LOGGER.info(
                    "BedJet %s: Reconnection attempt %d",
                    self._name or self.ble_device.address,
                    self._reconnect_attempts
                )

                await self._connect_internal()

                _LOGGER.info(
                    "BedJet %s: Reconnected successfully after %d attempts",
                    self._name or self.ble_device.address,
                    self._reconnect_attempts
                )
                self._reconnect_attempts = 0
                break

            except Exception as err:
                error_msg = str(err)

                # Determine appropriate backoff based on error type
                if "In Progress" in error_msg or "connection slot" in error_msg.lower():
                    # Bluetooth adapter is busy - wait longer
                    delay = min(RECONNECT_INTERVAL_MAX, 30 + (self._reconnect_attempts * 10))
                    _LOGGER.warning(
                        "BedJet %s: Bluetooth adapter busy, waiting %d seconds: %s",
                        self._name or self.ble_device.address,
                        delay,
                        err
                    )
                else:
                    # Standard exponential backoff
                    delay = min(
                        RECONNECT_INTERVAL_BASE * (2 ** min(self._reconnect_attempts, 6)),
                        RECONNECT_INTERVAL_MAX
                    )
                    _LOGGER.warning(
                        "BedJet %s: Reconnection attempt %d failed, retrying in %d seconds: %s",
                        self._name or self.ble_device.address,
                        self._reconnect_attempts,
                        delay,
                        err
                    )

                if not self._should_reconnect or self._shutting_down:
                    break

                await asyncio.sleep(delay)

    async def _watchdog_loop(self) -> None:
        """Connection watchdog loop.

        Periodically checks the connection state and triggers reconnection
        if needed. Acts as a backup to the disconnect callback.
        """
        while not self._shutting_down:
            await asyncio.sleep(CONNECTION_WATCHDOG_INTERVAL)

            if self._shutting_down:
                break

            # Skip if we're already trying to connect
            if self._connecting:
                continue

            # Skip if reconnect loop is already running
            if self._reconnect_task is not None and not self._reconnect_task.done():
                continue

            # Check if connection is stale
            if self._connected and self.client is not None:
                try:
                    if not self.client.is_connected:
                        _LOGGER.info(
                            "BedJet %s: Watchdog detected stale connection",
                            self._name or self.ble_device.address
                        )
                        self._connected = False
                        self._notify_connection_callbacks(False)
                        if self._should_reconnect:
                            self._schedule_reconnect()
                except Exception:
                    pass

            # If we should be connected but aren't
            elif self._should_reconnect and not self._connected:
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

    async def _connect_internal(self) -> None:
        """Internal connection method with proper locking and throttling."""
        # Check throttling
        time_since_last = time.monotonic() - self._last_connection_attempt
        if time_since_last < MIN_TIME_BETWEEN_CONNECTIONS:
            wait_time = MIN_TIME_BETWEEN_CONNECTIONS - time_since_last
            _LOGGER.debug("Throttling connection attempt, waiting %.1f seconds", wait_time)
            await asyncio.sleep(wait_time)

        if self._connecting:
            _LOGGER.debug("Connection already in progress")
            raise BleakError("Connection already in progress")

        self._connecting = True
        self._last_connection_attempt = time.monotonic()

        try:
            async with self._operation_lock:
                if self.is_connected:
                    return

                # Clean up any existing client
                if self.client is not None:
                    try:
                        await self.client.disconnect()
                    except Exception:
                        pass
                    self.client = None

                _LOGGER.debug(
                    "Connecting to BedJet %s",
                    self._name or self.ble_device.address
                )

                # Establish connection with disconnect callback
                self.client = await establish_connection(
                    BleakClient,
                    self.ble_device,
                    self.ble_device.address,
                    disconnected_callback=self._on_disconnect,
                    timeout=CONNECTION_TIMEOUT,
                )

                # Small delay to let connection stabilize
                await asyncio.sleep(0.5)

                # Subscribe to status notifications
                try:
                    await self.client.start_notify(
                        BEDJET_STATUS_UUID, self._handle_status_update
                    )
                except Exception as err:
                    _LOGGER.warning("Failed to start notifications: %s", err)
                    # Try to disconnect cleanly
                    try:
                        await self.client.disconnect()
                    except Exception:
                        pass
                    self.client = None
                    raise

                # Read device name
                try:
                    name_data = await self.client.read_gatt_char(BEDJET_NAME_UUID)
                    self._name = name_data.decode("utf-8").strip()
                except Exception as err:
                    _LOGGER.debug("Could not read device name: %s", err)
                    if not self._name:
                        self._name = f"BedJet ({self.ble_device.address})"

                self._connected = True
                _LOGGER.info("Connected to BedJet %s", self._name)

                # Notify listeners of connection
                self._notify_connection_callbacks(True)

        finally:
            self._connecting = False

    async def connect(self) -> None:
        """Connect to the BedJet device.

        This is the public method called by the coordinator and other code.
        It will not attempt to connect if already connected or if a connection
        is in progress.
        """
        if self.is_connected:
            return

        if self._connecting:
            # Wait for the current connection attempt to complete
            for _ in range(30):  # Wait up to 30 seconds
                await asyncio.sleep(1)
                if self.is_connected or not self._connecting:
                    break
            if self.is_connected:
                return
            raise BleakError("Connection attempt timed out")

        try:
            await self._connect_internal()
        except Exception as err:
            # Don't spam logs for expected errors during reconnection
            if self._reconnect_task is not None and not self._reconnect_task.done():
                raise
            _LOGGER.error("Failed to connect to BedJet: %s", err)
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

        async with self._operation_lock:
            if self.client:
                try:
                    if self.client.is_connected:
                        try:
                            await self.client.stop_notify(BEDJET_STATUS_UUID)
                        except Exception:
                            pass
                        await self.client.disconnect()
                except Exception as err:
                    _LOGGER.debug("Error during disconnect: %s", err)
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
                if data[7] != 0 and data[7] != 0x26:
                    raw_current = data[7] - 0x26
                    self._current_temp = round((raw_current + 66) - (raw_current / 9))

                if data[8] != 0 and data[8] != 0x26:
                    raw_target = data[8] - 0x26
                    self._target_temp = round((raw_target + 66) - (raw_target / 9))

                # Parse time remaining (bytes 4, 5, 6)
                self._time_remaining = (data[4] * 3600) + (data[5] * 60) + data[6]

                # Parse fan speed (byte 10)
                if data[10] > 0:
                    self._fan_speed = data[10] * FAN_STEP

                # Parse mode (bytes 13 and 14)
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

                self._notify_callbacks()

        except Exception as err:
            _LOGGER.error("Error parsing status data: %s", err)

    async def update(self) -> None:
        """Update device state by requesting current status.

        Note: This method does NOT automatically reconnect. The reconnection
        is handled by the dedicated reconnect loop to avoid connection thrashing.
        """
        if not self.is_connected:
            # If not connected, just return - the reconnect loop will handle it
            if not self._connecting and (self._reconnect_task is None or self._reconnect_task.done()):
                self._schedule_reconnect()
            return

        try:
            await self._send_command([0x01, 0x00])  # Status request
        except Exception as err:
            _LOGGER.debug("Status request failed: %s", err)

    async def _send_command(self, command: list[int]) -> None:
        """Send a command to the BedJet."""
        if not self.is_connected:
            raise BleakError("Device not connected")

        async with self._operation_lock:
            try:
                command_bytes = bytearray(command)
                _LOGGER.debug("Sending command: %s", command_bytes.hex())
                await self.client.write_gatt_char(BEDJET_COMMAND_UUID, command_bytes)
                await asyncio.sleep(0.3)
            except Exception as err:
                _LOGGER.error("Failed to send command: %s", err)
                raise

    async def _send_command_with_retry(self, command: list[int], retries: int = 2) -> None:
        """Send a command with retry on failure."""
        last_error = None
        for attempt in range(retries + 1):
            try:
                if not self.is_connected:
                    if self._connecting:
                        # Wait for connection
                        for _ in range(10):
                            await asyncio.sleep(1)
                            if self.is_connected:
                                break
                    if not self.is_connected:
                        raise BleakError("Device not connected")

                await self._send_command(command)
                return
            except Exception as err:
                last_error = err
                if attempt < retries:
                    _LOGGER.debug(
                        "Command failed (attempt %d/%d): %s",
                        attempt + 1, retries + 1, err
                    )
                    await asyncio.sleep(1)

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
            raise ValueError(f"Temperature {temperature} out of range {MIN_TEMP}-{MAX_TEMP}")
        temp_offset = temperature - 66
        temp_byte = int(temp_offset + (temp_offset / 9) + 0x26)
        temp_byte = max(0, min(255, temp_byte))
        await self._send_command_with_retry([0x03, temp_byte])

    async def set_fan_speed(self, speed: int) -> None:
        """Set the fan speed percentage."""
        if not MIN_FAN_SPEED <= speed <= MAX_FAN_SPEED:
            raise ValueError(f"Fan speed {speed} out of range {MIN_FAN_SPEED}-{MAX_FAN_SPEED}")
        fan_byte = round(speed / FAN_STEP) - 1
        await self._send_command_with_retry([0x07, fan_byte])

    async def set_timer(self, minutes: int) -> None:
        """Set the timer in minutes."""
        if minutes < 0 or minutes > 600:
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
        """Update the BLE device reference."""
        self.ble_device = ble_device
