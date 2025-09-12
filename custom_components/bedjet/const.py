"""Constants for the BedJet integration."""
from __future__ import annotations

from enum import IntEnum
from typing import Final

DOMAIN: Final = "bedjet"
MANUFACTURER: Final = "BedJet"

# BLE characteristics
BEDJET_STATUS_UUID: Final = "00002000-bed0-0080-aa55-4265644a6574"
BEDJET_NAME_UUID: Final = "00002001-bed0-0080-aa55-4265644a6574"
BEDJET_COMMAND_UUID: Final = "00002004-bed0-0080-aa55-4265644a6574"

# Update intervals
UPDATE_INTERVAL: Final = 30  # seconds
SCAN_INTERVAL: Final = 60    # seconds

# Temperature limits (Fahrenheit)
MIN_TEMP: Final = 66
MAX_TEMP: Final = 104

# Fan speed limits (percentage)
MIN_FAN_SPEED: Final = 5
MAX_FAN_SPEED: Final = 100
FAN_STEP: Final = 5

class BedJetMode(IntEnum):
    """BedJet operation modes."""
    OFF = 0x01
    COOL = 0x02
    HEAT = 0x03
    TURBO = 0x04
    DRY = 0x05
    EXT_HT = 0x06

class BedJetControl(IntEnum):
    """BedJet control commands."""
    FAN_UP = 0x10
    FAN_DOWN = 0x11
    TEMP_UP = 0x12
    TEMP_DOWN = 0x13

class BedJetPreset(IntEnum):
    """BedJet memory presets."""
    M1 = 0x20
    M2 = 0x21
    M3 = 0x22

MODE_MAP = {
    BedJetMode.OFF: "off",
    BedJetMode.COOL: "cool",
    BedJetMode.HEAT: "heat",
    BedJetMode.TURBO: "turbo",
    BedJetMode.DRY: "dry",
    BedJetMode.EXT_HT: "ext_ht"
}

REVERSE_MODE_MAP = {v: k for k, v in MODE_MAP.items()}
