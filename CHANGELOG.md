# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
