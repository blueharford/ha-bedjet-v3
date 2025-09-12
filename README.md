# BedJet V3 Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/blueharford/ha-bedjet-v3.svg)](https://github.com/blueharford/ha-bedjet-v3/releases)
[![License](https://img.shields.io/github/license/blueharford/ha-bedjet-v3.svg)](LICENSE)

A modern Home Assistant integration for BedJet V3 climate control devices. This integration provides full climate control via Bluetooth Low Energy, including temperature control, fan speed adjustment, and all BedJet operating modes.

## Features

### BedJet V3 Support
- 🌡️ **Temperature Control** - Set target temperature (66°F - 104°F)
- 💨 **Fan Speed Control** - Adjust fan speed (5% - 100% in 5% increments)
- 🔄 **Operating Modes** - Off, Cool, Heat, Turbo Heat, Dry, External Heat
- ⏰ **Timer Control** - Set auto-shutoff timer up to 10 hours
- 💾 **Memory Presets** - Access M1, M2, M3 memory settings
- 📡 **Real-time Updates** - Live temperature and status monitoring

### Home Assistant Integration
- 🔍 **Auto-Discovery** - Automatic Bluetooth device discovery
- 🏠 **Climate Entity** - Full Home Assistant climate control interface
- 📱 **Device Registry** - Proper device information and connections
- 🔧 **Config Flow** - Easy setup through UI
- 📊 **State Attributes** - Additional info like time remaining
- 🛡️ **Error Handling** - Robust connection management and recovery

## Installation

### HACS (Recommended)

1. **Add Custom Repository**
   - Open HACS in Home Assistant
   - Go to "Integrations"
   - Click the three dots menu (⋮) → "Custom repositories"
   - Add `https://github.com/blueharford/ha-bedjet-v3` as "Integration"
   - Click "Add"

2. **Install Integration**
   - Search for "BedJet V3 Climate Control" in HACS
   - Click "Download"
   - Restart Home Assistant

### Manual Installation

1. **Download Files**
   - Download the latest release from [GitHub releases](https://github.com/blueharford/ha-bedjet-v3/releases)
   - Extract the archive

2. **Copy Files**
   ```bash
   # Copy to your Home Assistant config directory
   cp -r custom_components/bedjet /config/custom_components/
   ```

3. **Restart Home Assistant**

## Setup

### Prerequisites
- Home Assistant 2025.9.0 or later
- BedJet V3 device
- Bluetooth Low Energy support on Home Assistant host
- BedJet within Bluetooth range (≤ 30 feet recommended)

### Configuration

1. **Enable Bluetooth**
   - Ensure the Bluetooth integration is enabled in Home Assistant
   - Verify your BedJet is powered on and discoverable

2. **Add Integration**
   - Go to **Settings** → **Devices & Services**
   - Click **"Add Integration"**
   - Search for **"BedJet"** (or it may auto-discover)
   - Follow the setup wizard to pair your BedJet V3

3. **Device Setup**
   - The integration will automatically discover nearby BedJet devices
   - Select your device from the list or enter MAC address manually
   - Complete the pairing process

## Usage

### Basic Climate Control

The BedJet will appear as a climate entity in Home Assistant:

```yaml
# Example automation
automation:
  - alias: "Bedtime Cooling"
    trigger:
      platform: time
      at: "22:00:00"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.bedjet_bedroom
        data:
          temperature: 68
          hvac_mode: cool
      - service: climate.set_fan_mode
        target:
          entity_id: climate.bedjet_bedroom
        data:
          fan_mode: "25%"
```

### Available Services

The integration supports all standard climate services:
- `climate.set_temperature` - Set target temperature
- `climate.set_hvac_mode` - Set operating mode
- `climate.set_fan_mode` - Set fan speed percentage

### HVAC Modes
- **Off** - Turn off BedJet
- **Cool** - Cooling mode
- **Heat** - Heating mode  
- **Dry** - Dry mode (fan only)

*Note: Turbo Heat and External Heat modes map to Heat mode in Home Assistant*

### Fan Modes
Fan speed can be set from 5% to 100% in 5% increments:
- `5%`, `10%`, `15%`, `20%`, `25%`, `30%`, etc.

### State Attributes
- `current_temperature` - Current bed temperature
- `target_temperature` - Target temperature setting
- `time_remaining` - Auto-shutoff timer remaining (seconds)

## Automation Examples

### Smart Sleep Climate
```yaml
automation:
  - alias: "Smart Sleep Climate"
    trigger:
      - platform: state
        entity_id: binary_sensor.bedroom_occupancy
        to: "on"
    condition:
      - condition: time
        after: "21:00:00"
        before: "07:00:00"
    action:
      - service: climate.set_hvac_mode
        target:
          entity_id: climate.bedjet_bedroom
        data:
          hvac_mode: cool
      - service: climate.set_temperature
        target:
          entity_id: climate.bedjet_bedroom
        data:
          temperature: 68
```

### Temperature-Based Auto Control
```yaml
automation:
  - alias: "Auto BedJet on Hot Days"
    trigger:
      platform: numeric_state
      entity_id: sensor.bedroom_temperature
      above: 75
    action:
      - service: climate.set_hvac_mode
        target:
          entity_id: climate.bedjet_bedroom
        data:
          hvac_mode: cool
      - service: climate.set_temperature
        target:
          entity_id: climate.bedjet_bedroom
        data:
          temperature: 70
```

### Morning Warm-Up
```yaml
automation:
  - alias: "Morning Warm-Up"
    trigger:
      platform: time
      at: "06:30:00"
    condition:
      condition: numeric_state
      entity_id: sensor.outdoor_temperature
      below: 50
    action:
      - service: climate.set_hvac_mode
        target:
          entity_id: climate.bedjet_bedroom
        data:
          hvac_mode: heat
      - service: climate.set_temperature
        target:
          entity_id: climate.bedjet_bedroom
        data:
          temperature: 75
```

## Troubleshooting

### Common Issues

**Device Not Found**
- Ensure BedJet is powered on and within range
- Check that Bluetooth is enabled in Home Assistant
- Try restarting the Bluetooth service
- Manually enter MAC address if auto-discovery fails

**Connection Failed** 
- Power cycle the BedJet device
- Restart Home Assistant
- Ensure no other devices (like the BedJet app) are connected
- Check Home Assistant logs for detailed error messages

**Commands Not Responding**
- Verify Bluetooth connection stability
- Restart the integration: Settings → Devices & Services → BedJet → Configure
- Check for interference from other Bluetooth devices

### Debug Logging

Enable debug logging by adding to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.bedjet: debug
    homeassistant.components.bluetooth: debug
```

### System Requirements

**Home Assistant**
- Version 2025.9.0 or later
- Bluetooth integration enabled
- Python 3.11 or later

**Hardware**
- BedJet V3 device (V1/V2 not supported)
- Bluetooth Low Energy adapter
- Stable Bluetooth range (< 30 feet recommended)

## Technical Details

### Bluetooth Protocol
- Uses BedJet's proprietary Bluetooth LE protocol
- Real-time status updates via BLE notifications
- Custom temperature and fan speed encoding
- Robust connection handling with automatic retry

### Integration Architecture
- **Device Layer**: `BedJetDevice` handles Bluetooth communication
- **Platform Layer**: `BedJetClimate` provides Home Assistant climate entity  
- **Config Flow**: Manages device discovery and setup
- **Update Coordinator**: Handles periodic state synchronization

### Dependencies
- `bleak>=0.22.0` - Modern Bluetooth Low Energy library
- `bleak-retry-connector>=3.5.0` - Connection retry logic
- Home Assistant Bluetooth integration

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

### Development Setup

```bash
# Clone the repository
git clone https://github.com/blueharford/ha-bedjet-v3.git
cd ha-bedjet-v3

# Set up development environment
# (Follow Home Assistant development setup guide)
```

## Support

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/blueharford/ha-bedjet-v3/issues)
- 💡 **Feature Requests**: [GitHub Issues](https://github.com/blueharford/ha-bedjet-v3/issues)
- 💬 **Questions**: [Home Assistant Community](https://community.home-assistant.io/)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Home Assistant development team for the excellent platform
- BedJet for creating an innovative sleep climate solution
- The Home Assistant community for testing and feedback

---

**Disclaimer**: This integration is not affiliated with BedJet LLC. BedJet is a trademark of BedJet LLC.
