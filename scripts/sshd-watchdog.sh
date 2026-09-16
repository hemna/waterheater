#!/bin/bash
# sshd connectivity watchdog for Raspberry Pi.
# Verifies sshd is actually accepting connections (not just running as a process).
# If the banner exchange fails, restarts sshd. If that doesn't recover it, reboots.
# Designed to run via systemd timer every 2 minutes.

SSH_PORT=22
SSH_TIMEOUT=10
LOG_TAG="sshd-watchdog"
REBOOT_DELAY=10   # seconds to wait after sshd restart before rechecking

log() {
    logger -t "$LOG_TAG" "$1"
}

# Test that sshd is accepting connections by reading the SSH banner.
# nc exits 0 if the connection opened and we received data.
check_sshd() {
    banner=$(nc -w "$SSH_TIMEOUT" 127.0.0.1 "$SSH_PORT" 2>/dev/null | head -1)
    echo "$banner" | grep -q "^SSH-"
}

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

# sshd still not responding after restart — something more serious is wrong.
# Reboot to recover the host.
log "sshd STILL not accepting connections after restart — rebooting host"
/sbin/reboot
