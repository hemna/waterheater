# waterheater

Water heater control using a NEMA 17 stepper motor (17HS4023) on a Raspberry Pi, with a web UI for temperature control.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Raspberry Pi with GPIO access when using motor control

## Install

With uv:

```bash
uv sync
```

With pip:

```bash
pip install -e .
```

## Run the app

**Web server** (Flask + SocketIO on port 80):

```bash
uv run python main.py
```

Or with pip:

```bash
python main.py
```

Then open http://localhost/ (or your Pi’s IP) in a browser. On Linux, binding to port 80 may require `sudo`.

**CLI motor test** (steps only, no web server):

```bash
uv run python main.py --steps 100 --steptype Full --clockwise
```

Options: `--steps`, `--steptype` (Full, 1/2, 1/4, 1/8, 1/16, 1/32), `--clockwise` / `--no-clockwise`.
