# Developer Guide

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install ruff pytest
```

## Validation commands

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
python3 -m compileall custom_components/vaillant_ebus/
```

## Architecture

```
custom_components/vaillant_ebus/
├── __init__.py         # Component setup, HA services
├── config_flow.py      # Config flow (host/port input)
├── coordinator.py      # DataUpdateCoordinator, poll loop, auto-discovery
├── sensor.py           # Sensor platform entities
├── binary_sensor.py    # Binary sensor entities
├── number.py           # Number entities (writable)
├── select.py           # Select entities (writable enums)
├── switch.py           # Switch entities (writable booleans)
├── climate.py          # Climate entity (heating zone thermostat)
├── water_heater.py     # Water heater entity (DHW)
├── calendar.py         # Read-only schedule entities
├── date.py             # Date entities (holiday)
├── diagnostics.py      # HA diagnostics provider
├── backend/
│   ├── base.py         # Abstract Backend class
│   ├── tcp.py          # EbusdTcpBackend — asyncio TCP transport
│   ├── models.py       # Dataclasses (EbusdRegister, RegisterMeta, etc.)
│   ├── mapping.py      # Register metadata (friendly names, icons, units)
│   └── entity_factory.py  # Dynamic entity generation from discovery
├── brand/
│   ├── logo.png        # HACS branding
│   └── icon.png        # HACS branding
├── translations/
│   └── en.json         # English UI strings
├── const.py            # Constants
├── manifest.json       # HA manifest
├── services.yaml       # Service definitions
└── strings.json        # Config flow UI strings
```

## TCP protocol

Ebusd raw TCP uses text commands terminated by `\n`. Responses end with `\n`.

| Command | Purpose | Example response |
|---------|---------|-----------------|
| `i` | ebusd version | `version: ebusd 26.1.26.1` |
| `f` | Find all registers + values | `hmu.Hc1Temp: 32.5 °C | ...` |
| `r <circuit> <name>` | Read single register | `32.5 °C` |
| `write -c <circuit> <name> <value>` | Write register | `done` |
| `define -r "<definition>"` | Define a temporary register | `done` |

## Adding register metadata

Edit `backend/mapping.py`:

```python
"hmu.ExampleRegister": RegisterMeta(
    friendly_name="Example Register",
    device_class="temperature",
    unit="°C",
    entity_type="sensor",
    entity_category="diagnostic",
),
```

Key fields:

| Field | Purpose |
|-------|---------|
| `entity_type` | Override auto-classification: `"sensor"`, `"binary_sensor"`, `"number"`, `"select"`, `"switch"` |
| `friendly_name` | HA display name (leave `None` to auto-generate from register name) |
| `device_class` | HA device class (e.g. `"temperature"`, `"power"`, `"energy"`) |
| `enabled` | `False` to hide entity by default |
| `entity_category` | `"diagnostic"` or `"config"` for less prominent entities |
| `writable` | `True` if the register supports writes |
| `value_map` | Dictionary mapping raw values to display strings (for select/switches) |

## Custom registers (define)

Some registers aren't in the CSV database and must be defined at runtime via `define`. Example: room humidity on CTLV2.

Define format in `coordinator.py:_define_custom_registers()`:

```python
defines = [
    "r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800"
    ",value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity",
]
```

The register then appears as `ctlv2.z1RoomHumidity` and needs a mapping entry in `mapping.py`.

## Testing against live ebusd

```bash
# Quick read test
echo 'r ctlv2 Hc1Temp' | nc <ebusd-host> 8888

# Full discovery dump
echo 'f' | timeout 30 nc <ebusd-host> 8888
```
