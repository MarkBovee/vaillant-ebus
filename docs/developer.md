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
├── datetime.py         # Datetime entities
├── diagnostics.py      # HA diagnostics provider
├── backend/
│   ├── ebus_service.py # EbusService — asyncio TCP transport
│   ├── discovery_service.py # DeviceGraph construction from ebusd find output
│   ├── register_service.py # Register parsing, reads, writes, and writeability
│   ├── models.py       # Dataclasses (EbusdRegister, RegisterMeta, etc.)
│   ├── mapping.py      # Register metadata (friendly names, icons, units)
│   └── entity_factory.py # Dynamic entity generation from DeviceGraph
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
| `f -a` | Find all message types and values | `hmu Hc1Temp = 32.5` |
| `read -c <circuit> <name>` | Read a single register | `32.5` |
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

### Date registers (manual cooling start/end)

The manual cooling start/end dates (myVaillant "cool until [date]") are defined
the same way, but use the `HDA:3` date field type (day;month;year with the year
byte as year−2000, no BCD) plus an `IGN:4` skip of the echo prefix, matching the
holiday/away date registers:

```python
defines = [
    "r5,ctlv2,ManualCoolingStartDate,ManualCoolingStartDate,31,15,B524"
    ",02000000da00,value,,IGN:4,,,,value,,HDA:3",
    "r5,ctlv2,ManualCoolingEndDate,ManualCoolingEndDate,31,15,B524"
    ",02000000db00,value,,IGN:4,,,,value,,HDA:3",
    # write route: separate w-define on the 0201... write-sub with value,m
    "w,ctlv2,ManualCoolingStartDate,ManualCoolingStartDate,31,15,B524"
    ",02010000da00,value,m,HDA:3",
    "w,ctlv2,ManualCoolingEndDate,ManualCoolingEndDate,31,15,B524"
    ",02010000db00,value,m,HDA:3",
]
```

These derive from `john30/ebusd-configuration` issue #644
(`@ext(0xda, 0)` / `@ext(0xdb, 0)` on the `_720` r_1 base) and were verified on a
CTLV2 `SW0514`/`HW1104`. The write route uses the `0201...` write-sub (w_1-base)
with a `value,m,HDA:3` field; `write_register` then accepts `DD.MM.YYYY` values.
The datetime platform exposes them as read/write `DateTimeEntity` instances.

## Testing against live ebusd

```bash
# Quick read test
echo 'r ctlv2 Hc1Temp' | nc <ebusd-host> 8888

# Full discovery dump
echo 'f' | timeout 30 nc <ebusd-host> 8888
```
