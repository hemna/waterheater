#!/bin/bash
# sshd connectivity watchdog for Raspberry Pi.
# Verifies sshd is actually accepting connections (not just running as a process).
# If the banner exchange fails, restarts sshd. If that doesn't recover it, reboots.
# Designed to run via systemd timer every 2 minutes.
#
# Guards against false-positive reboots:
#   - skips the probe entirely if nc is unavailable
#   - probes the port sshd is actually configured to listen on
#   - limits reboots to MAX_REBOOTS_PER_DAY

SSH_TIMEOUT=10
LOG_TAG="sshd-watchdog"
REBOOT_DELAY=10       # seconds to wait after sshd restart before rechecking
MAX_REBOOTS_PER_DAY=3
STATE_DIR="/var/lib/sshd-watchdog"
REBOOT_COUNT_FILE="$STATE_DIR/reboot_count"

log() {
    logger -t "$LOG_TAG" "$1"
}

# Resolve the port sshd is configured to listen on (default 22).
get_sshd_port() {
    local p
    p=$(sshd -T 2>/dev/null | awk '/^port /{print $2}')
    if [ -z "$p" ]; then
        p=$(sed -n 's/^[[:space:]]*Port[[:space:]]\+\([0-9]\+\)/\1/p' /etc/ssh/sshd_config 2>/dev/null | tail -1)
    fi
    echo "${p:-22}"
}

# Test that sshd is accepting connections by reading the SSH banner.
# nc exits 0 if the connection opened and we received data.
check_sshd() {
    banner=$(nc -w "$SSH_TIMEOUT" 127.0.0.1 "$SSH_PORT" 2>/dev/null | head -1)
    echo "$banner" | grep -q "^SSH-"
}

if ! command -v nc >/dev/null 2>&1; then
    log "nc not available — cannot probe sshd; skipping check"
    exit 0
fi

SSH_PORT=$(get_sshd_port)

if check_sshd; then
    exit 0
fi

log "sshd not accepting connections on port $SSH_PORT — restarting sshd"
systemctl restart ssh

sleep "$REBOOT_DELAY"

if check_sshd; then
    log "sshd recovered after restart"
    exit 0
fi

# sshd still not responding after restart. Reboot to recover the host, but only
# up to MAX_REBOOTS_PER_DAY so a persistent false positive can't reboot-loop.
mkdir -p "$STATE_DIR"
today=$(date +%Y-%m-%d)
last_day=$(sed -n '1p' "$REBOOT_COUNT_FILE" 2>/dev/null)
count=$(sed -n '2p' "$REBOOT_COUNT_FILE" 2>/dev/null)
if [ "$last_day" != "$today" ]; then
    count=0
fi
count=$((count + 1))
if [ "$count" -gt "$MAX_REBOOTS_PER_DAY" ]; then
    log "sshd STILL not accepting connections after restart; reboot limit ($MAX_REBOOTS_PER_DAY/day) reached — not rebooting"
    exit 1
fi
printf '%s\n%s\n' "$today" "$count" > "$REBOOT_COUNT_FILE"
log "sshd STILL not accepting connections after restart — rebooting host (reboot $count/$MAX_REBOOTS_PER_DAY today)"
/sbin/reboot
