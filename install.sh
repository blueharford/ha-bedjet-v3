#!/bin/bash
#
# BedJet V3 Home Assistant Integration Installer
# https://github.com/blueharford/ha-bedjet-v3
#
# This script installs the BedJet V3 integration for Home Assistant.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Print banner
print_banner() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                                                               ║"
    echo "║        ${BOLD}BedJet V3 Home Assistant Integration${NC}${CYAN}                  ║"
    echo "║                    Installer v2026.1.0                        ║"
    echo "║                                                               ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Print colored message
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Detect Home Assistant configuration directory
detect_config_dir() {
    local config_dirs=(
        "/config"                           # Home Assistant OS / Docker
        "/usr/share/hassio/homeassistant"   # Supervised
        "$HOME/.homeassistant"              # Core installation
        "/home/homeassistant/.homeassistant" # venv installation
        "/srv/homeassistant/.homeassistant" # Alternative venv
        "."                                 # Current directory (for development)
    )

    for dir in "${config_dirs[@]}"; do
        if [[ -f "$dir/configuration.yaml" ]]; then
            echo "$dir"
            return 0
        fi
    done

    return 1
}

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Main installation function
main() {
    print_banner

    echo -e "${BOLD}Starting installation...${NC}\n"

    # Check if custom_components/bedjet exists in script directory
    if [[ ! -d "$SCRIPT_DIR/custom_components/bedjet" ]]; then
        error "Integration files not found at $SCRIPT_DIR/custom_components/bedjet"
        error "Please run this script from the repository root directory."
        exit 1
    fi

    # Detect or get config directory
    info "Detecting Home Assistant configuration directory..."

    if [[ -n "$1" ]]; then
        CONFIG_DIR="$1"
        info "Using provided config directory: $CONFIG_DIR"
    else
        CONFIG_DIR=$(detect_config_dir) || true

        if [[ -z "$CONFIG_DIR" ]]; then
            echo ""
            warning "Could not auto-detect Home Assistant configuration directory."
            echo ""
            echo -e "Common locations:"
            echo -e "  ${CYAN}/config${NC}                           - Home Assistant OS / Docker"
            echo -e "  ${CYAN}/usr/share/hassio/homeassistant${NC}   - Supervised installation"
            echo -e "  ${CYAN}~/.homeassistant${NC}                  - Core installation"
            echo ""
            read -p "Please enter your Home Assistant config directory: " CONFIG_DIR

            if [[ -z "$CONFIG_DIR" ]]; then
                error "No configuration directory provided. Exiting."
                exit 1
            fi
        else
            success "Found Home Assistant config at: $CONFIG_DIR"
        fi
    fi

    # Validate config directory
    if [[ ! -d "$CONFIG_DIR" ]]; then
        error "Directory does not exist: $CONFIG_DIR"
        exit 1
    fi

    if [[ ! -f "$CONFIG_DIR/configuration.yaml" ]]; then
        warning "configuration.yaml not found in $CONFIG_DIR"
        read -p "Continue anyway? (y/N): " confirm
        if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
            error "Installation cancelled."
            exit 1
        fi
    fi

    # Create custom_components directory if needed
    DEST_DIR="$CONFIG_DIR/custom_components"
    if [[ ! -d "$DEST_DIR" ]]; then
        info "Creating custom_components directory..."
        mkdir -p "$DEST_DIR"
    fi

    # Check for existing installation
    if [[ -d "$DEST_DIR/bedjet" ]]; then
        warning "Existing BedJet integration found at $DEST_DIR/bedjet"
        read -p "Overwrite existing installation? (y/N): " confirm
        if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
            error "Installation cancelled."
            exit 1
        fi
        info "Removing existing installation..."
        rm -rf "$DEST_DIR/bedjet"
    fi

    # Copy integration files
    info "Installing BedJet integration..."
    cp -r "$SCRIPT_DIR/custom_components/bedjet" "$DEST_DIR/"

    # Verify installation
    if [[ -f "$DEST_DIR/bedjet/manifest.json" ]]; then
        success "Integration files installed successfully!"
    else
        error "Installation verification failed. Please check permissions."
        exit 1
    fi

    # Get version from manifest
    VERSION=$(grep -o '"version": "[^"]*"' "$DEST_DIR/bedjet/manifest.json" | cut -d'"' -f4)

    # Print success message and next steps
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                               ║${NC}"
    echo -e "${GREEN}║              ${BOLD}Installation Complete!${NC}${GREEN}                          ║${NC}"
    echo -e "${GREEN}║                                                               ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BOLD}Installed Version:${NC} $VERSION"
    echo -e "${BOLD}Installed To:${NC} $DEST_DIR/bedjet"
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}                     NEXT STEPS                                ${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${BOLD}1. RESTART HOME ASSISTANT${NC}"
    echo -e "   The integration will not be available until you restart."
    echo ""
    echo -e "   ${YELLOW}For Home Assistant OS / Supervised:${NC}"
    echo -e "   - Go to Settings -> System -> Restart"
    echo -e "   - Or run: ${CYAN}ha core restart${NC}"
    echo ""
    echo -e "   ${YELLOW}For Home Assistant Core:${NC}"
    echo -e "   - Run: ${CYAN}sudo systemctl restart home-assistant@homeassistant${NC}"
    echo -e "   - Or:  ${CYAN}hass --script restart${NC}"
    echo ""
    echo -e "   ${YELLOW}For Docker:${NC}"
    echo -e "   - Run: ${CYAN}docker restart homeassistant${NC}"
    echo ""
    echo -e "${BOLD}2. ENABLE BLUETOOTH (if not already enabled)${NC}"
    echo -e "   - Go to Settings -> Devices & Services"
    echo -e "   - Search for 'Bluetooth' and add it if not present"
    echo -e "   - Ensure your Bluetooth adapter is detected"
    echo ""
    echo -e "${BOLD}3. ADD THE BEDJET INTEGRATION${NC}"
    echo -e "   - Go to Settings -> Devices & Services"
    echo -e "   - Click '+ Add Integration' button"
    echo -e "   - Search for '${CYAN}BedJet${NC}'"
    echo -e "   - Select your BedJet device from the list"
    echo -e "   - Complete the setup wizard"
    echo ""
    echo -e "   ${YELLOW}Note:${NC} Your BedJet should auto-discover if it's powered on"
    echo -e "   and within Bluetooth range (~30 feet / 10 meters)"
    echo ""
    echo -e "${BOLD}4. VERIFY THE DEVICE${NC}"
    echo -e "   - After setup, go to Settings -> Devices & Services"
    echo -e "   - Find 'BedJet V3 Climate Control' in the integrations list"
    echo -e "   - Click on it to see your device"
    echo -e "   - The device should show as 'Available' if connected"
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}                   TROUBLESHOOTING                             ${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${YELLOW}If BedJet is not discovered:${NC}"
    echo -e "   - Ensure BedJet is powered on"
    echo -e "   - Close the BedJet phone app (it may be holding the connection)"
    echo -e "   - Power cycle the BedJet device"
    echo -e "   - Check that Bluetooth adapter is working in Home Assistant"
    echo ""
    echo -e "${YELLOW}If connection drops frequently:${NC}"
    echo -e "   - Move Home Assistant closer to the BedJet"
    echo -e "   - Reduce Bluetooth interference from other devices"
    echo -e "   - The integration will auto-reconnect when connection is lost"
    echo ""
    echo -e "${YELLOW}To enable debug logging, add to configuration.yaml:${NC}"
    echo -e "   ${CYAN}logger:"
    echo -e "     default: info"
    echo -e "     logs:"
    echo -e "       custom_components.bedjet: debug${NC}"
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}                      RESOURCES                                ${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "Documentation:  ${CYAN}https://github.com/blueharford/ha-bedjet-v3${NC}"
    echo -e "Issues/Bugs:    ${CYAN}https://github.com/blueharford/ha-bedjet-v3/issues${NC}"
    echo -e "HA Community:   ${CYAN}https://community.home-assistant.io/${NC}"
    echo ""
    echo -e "${GREEN}Thank you for using BedJet V3 Home Assistant Integration!${NC}"
    echo ""
}

# Run main function with all arguments
main "$@"
