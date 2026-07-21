# Setup Guide

## Prerequisites

- Home Assistant running (core or supervised)
- ebusd installed — either as HA addon or standalone on your network
- Heat pump with eBUS adapter connected to ebusd
- ebusd configured with `--port=8888` (raw TCP, no MQTT needed)

## ebusd addon configuration

Navigate to **Settings → Add-ons → ebusd → Configuration** and set:

```yaml
network_device: ens:192.168.1.101:9999
seed_mqtt_cfg: false
commandline_options:
  - "--accesslevel=*"
  - "--port=8888"
  - "--enabledefine"
```

### Explanation

| Setting | Why |
|---------|-----|
| `network_device` | Points to your eBUS adapter: `ens:<ip>:<port>` for network adapters, or a serial path like `/dev/ttyUSB0` |
| `seed_mqtt_cfg: false` | Prevents ebusd from starting its MQTT client — not needed for raw TCP |
| `--accesslevel=*` | Grants full read and write to all registers |
| `--port=8888` | Opens the raw TCP command port — this is what the integration connects to |
| `--enabledefine` | Allows runtime `define` commands (used for custom registers like room humidity) |

> Do not add `--mqttjson`, `--mqttint`, `--configpath`, or `--scanconfig` — the integration handles everything via raw TCP.

### Standalone ebusd (no HA addon)

If ebusd runs on a separate machine or bare-metal:

```bash
ebusd --device=ens:192.168.1.101:9999 --port=8888 --accesslevel=* --enabledefine
```

## Integration setup steps

1. Install the integration via HACS or manually (see [README](../README.md))
2. **Restart HA** if not done yet
3. Go to **Settings → Devices & Services → Add Integration**
4. Search for **"Vaillant eBUS"**
5. Enter your ebusd host and TCP port (default: `8888`)
6. Submit — wait 30 seconds for devices to appear

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
