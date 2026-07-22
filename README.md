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

## Prerequisites

- Home Assistant 2025.1+
- **ebusd** — eBUS daemon, installed and running
- Vaillant heat pump with eBUS adapter (network or serial)

> This integration is a **client for ebusd**. You need ebusd running before adding this integration.

## Step 1: Install ebusd

ebusd is available as an HA addon or standalone. The addon is the easiest route.

### HA addon (recommended)

1. Go to **Settings → Add-ons → Add-on store**
2. Add this repository as an external addon: `https://github.com/john30/ebusd-addon`
3. Install **ebusd**
4. Go to **Configuration** and set:

```yaml
network_device: ens:192.168.x.x:9999
seed_mqtt_cfg: false
commandline_options:
  - "--accesslevel=*"
  - "--scanconfig"
  - "--port=8888"
  - "--enabledefine"
```

| Setting | Purpose |
|---------|---------|
| `network_device` | Your eBUS adapter: `ens:<ip>:<port>` for network adapters, or `/dev/ttyUSB0` for serial |
| `seed_mqtt_cfg: false` | Disable MQTT — not needed |
| `--accesslevel=*` | Full read/write access |
| `--scanconfig` | Scans for additional registers (recommended) |
| `--port=8888` | Raw TCP port — this integration connects here |
| `--enabledefine` | Allows runtime register defines (e.g. room humidity) |

Do **not** add `--mqttjson`, `--mqttint`, or `--configpath`.

5. **Start** the ebusd addon
6. Verify it's running: open the addon log — you should see no errors

### Standalone

If ebusd runs on a separate machine or bare-metal:

```bash
ebusd --device=ens:192.168.1.100:9999 --port=8888 --accesslevel=* --enabledefine
```

## Step 2: Install this integration

### HACS (recommended)

1. Go to **HACS → Integrations → three-dot menu → Custom repositories**
2. Repository URL: `https://github.com/MarkBovee/vaillant-ebus`
3. Category: **Integration**
4. Click **Add**, then install **"Vaillant eBUS"** from HACS
5. **Restart HA**

### Manual

1. Copy `custom_components/vaillant_ebus/` to `config/custom_components/vaillant_ebus/`
2. Restart HA

## Step 3: Add integration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **"Vaillant eBUS"**
3. Enter your ebusd host and TCP port (default: `8888`)
4. Submit — the integration connects and auto-discovers all registers
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

Apache 2.0
