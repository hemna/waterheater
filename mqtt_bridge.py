"""MQTT bridge for waterheater — publishes state and accepts commands via MQTT.

Connects to a broker and exposes all waterheater functionality over MQTT topics:
  Publish:   waterheater/state      — full JSON state on every change + heartbeat
  Publish:   waterheater/history    — heater ON/OFF history (retained)
  Publish:   waterheater/chart_data — chart data response (not retained)
  Subscribe: waterheater/cmd/<action> — JSON payload triggers the corresponding action

Commands (waterheater/cmd/<action>):
  set_temperature         {"temperature": int}
  change_temperature      {"degrees": int}
  set_temperature_reading {"temperature": int}
  set_timer               {"duration_minutes": float}
  force_reset             {}
  start_progressive       {}
  stop_progressive        {}
  set_ldr_auto_timer      {"enabled": bool}
  set_ldr_progressive     {"enabled": bool}
  set_progressive_floor   {"temperature": int}
  set_off_timer_minutes   {"minutes": int}
  set_start_timer         {"duration_minutes": float, "intermediate_temperature": int,
                           "reset_duration_minutes": float}
  cancel_start_timer      {}
  cancel_off_timer        {}
  move_motor              {"steps": int, "steptype": str, "clockwise": bool}
  get_history             {}
  get_chart_data          {"period": "day|week|month|year", "offset": int}

Broker settings come from environment variables (with safe local defaults):
  MQTT_BROKER, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD, MQTT_CLIENT_ID
  MQTT_TLS=1 enables TLS (wraps the socket; use with MQTT_PORT=8883)
"""

import json
import os
import threading
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None
    print("WARNING: paho-mqtt not installed — MQTT bridge disabled")


MQTT_BROKER = os.environ.get("MQTT_BROKER", "cloud.hemna.com")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "waterheater")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "waterheater")
MQTT_CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "waterheater-pi")
MQTT_USE_TLS = os.environ.get("MQTT_TLS", "").strip().lower() in ("1", "true", "yes")
MQTT_TOPIC_STATE = "waterheater/state"
MQTT_TOPIC_HISTORY = "waterheater/history"
MQTT_TOPIC_CHART_DATA = "waterheater/chart_data"
MQTT_TOPIC_CMD = "waterheater/cmd/#"
MQTT_HEARTBEAT_INTERVAL = 30  # seconds

# Command topics → handler mapping (set by init)
_cmd_handlers = {}
_get_state_fn = None
_get_history_fn = None
_client = None
_connected = False


def _on_connect(client, userdata, flags, reason_code, properties):
    global _connected
    if reason_code == 0:
        print(f"MQTT: connected to {MQTT_BROKER}:{MQTT_PORT}")
        _connected = True
        client.subscribe(MQTT_TOPIC_CMD)
        # Publish current state and history immediately on connect
        publish_state()
        # Defer history publish to allow init to complete
        import threading
        threading.Timer(2.0, _publish_initial_history).start()
    else:
        print(f"MQTT: connection failed (rc={reason_code})")
        _connected = False


def _publish_initial_history():
    """Publish history after connection is established."""
    if _get_history_fn:
        events, stats = _get_history_fn()
        publish_history(events, stats)


def _on_disconnect(client, userdata, flags, reason_code, properties):
    global _connected
    _connected = False
    if reason_code != 0:
        print(f"MQTT: unexpected disconnect (rc={reason_code}), will auto-reconnect")


def _on_message(client, userdata, msg):
    """Route incoming MQTT commands to the appropriate handler."""
    # Extract action from topic: waterheater/cmd/<action>
    parts = msg.topic.split("/")
    if len(parts) < 3 or parts[0] != "waterheater" or parts[1] != "cmd":
        return
    action = parts[2]

    # Parse payload
    try:
        if msg.payload:
            data = json.loads(msg.payload.decode("utf-8"))
        else:
            data = {}
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"MQTT: bad payload for {action}: {e}")
        return

    handler = _cmd_handlers.get(action)
    if handler:
        print(f"MQTT: cmd/{action} → {data}")
        try:
            handler(data)
        except Exception as e:
            print(f"MQTT: error handling {action}: {e}")
    else:
        print(f"MQTT: unknown command '{action}'")


def publish_state():
    """Publish current full state to MQTT. Safe to call from any thread."""
    if _client is None or not _connected or _get_state_fn is None:
        return
    try:
        state = _get_state_fn()
        payload = json.dumps(state)
        _client.publish(MQTT_TOPIC_STATE, payload, qos=1, retain=True)
    except Exception as e:
        print(f"MQTT: publish error: {e}")


def publish_history(events: list, stats: dict):
    """Publish heater history to MQTT. Called on heater transitions."""
    if _client is None or not _connected:
        return
    try:
        payload = json.dumps({"events": events, "stats": stats})
        _client.publish(MQTT_TOPIC_HISTORY, payload, qos=1, retain=True)
    except Exception as e:
        print(f"MQTT: history publish error: {e}")


def publish_chart_data(period: str, offset: int, data: dict):
    """Publish chart data response to MQTT."""
    if _client is None or not _connected:
        return
    try:
        payload = json.dumps({"period": period, "offset": offset, "data": data})
        _client.publish(MQTT_TOPIC_CHART_DATA, payload, qos=1, retain=False)
    except Exception as e:
        print(f"MQTT: chart_data publish error: {e}")


def _heartbeat_loop():
    """Periodically publish state as a heartbeat."""
    while True:
        time.sleep(MQTT_HEARTBEAT_INTERVAL)
        publish_state()


def init(get_state_fn, cmd_handlers: dict, get_history_fn=None):
    """Initialize the MQTT bridge.

    Args:
        get_state_fn: callable returning a dict with full current state
        cmd_handlers: dict mapping command names to handler callables
                      e.g. {"set_temperature": fn, "force_reset": fn, ...}
        get_history_fn: callable returning (events_list, stats_dict) tuple
    """
    global _client, _get_state_fn, _cmd_handlers, _get_history_fn

    if mqtt is None:
        print("MQTT: paho-mqtt not available, bridge not started")
        return

    if MQTT_USERNAME == "waterheater" and MQTT_PASSWORD == "waterheater":
        print("WARNING: MQTT using default credentials — set MQTT_USERNAME/MQTT_PASSWORD env vars")
    if MQTT_USE_TLS:
        print("MQTT: TLS enabled")

    _get_state_fn = get_state_fn
    _cmd_handlers = cmd_handlers
    _get_history_fn = get_history_fn

    _client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        protocol=mqtt.MQTTv311,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    if MQTT_USE_TLS:
        _client.tls_set()
    _client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    _client.on_connect = _on_connect
    _client.on_disconnect = _on_disconnect
    _client.on_message = _on_message

    # Enable auto-reconnect
    _client.reconnect_delay_set(min_delay=1, max_delay=30)

    def _connect_loop():
        """Keep trying to connect until success, then loop_forever handles reconnect."""
        while True:
            try:
                print(f"MQTT: attempting connect to {MQTT_BROKER}:{MQTT_PORT}...")
                _client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                print("MQTT: connect() returned, entering loop_forever")
                _client.loop_forever()
            except Exception as e:
                print(f"MQTT: connection error ({type(e).__name__}: {e}), retrying in 5s...")
                time.sleep(5)

    threading.Thread(target=_connect_loop, daemon=True).start()
    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    print(f"MQTT: bridge starting → {MQTT_BROKER}:{MQTT_PORT}")
