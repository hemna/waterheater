#######################################
# Copyright (c) 2021 Maker Portal LLC
# Author: Joshua Hrisko
#######################################
#
# NEMA 17 (17HS4023) Raspberry Pi Tests
# --- rotating the NEMA 17 to test
# --- wiring and motor functionality
#
#
#######################################
#
import click
import RPi.GPIO as GPIO
from RpiMotorLib import RpiMotorLib
import time
from flask import Flask, render_template, request, jsonify
import threading
from flask import request
from flask_socketio import SocketIO, Namespace
import json
import os

################################
# RPi and Motor Pre-allocations
################################
#
#define GPIO pins
DEFAULT_STEPS_PER_DEGREE=13
DEFAULT_INITIAL_TEMPERATURE=110
CURRENT_TEMPERATURE=110
APP_NAMESPACE = '/control'

direction= 22 # Direction (DIR) GPIO Pin
step = 23 # Step GPIO Pin
EN_pin = 24 # enable pin (LOW to enable)

TEMPERATURE_FILE = '/tmp/current_temperature.json'

WEB_PORT=80

###########################
# Actual motor control
###########################
#

def motor_control(steps, clockwise=True, steptype='Full'):
    """Clockwise to increase temperature."""
    print(f"Move motor {steps} clockwise? {clockwise} type {steptype}")
    # Declare a instance of class pass GPIO pins numbers and the motor type
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(EN_pin, GPIO.OUT) # set enable pin as output
    GPIO.output(EN_pin,GPIO.LOW) # pull enable to low to enable motor
    mymotortest = RpiMotorLib.A4988Nema(direction, step, (21,21,21), "DRV8825")
    mymotortest.motor_go(
            clockwise, # True=Clockwise, False=Counter-Clockwise
            steptype, # Step type (Full,Half,1/4,1/8,1/16,1/32)
            steps, # number of steps
            #.0005, # step delay [sec]
            .005, # step delay [sec]
            True, # True = print verbose output
            .05) # initial delay [sec]
    GPIO.cleanup() # clear GPIO allocations after run


def load_temperature():
    global CURRENT_TEMPERATURE
    if os.path.exists(TEMPERATURE_FILE):
        try:
            with open(TEMPERATURE_FILE, 'r') as f:
                data = json.load(f)
                CURRENT_TEMPERATURE = data.get('current_temperature', CURRENT_TEMPERATURE)
        except Exception as e:
            CURRENT_TEMPERATURE = DEFAULT_INITIAL_TEMPERATURE
            print(f"Error loading temperature: {e}.")
            print(f"Using default temperature: {CURRENT_TEMPERATURE}")
    else:
        CURRENT_TEMPERATURE = DEFAULT_INITIAL_TEMPERATURE
        print(f"No temperature file found, using default: {CURRENT_TEMPERATURE}")
    print(f"Loadded Current temperature: {CURRENT_TEMPERATURE}")


def save_temperature():
    global CURRENT_TEMPERATURE
    print(f"Saving Current temperature: {CURRENT_TEMPERATURE} to {TEMPERATURE_FILE}")
    try:
        with open(TEMPERATURE_FILE, 'w') as f:
            json.dump({'current_temperature': CURRENT_TEMPERATURE}, f)
    except Exception as e:
        print(f"Error saving temperature: {e}")
    print(f"Saved Current temperature: {CURRENT_TEMPERATURE} to {TEMPERATURE_FILE}")


def change_temperature(degrees):
    global CURRENT_TEMPERATURE
    print(f"Changing temperature by {degrees} degrees")
    if degrees > 0:
        steps = int(degrees * DEFAULT_STEPS_PER_DEGREE)
        motor_control(steps, clockwise=False, steptype='Full')
        CURRENT_TEMPERATURE += degrees
    else:
        steps = int(degrees * DEFAULT_STEPS_PER_DEGREE)
        motor_control(abs(steps), clockwise=True, steptype='Full')
        CURRENT_TEMPERATURE += degrees
    save_temperature()
    sio.emit('temperature_status', {'message': f"Temperature changed to {CURRENT_TEMPERATURE} degrees"}, namespace=APP_NAMESPACE)
    sio.emit('temperature_update', {'temperature': CURRENT_TEMPERATURE}, namespace=APP_NAMESPACE)

def set_temperature(temperature):
    global CURRENT_TEMPERATURE
    print(f"Setting temperature to {temperature}")
    diff = temperature - CURRENT_TEMPERATURE
    if diff > 0:
        steps = int(diff * DEFAULT_STEPS_PER_DEGREE)
        motor_control(steps, clockwise=False, steptype='Full')
    else:
        steps = int(abs(diff) * DEFAULT_STEPS_PER_DEGREE)
        motor_control(steps, clockwise=True, steptype='Full')
    CURRENT_TEMPERATURE = temperature
    save_temperature()
    sio.emit('temperature_status', {'message': f"Temperature changed to {CURRENT_TEMPERATURE} degrees"}, namespace=APP_NAMESPACE)
    sio.emit('temperature_update', {'temperature': CURRENT_TEMPERATURE}, namespace=APP_NAMESPACE)

# --- Flask Web UI with SocketIO ---
flask_app = Flask(
    __name__,
      static_url_path="/static",
      static_folder="web/static",
      template_folder="web/templates")


def init_flask():
    global flask_app
    sio = SocketIO(
        flask_app,
        debug=True,
        logger=True,
        engineio_logger=True,
        async_mode='threading')

    sio.on_namespace(ControlNamespace(APP_NAMESPACE))
    return sio


class ControlNamespace(Namespace):
    def on_connect(self):
        global sio
        print("Client connected")
        sio.emit('motor_status',
                 {'message': "Connected to server"},
                 namespace=APP_NAMESPACE)

    def on_disconnect(self):
        print("Client disconnected")

    def on_message(self, sid, data):
        print(f"on_message: Received message: {data}")

    def on_move_motor(self, data):
        print(f"on_move_motor: {data}")
        print(f"data.get('steps', 100): {data.get('steps', 100)}")
        print(f"data.get('steptype', 'Full'): {data.get('steptype', 'Full')}")
        print(f"data.get('clockwise', True): {data.get('clockwise', True)}")
        steps = int(data.get('steps', 100))
        steptype = data.get('steptype', 'Full')
        clockwise = bool(data.get('clockwise', True))
        print(f"Moving motor {steps} steps, {'CW' if clockwise else 'CCW'}, {steptype}")
        #threading.Thread(target=motor_control, args=(steps, clockwise, steptype)).start()
        motor_control(steps, clockwise=clockwise, steptype=steptype)
        sio.emit('motor_status', {'message': f"Motor moving {steps} steps, {'CW' if clockwise else 'CCW'}, {steptype}"})

    def on_change_temperature(self, data):
        print(f"on_change_temperature: {data}")
        temperature = int(data.get('temperature', 1))
        change_temperature(temperature)
        sio.emit('temperature_status', {'message': f"Temperature changed to {temperature} degrees"}, namespace=APP_NAMESPACE)

    def on_set_temperature_reading(self, data):
        """Set the current temperature reading from the heater.

        This is used to set the current temperature reading from the heater.
        This is a manual override, since there is no way to read the temperature
        from the heater.

        """
        global CURRENT_TEMPERATURE
        print(f"on_set_temperature_reading: {data}")
        temperature = int(data.get('temperature', 1))
        CURRENT_TEMPERATURE = temperature
        save_temperature()
        print(f"Setting temperature to {CURRENT_TEMPERATURE}")
        sio.emit('temperature_update',
                 {'temperature': temperature},
                 namespace=APP_NAMESPACE)

    def on_set_temperature(self, data):
        """User wants to set the temperature setting to this exact value."""
        global CURRENT_TEMPERATURE
        print(f"on_set_temperature: {data}")
        temperature = int(data.get('temperature', 1))
        set_temperature(temperature)
        print(f"Setting temperature to {CURRENT_TEMPERATURE}")

@flask_app.route("/")
def index():
    global CURRENT_TEMPERATURE
    print(f"Index page requested, current temperature: {CURRENT_TEMPERATURE}")
    return render_template('index.html', initial_temperature=CURRENT_TEMPERATURE)


@click.command()
@click.option('--steps', default=100, help='Number of steps.')
@click.option('--steptype',
              type=click.Choice(['Full', '1/2', '1/4', '1/8', '1/16', '1/32']),
              default="Full",
              help="Step Type")
@click.option('--clockwise',
              type=click.BOOL,
              default=True,
              help='Rotate clockwise?.')
def main(steps, steptype, clockwise):
    print("Hello from waterheater!")
    motor_control(steps, clockwise=clockwise, steptype=steptype)


if __name__ == "__main__":
    import sys
    load_temperature()
    if len(sys.argv) > 1 and sys.argv[1].startswith('--'):
        main()
    else:
        print("init_flask()")
        sio = init_flask()
        print(f"Starting web server with SocketIO on http://0.0.0.0:{WEB_PORT} ...")
        sio.run(
            flask_app,
            debug=True,
            host='0.0.0.0',
            port=WEB_PORT,
            allow_unsafe_werkzeug=True,
        )
        print("sio.run() returned")
