# Vaillant eBUS

Local Home Assistant integration for Vaillant heat pumps via ebusd TCP.

**No cloud. No addon dependencies (beyond ebusd).**

## Features

- Auto-discovers 250+ registers from 4 Vaillant slaves (HMU00, CTLV2, VWZ00, NETX2)
- Entities grouped into 4 devices:
  - **aroTHERM (Heat Pump)** — COP, temperatures, pressures, fan speeds, runtimes, yields
  - **CTLV2 (Heating Control)** — water pressure, average temp, errors, hydraulic scheme
  - **Woonkamer (Z1)** — room temperature, operation mode, flow temp, heat curve, holiday schedule, away mode
  - **Boiler (DHW)** — storage temps, target temp, operation mode, cylinder params
- Climate, water heater, number, select, switch, binary sensor, date, calendar platforms
- Away mode (holiday period) switch
- Read/write services (`read_parameter`, `write_parameter`, `refresh`, `rediscover`)
- Async TCP connection with reconnect backoff

## Requirements

- Vaillant aroTHERM (or compatible) heat pump with eBUS interface
- Network eBUS adapter (e.g., from ebusd project)
- ebusd running on your network (HA addon or standalone)
- Home Assistant 2026.x or newer

## Installation

### 1. ebusd addon configuration

Install the ebusd addon from the HA addon store. Configure:

```yaml
network_device: ens:<YOUR_EBUSD_ADAPTER_IP>:9999
seed_mqtt_cfg: false
commandline_options:
  - "--accesslevel=*"
  - "--scanconfig"
  - "--port=8888"
  - "--enabledefine"
```

The addon will auto-discover all 4 Vaillant slaves.

To add register definitions not in the default CSV set (e.g., Z1RoomHumidity), place a `.csv` file in the ebusd config directory (`/etc/ebusd/vaillant/`). This requires rebuilding the addon image or mounting a custom volume.

### 2. Integration install

Copy `custom_components/vaillant_ebus/` to your HA `config/custom_components/` and restart HA.

### 3. Add integration

Settings → Devices & Services → Add Integration → Vaillant eBUS. Enter:
- **Host**: IP of your HA server (where ebusd runs)
- **Port**: 8888 (default ebusd TCP port)

## Architecture

```
Heat Pump ──eBUS──► Network Adapter ──TCP──► ebusd (port 8888)
                                                    │
                                               HA custom_component
                                               (async TCP, no MQTT)
```

## Services

| Service | Description |
|---------|-------------|
| `vaillant_ebus.read_parameter` | Read a register by circuit and name |
| `vaillant_ebus.write_parameter` | Write a value and verify |
| `vaillant_ebus.refresh` | Force re-read all registers |
| `vaillant_ebus.rediscover` | Re-run `find` and rebuild entities |

## Device / Circuit Mapping

| Device | Circuit(s) | Key entities |
|--------|-----------|--------------|
| aroTHERM (Heat Pump) | `hmu`, `Broadcast` | COP, temps, pressures, fan speeds, yields |
| CTLV2 (Heating Control) | `ctlv2` (system) | water pressure, avg temp, errors |
| Woonkamer (Z1) | `ctlv2` (Z1 sub) | room temp, heat curve, holiday, away |
| Boiler (DHW) | `ctlv2` (DHW sub) | storage temp, target temp, operation |

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest -q
python3 -m compileall custom_components/vaillant_ebus/
```

## License

Apache 2.0
