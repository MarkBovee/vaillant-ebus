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

The addon config directory on the host (`/addon_configs/b4d7ad18_ebusd/`) is mounted into the ebusd container as the config path (`/etc/ebusd/`). Placing `.csv` files in `vaillant/` subdirectory adds register definitions. To deploy custom CSV files:

```bash
# Compile latest ebusd-configuration locally
git clone https://github.com/john30/ebusd-configuration.git /tmp/ebusd-conf
cd /tmp/ebusd-conf && npm install && npm run compile-en
# Upload the compiled CSV set to the addon config dir
scp -r outcsv/@ebusd/ebus-typespec/vaillant/*.csv \
  hass-host:/addon_configs/b4d7ad18_ebusd/vaillant/
# Restart the ebusd addon
```

**Warning**: `--configpath=/config` in commandline_options overrides the default config path and breaks standard CSV loading — do not use.

To replace the whole CSV set: upload compiled CSVs to the addon config dir as described above. The addon mounts this directory directly as `/etc/ebusd/` inside the container.

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

## Register Discovery

The integration uses ebusd's `find` command to discover available registers. Only registers with data OR those listed in `REGISTER_MAP` (mapping.py) become entities.

Registers not in `find` output but known by name can be read directly via `read -c <circuit> <name>`. The coordinator's `_fallback_read` mechanism attempts this for all REGISTER_MAP entries that weren't found by `find`.

This two-pass approach handles registers that only appear when the heat pump is active (compressor running) or that are available by name but not auto-discovered.

Not all registers defined in circuit-specific CSV files are actually supported by every hardware revision. If a register returns `ERR: element not found` despite being in the CSV, the firmware variant likely omits that sensor.

### ebusd TCP commands

| Command | Purpose |
|---------|---------|
| `f` | List all known registers |
| `r -c <circuit> <name>` | Read a register |
| `i` | Daemon info (version, slaves, loaded CSVs) |
| `scan <address>` | Scan a specific slave for new messages |
| `scan full` | Scan all slaves |
| `l` | Listen for bus traffic |

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
