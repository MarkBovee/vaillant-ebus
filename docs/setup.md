# Setup Guide

## Prerequisites

- Home Assistant running (core or supervised)
- **ebusd** installed and running (HA addon or standalone)
- Heat pump with eBUS adapter connected to ebusd

> This integration is a client for **ebusd**. Install and configure ebusd first.

## Step 1: Install ebusd

### HA addon (recommended)

1. Go to **Settings → Add-ons → Add-on store**
2. Add external repository: `https://github.com/john30/ebusd-addon`
3. Install **ebusd**
4. Go to **Configuration** and set:

```yaml
network_device: ens:192.168.1.100:9999
seed_mqtt_cfg: false
commandline_options:
  - "--accesslevel=*"
  - "--scanconfig"
  - "--port=8888"
  - "--enabledefine"
```

| Setting | Why |
|---------|-----|
| `network_device` | Points to your eBUS adapter: `ens:<ip>:<port>` for network adapters, or a serial path like `/dev/ttyUSB0` |
| `seed_mqtt_cfg: false` | Prevents ebusd from starting its MQTT client — not needed for raw TCP |
| `--accesslevel=*` | Grants full read and write to all registers |
| `--scanconfig` | Scans for additional registers (recommended) |
| `--port=8888` | Opens the raw TCP command port — this is what the integration connects to |
| `--enabledefine` | Allows runtime `define` commands (used for custom registers like room humidity) |

> Do not add `--mqttjson`, `--mqttint`, or `--configpath` — this integration uses raw TCP only.

5. **Start** the ebusd addon.

### Standalone ebusd (no HA addon)

If ebusd runs on a separate machine or bare-metal:

```bash
ebusd --device=ens:192.168.1.100:9999 --port=8888 --accesslevel=* --enabledefine
```

## Step 2: Install this integration

Follow the [README](../README.md) — HACS or manual install.

## Step 3: Add integration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **"Vaillant eBUS"**
3. Enter your ebusd host and TCP port (default: `8888`)
4. Submit — wait 30 seconds for devices to appear

## Verifying the connection

Check raw TCP is working:

```bash
# From any machine on the same network:
echo 'i' | nc 192.168.1.100 8888
# Expected: "version: ebusd 26.x.x.x"
```

## Devices after setup

| Device | Circuit | What you get |
|--------|---------|--------------|
| Vaillant aroTHERM heat pump | `hmu` | Temperatures, pressures, energy counters, runtime, errors |
| Vaillant CTLV2 heating control | `ctlv2` | Zone temps, DHW, heating curve, schedules, operation modes |
| Vaillant VWZ00 ventilation | `vwz00` | Ventilation status, fan speeds |
| Vaillant system | `Broadcast` | Outdoor temperature, water pressure (system-wide values) |
| Vaillant (global) | `global` | ebusd daemon info, connection status |

## Register discovery behavior

- On first connect, the integration runs `find` to discover all available registers
- Each register becomes an entity — sensors, numbers, selects, switches, etc.
- Some heat pump registers only return data when the compressor is running (heating/DHW/cooling active). These show "unavailable" or "no data stored" when idle, and become enabled automatically when data appears
- Custom registers (like room humidity, `ctlv2.z1RoomHumidity`) are defined at runtime via `--enabledefine` — the integration auto-defines them on startup

## YAML overrides

To override metadata for any register, create `config/vaillant_ebus/entities.yaml`:

```yaml
hmu.CurrentConsumedPower:
  device_class: "power"
  unit: "W"
  entity_category: "diagnostic"
```
