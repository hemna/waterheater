#!/bin/bash
# Waterheater app watchdog for Raspberry Pi.
# Checks that the waterheater Flask/SocketIO app is responding on port 80.
# If the HTTP check fails, restarts waterheater.service.
# Designed to run via systemd timer every 2 minutes.

APP_URL="http://127.0.0.1:80/"
HTTP_TIMEOUT=10
LOG_TAG="app-watchdog"
SERVICE="waterheater.service"
RESTART_WAIT=15   # seconds to wait after restart before rechecking

log() {
    logger -t "$LOG_TAG" "$1"
}

# Returns 0 if the app returns any HTTP response (even 302 redirect to /login).
check_app() {
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        --max-time "$HTTP_TIMEOUT" \
        --connect-timeout 5 \
        "$APP_URL" 2>/dev/null)
    # Any response (200, 302, 401, etc.) means the app is alive.
    [ -n "$http_code" ] && [ "$http_code" -ge 100 ] 2>/dev/null
}

if check_app; then
    exit 0
fi

log "waterheater app not responding on $APP_URL — restarting $SERVICE"
systemctl restart "$SERVICE"

sleep "$RESTART_WAIT"

if check_app; then
    log "waterheater app recovered after restart"
    exit 0
fi

log "waterheater app STILL not responding after restart — check logs: journalctl -u $SERVICE"
# Don't reboot — a broken app config would cause a reboot loop.
# Log and let the operator investigate.
exit 1
