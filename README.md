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
- **ebusd** — eBUS daemon, installed and running ([upstream](https://github.com/john30/ebusd))
- Vaillant heat pump with eBUS adapter

> This integration is a **client for ebusd**. You need ebusd running before adding this integration.

### eBUS adapter

The heat pump communicates over a two-wire eBUS. You need an adapter to connect it to your network:

- **Network adapter** (recommended): Vaillant VR921 or third-party network eBUS adapter. Gets its own IP on your LAN. Address format: `ens:192.168.x.x:9999`
- **Serial adapter**: USB-to-eBUS or serial adapter connected to the HA server. Address format: `/dev/ttyUSB0`

Known compatible heat pumps: aroTHERM, aroTHERM plus, VWL series. Other Vaillant models with eBUS should work too — the integration auto-discovers whatever registers the heat pump exposes.

## Step 1: Install ebusd

ebusd is available as an HA addon or standalone. The addon is the easiest route.

### HA addon (recommended)

1. Go to **Settings → Add-ons → Add-on store**
2. Click the **three-dot menu → Repositories**, add: `https://github.com/LukasGrebe/ha-addons/` (HA wrapper for [john30/ebusd](https://github.com/john30/ebusd))
3. **Install ebusd** from the addon store
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
| `--accesslevel=*` | Full read/write access to all registers |
| `--scanconfig` | Scans for additional registers during startup (recommended) |
| `--port=8888` | Raw TCP command port — this integration connects to this |
| `--enabledefine` | Allows runtime register creation (needed for room humidity) |

Do **not** add `--mqttjson`, `--mqttint`, or `--configpath`.

5. **Start** the addon and wait until it shows **"running"** in the addon dashboard
6. Verify: open the addon log — you should see no errors. If you see `ERR: element not found` for some registers, that is normal — your hardware just doesn't support them.

### Standalone

If ebusd runs on a separate machine or bare-metal:

```bash
ebusd --device=ens:192.168.1.100:9999 --port=8888 --accesslevel=* --enabledefine
```

> Replace `192.168.1.100:9999` with your eBUS adapter's actual IP and port.

## Step 2: Install this integration

### HACS (recommended)

1. Go to **HACS → Integrations → three-dot menu → Custom repositories**
2. Repository URL: `https://github.com/MarkBovee/vaillant-ebus`
3. Category: **Integration**
4. Click **Add**, then install **"Vaillant eBUS"** from HACS
5. **Restart HA**

### Manual

1. Copy `custom_components/vaillant_ebus/` to your HA `config/custom_components/vaillant_ebus/`
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

### YAML entity overrides

Create `config/vaillant_ebus/entities.yaml` to override auto-detected metadata:

```yaml
ctlv2.HwcTempDesired:
  friendly_name: "DHW Target Temperature"
  icon: "mdi:water-thermometer"
  unit: "°C"
  device_class: "temperature"
```

Available override keys: `friendly_name`, `icon`, `unit`, `device_class`, `entity_category`, `entity_type`, `enabled`, `writable`, `min`, `max`, `step`, `options`.

## Services

| Service | Description |
|---------|-------------|
| `vaillant_ebus.read_parameter` | Read a register by circuit and name |
| `vaillant_ebus.write_parameter` | Write a value with read-after-write verification |
| `vaillant_ebus.refresh` | Force re-read all active registers |
| `vaillant_ebus.rediscover` | Re-run entity discovery (finds new registers) |

## Updating

HACS notifies you when a new release is available. To update:

1. Go to **HACS → Integrations → Vaillant eBUS**
2. Click **"Update"** (if available)
3. **Restart HA**

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md).

## License

Apache 2.0
