#!/usr/bin/env python3
"""Quick CLI to send commands to the local waterheater app via SocketIO.

Usage:
    ./ctl.py cancel_start_timer
    ./ctl.py cancel_timer
    ./ctl.py set_temperature 97
    ./ctl.py force_reset
"""
import sys
import socketio

COMMANDS_NO_ARGS = ["cancel_start_timer", "force_reset", "start_progressive_now", "stop_progressive_now"]

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    data = {}
    if cmd == "set_temperature" and len(sys.argv) > 2:
        data = {"temperature": int(sys.argv[2])}
    elif cmd == "change_temperature" and len(sys.argv) > 2:
        data = {"temperature": int(sys.argv[2])}
    elif cmd == "set_timer" and len(sys.argv) > 2:
        data = {"duration_minutes": float(sys.argv[2])}

    sio = socketio.SimpleClient()
    sio.connect("http://localhost", namespace="/control", wait_timeout=3)
    sio.emit(cmd, data)
    import time; time.sleep(0.5)
    sio.disconnect()
    print(f"✓ {cmd} {data or ''}")

if __name__ == "__main__":
    main()
