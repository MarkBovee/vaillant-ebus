# Vaillant eBUS

Home Assistant integration for Vaillant heat pumps via **direct ebusd TCP** — no MQTT, no cloud.

Reads & writes 350+ eBUS registers from your heat pump, heating controller, and DHW system. Fully local, no internet required.

## Features

- Direct TCP connection to ebusd — zero MQTT setup required
- Auto-discovers all registers on connect
- 60+ entity types generated: sensor, binary_sensor, number, select, switch, climate, water_heater, calendar
- Read & write any register via HA services (`vaillant_ebus.read_parameter`, `vaillant_ebus.write_parameter`)
- Custom registers via `--enabledefine` (e.g. room humidity)
- YAML overrides for entity metadata (names, icons, units)

## Requirements

- Home Assistant 2024.6+ (recommended)
- ebusd — install as HA addon or standalone on your network
- Vaillant heat pump with eBUS adapter (network or serial)

## Installation

### HACS (recommended)

1. Go to HACS → Integrations → three-dot menu → Custom repositories
2. Repository URL: `https://github.com/MarkBovee/vaillant-ebus`
3. Category: Integration
4. Click Add, then install "Vaillant eBUS" from HACS
5. **Restart HA**
6. Go to Settings → Devices & Services → Add Integration → search "Vaillant eBUS"

### Manual

1. Copy `custom_components/vaillant_ebus/` to your HA `config/custom_components/vaillant_ebus/`
2. Restart HA
3. Add integration via Settings → Devices & Services → Add Integration → Vaillant eBUS

## ebusd addon configuration

**Settings → Add-ons → ebusd → Configuration:**

```yaml
network_device: ens:192.168.x.x:9999
seed_mqtt_cfg: false
commandline_options:
  - "--accesslevel=*"
  - "--port=8888"
  - "--enabledefine"
```

| Setting | Purpose |
|---------|---------|
| `network_device` | Your eBUS adapter (network or serial) |
| `seed_mqtt_cfg: false` | Disable MQTT — no broker needed |
| `--accesslevel=*` | Full read/write access |
| `--port=8888` | Raw TCP port — this integration connects here |
| `--enabledefine` | Allows runtime register defines (e.g. room humidity) |

Do **not** add `--mqttjson`, `--mqttint`, or `--configpath` — this integration uses raw TCP only.

## Integration setup

1. After installation & restart, go to Settings → Devices & Services → Add Integration
2. Search for "Vaillant eBUS"
3. Enter ebusd host and TCP port (default: `8888`)
4. Submit — integration connects and auto-discovers all registers
5. Devices appear within 30 seconds

### Expected devices

| Device | Circuit | Description |
|--------|---------|-------------|
| Vaillant aroTHERM heat pump | `hmu` | Heat pump telemetry |
| Vaillant CTLV2 heating control | `ctlv2` | Heating controller (zone, DHW) |
| Vaillant VWZ00 ventilation | `vwz00` | Ventilation unit |
| Vaillant system | `Broadcast` | eBUS broadcast values |
| Vaillant (global) | `global` | ebusd daemon status |

### YAML entity overrides

Create `config/vaillant_ebus/entities.yaml` to override auto-detected metadata:

```yaml
ctlv2.HwcTempDesired:
  friendly_name: "DHW Target Temperature"
  icon: "mdi:water-thermometer"
  unit: "°C"
  device_class: "temperature"
  writable: true
  min: 30
  max: 70
  step: 1
```

## Services

| Service | Description |
|---------|-------------|
| `vaillant_ebus.read_parameter` | Read a register by circuit and name |
| `vaillant_ebus.write_parameter` | Write a value with read-after-write verification |
| `vaillant_ebus.refresh` | Force re-read all active registers |
| `vaillant_ebus.rediscover` | Re-run entity discovery (finds new registers) |

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md).

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install ruff pytest
.venv/bin/ruff check .
.venv/bin/pytest -q
python3 -m compileall custom_components/vaillant_ebus/
```

## License

MIT
