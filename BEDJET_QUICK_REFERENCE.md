# BedJet Integration Quick Reference

## 🆕 What's New (v2025.9.2)
- ✅ **climate.turn_on** and **climate.turn_off** services now work
- ✅ **Temperature settings stick** (no more reverting to 84°F)
- ✅ **Enhanced debug logging** for troubleshooting
- ✅ **Better command processing** with delays and retries

## 🎮 Available Services

### Basic Climate Control
```yaml
# Turn on BedJet (uses last mode or defaults to heat)
service: climate.turn_on
target:
  entity_id: climate.bedjet_bedroom

# Turn off BedJet
service: climate.turn_off
target:
  entity_id: climate.bedjet_bedroom

# Set temperature (66-104°F)
service: climate.set_temperature
target:
  entity_id: climate.bedjet_bedroom
data:
  temperature: 72

# Set HVAC mode
service: climate.set_hvac_mode
target:
  entity_id: climate.bedjet_bedroom
data:
  hvac_mode: cool  # Options: off, heat, cool, dry

# Set fan speed
service: climate.set_fan_mode
target:
  entity_id: climate.bedjet_bedroom
data:
  fan_mode: "25%"  # 5% to 100% in 5% increments
```

## 🔧 Debug Mode
Add to `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.bedjet: debug
```

Look for these log messages:
- `Setting temperature 72°F (byte: 0x42)` - Temperature commands
- `Mode changed from off to heat` - Mode changes
- `Sending command: 0103XX` - Raw commands being sent
- `Received status data: XXXX` - Status updates from device

## 🚨 Troubleshooting

### Temperature Won't Change
1. **Check current mode** - Temperature only works in heat/cool modes
2. **Enable debug logging** - Look for temperature command bytes
3. **Wait for status update** - Can take 5-10 seconds
4. **Try while BedJet is running** - Some commands work better when active

### Turn On Doesn't Work  
1. **Check last mode memory** - Integration remembers last non-off mode
2. **Set explicit mode first** - Try `climate.set_hvac_mode` before turn_on
3. **Check debug logs** - Look for mode change commands

### Connection Issues
1. **Power cycle BedJet** - Turn off and on again
2. **Check Bluetooth range** - Stay within 30 feet during setup
3. **Restart integration** - Settings → Devices & Services → BedJet → Reload
4. **Restart Home Assistant** - If all else fails

## 📱 Quick Test Script
```yaml
# Test all functions
script:
  test_bedjet:
    sequence:
      - service: climate.turn_on
        target:
          entity_id: climate.bedjet_bedroom
      - delay: 2
      - service: climate.set_temperature
        target:
          entity_id: climate.bedjet_bedroom
        data:
          temperature: 70
      - delay: 2
      - service: climate.set_fan_mode
        target:
          entity_id: climate.bedjet_bedroom
        data:
          fan_mode: "20%"
      - delay: 5
      - service: climate.turn_off
        target:
          entity_id: climate.bedjet_bedroom
```

## 📊 State Attributes
- `current_temperature` - Current bed temperature
- `target_temperature` - Target temperature setting  
- `hvac_mode` - Current operating mode
- `fan_mode` - Current fan speed percentage
- `time_remaining` - Auto-shutoff timer (seconds)

## 🎯 Common Use Cases

### Bedtime Cooling
```yaml
automation:
  - alias: "Bedtime Cool Down"
    trigger:
      platform: time
      at: "22:00:00"
    action:
      - service: climate.turn_on
        target:
          entity_id: climate.bedjet_bedroom
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

### Morning Warm-up
```yaml
automation:
  - alias: "Morning Warm-up"
    trigger:
      platform: time
      at: "06:30:00"
    condition:
      condition: numeric_state
      entity_id: weather.home
      attribute: temperature
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

---
**Need Help?** Check debug logs and report issues with log excerpts.
