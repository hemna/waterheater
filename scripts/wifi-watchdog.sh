#!/bin/bash
# WiFi connectivity watchdog for Raspberry Pi
# Pings gateway and external DNS; restarts networking if both fail.
# Designed to run via systemd timer every 5 minutes.

GATEWAY="192.168.1.1"
EXTERNAL="8.8.8.8"
LOG_TAG="wifi-watchdog"
PING_COUNT=3
PING_TIMEOUT=5

log() {
    logger -t "$LOG_TAG" "$1"
}

ping_host() {
    ping -c "$PING_COUNT" -W "$PING_TIMEOUT" "$1" > /dev/null 2>&1
}

# Try gateway first
if ping_host "$GATEWAY"; then
    exit 0
fi

log "Gateway $GATEWAY unreachable, trying external $EXTERNAL..."

if ping_host "$EXTERNAL"; then
    log "External reachable but gateway not — unusual, skipping restart"
    exit 0
fi

log "Both $GATEWAY and $EXTERNAL unreachable — restarting WiFi"

# Disable and re-enable the WiFi device via nmcli
nmcli radio wifi off
sleep 2
nmcli radio wifi on
sleep 10

# Disable power management after reconnect
/sbin/iwconfig wlan0 power off 2>/dev/null

# Verify recovery
if ping_host "$GATEWAY"; then
    log "WiFi recovered after restart"
else
    log "WiFi still down after nmcli restart — attempting full NM restart"
    systemctl restart NetworkManager
    sleep 15
    /sbin/iwconfig wlan0 power off 2>/dev/null

    if ping_host "$GATEWAY"; then
        log "WiFi recovered after NetworkManager restart"
    else
        log "WiFi STILL down — hardware issue or AP down, giving up"
    fi
fi
