# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2026.1.0] - 2026-01-28

### Added
- **Persistent Connection Management**: Integration now aggressively maintains BLE connection
  - Automatic reconnection when phone app or other clients take over the connection
  - Exponential backoff reconnection strategy (2s -> 4s -> 8s -> ... up to 60s max)
  - Connection watchdog that monitors and restores connections every 15 seconds
  - Bleak disconnection callback for immediate detection when connection is lost
- **Connection State Callbacks**: Real-time connection state updates to Home Assistant
- **BLE Device Refresh**: Integration listens for Bluetooth updates from Home Assistant to keep device references fresh
- **Command Retry Logic**: All commands now retry with automatic reconnection on failure
- **Diagnostic Attributes**: Entity now shows `reconnect_attempts` when reconnecting
- **Formatted Time Remaining**: New `time_remaining_formatted` attribute (e.g., "1h 30m 0s")

### Changed
- **iot_class**: Changed from `local_polling` to `local_push` to reflect BLE notification-based updates
- **Minimum Home Assistant Version**: Now requires Home Assistant 2026.1.0
- **bleak-retry-connector**: Updated minimum version to 3.6.0
- **Entity Naming**: Uses `_attr_has_entity_name = True` for modern entity naming

### Fixed
- **Connection Takeover Issue**: When phone BedJet app connects, integration now automatically reconnects
- **Stale Connection Detection**: Watchdog detects and recovers from stale connections
- **Entity Availability**: Properly reflects connection state in real-time

### Technical
- Added `disconnected_callback` to BleakClient for immediate disconnection detection
- Added `_connect_lock` to prevent concurrent connection attempts
- Connection callbacks notify coordinator and entity of state changes
- Proper cleanup of watchdog and reconnection tasks on unload
- Registered for Bluetooth device updates via `async_register_callback`
- Clean shutdown handling via `EVENT_HOMEASSISTANT_STOP`

## [2025.9.1] - 2025-09-12

### Added
- Initial release of BedJet V3 Home Assistant integration
- Full climate control support via Bluetooth LE
- Temperature control (66°F - 104°F)
- Fan speed control (5% - 100% in 5% increments)
- All BedJet operating modes (Off, Cool, Heat, Turbo, Dry, External Heat)
- Timer control (up to 10 hours)
- Memory preset support (M1, M2, M3)
- Real-time status updates via Bluetooth notifications
- Automatic Bluetooth device discovery
- Config flow setup with UI
- Comprehensive error handling and recovery
- Device registry integration
- HACS support

### Technical
- Compatible with Home Assistant 2025.9.0+
- Uses modern `bleak` Bluetooth library (>=0.22.0)
- Implements `bleak-retry-connector` for robust connections
- Modern Home Assistant integration patterns
- Type hints throughout
- Comprehensive logging for debugging
- Silver tier quality scale compliance

### Documentation
- Complete README with installation and usage instructions
- Automation examples
- Troubleshooting guide
- Technical details and architecture information
