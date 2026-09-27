#!/bin/bash
# Install WiFi stability scripts on the waterheater Raspberry Pi.
# Run as root (or with sudo) from the waterheater repo directory.
#
# What this does:
#   1. Installs NM dispatcher to disable WiFi power management on connect
#   2. Installs wifi-watchdog systemd service + timer (pings every 5 min)
#   3. Disables power management immediately
#
# Usage:
#   sudo ./scripts/install-wifi-watchdog.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Installing WiFi power management dispatcher..."
cp "$SCRIPT_DIR/99-wifi-powersave-off" /etc/NetworkManager/dispatcher.d/99-wifi-powersave-off
chmod 755 /etc/NetworkManager/dispatcher.d/99-wifi-powersave-off

echo "==> Making watchdog script executable..."
chmod 755 "$SCRIPT_DIR/wifi-watchdog.sh"

echo "==> Installing systemd service and timer..."
cp "$SCRIPT_DIR/wifi-watchdog.service" /etc/systemd/system/wifi-watchdog.service
cp "$SCRIPT_DIR/wifi-watchdog.timer" /etc/systemd/system/wifi-watchdog.timer
systemctl daemon-reload
systemctl enable wifi-watchdog.timer
systemctl start wifi-watchdog.timer

echo "==> Disabling WiFi power management now..."
/sbin/iwconfig wlan0 power off 2>/dev/null || true

echo ""
echo "Done. WiFi watchdog timer is active:"
systemctl status wifi-watchdog.timer --no-pager
