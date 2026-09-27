#!/bin/bash
# Install all watchdog scripts on the waterheater Raspberry Pi.
# Run as root (or with sudo) from the waterheater repo directory.
#
# Installs:
#   1. wifi-watchdog   — pings gateway every 5 min, restarts WiFi if unreachable
#   2. sshd-watchdog   — checks SSH banner every 2 min, restarts sshd / reboots if stuck
#   3. app-watchdog    — checks waterheater HTTP every 2 min, restarts app if unresponsive
#
# Usage:
#   sudo ./scripts/install-watchdogs.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Installing WiFi power management dispatcher..."
cp "$SCRIPT_DIR/99-wifi-powersave-off" /etc/NetworkManager/dispatcher.d/99-wifi-powersave-off
chmod 755 /etc/NetworkManager/dispatcher.d/99-wifi-powersave-off

echo "==> Making watchdog scripts executable..."
chmod 755 "$SCRIPT_DIR/wifi-watchdog.sh"
chmod 755 "$SCRIPT_DIR/sshd-watchdog.sh"
chmod 755 "$SCRIPT_DIR/app-watchdog.sh"

echo "==> Installing systemd units..."
cp "$SCRIPT_DIR/wifi-watchdog.service"  /etc/systemd/system/wifi-watchdog.service
cp "$SCRIPT_DIR/wifi-watchdog.timer"    /etc/systemd/system/wifi-watchdog.timer
cp "$SCRIPT_DIR/sshd-watchdog.service"  /etc/systemd/system/sshd-watchdog.service
cp "$SCRIPT_DIR/sshd-watchdog.timer"    /etc/systemd/system/sshd-watchdog.timer
cp "$SCRIPT_DIR/app-watchdog.service"   /etc/systemd/system/app-watchdog.service
cp "$SCRIPT_DIR/app-watchdog.timer"     /etc/systemd/system/app-watchdog.timer

systemctl daemon-reload

echo "==> Enabling and starting timers..."
systemctl enable --now wifi-watchdog.timer
systemctl enable --now sshd-watchdog.timer
systemctl enable --now app-watchdog.timer

echo "==> Disabling WiFi power management now..."
/sbin/iwconfig wlan0 power off 2>/dev/null || true

echo ""
echo "Done. Active timers:"
systemctl list-timers wifi-watchdog.timer sshd-watchdog.timer app-watchdog.timer --no-pager
