## Context

EEBUS (VR921) integration limited to 4 measurements — confirmed. EBUS via ebusd provides complete heat pump telemetry. ebusd runs as HA addon on local network.

This integration adds an **ebusd TCP backend** to `vaillant_ebus`, building a custom HA component that talks directly to ebusd via its binary TCP protocol (port 8888). No MQTT broker dependency, no addon, no cloud.

Current state:
- EEBUS backend in `vaillant/` (protocol) + `custom_components/vaillant_ebus/` (HA layer)
- 4 EEBUS measurements proven, 15 described but never live
- ebusd addon runs on HA server (192.168.1.100), accessible via TCP port 8888
- 362 registers discovered via `find`, organised in circuits: `hmu`, `ctlv2`, `Broadcast`, `scan.*`, `vwz`
- Key heat pump registers (compressor speed, flow/return temp, pressure, fan speed, EEV) ARE defined in CSVs but currently show "no data stored" (heat pump idle — summer, no DHW demand)

## Goals / Non-Goals

**Goals:**
- TCP backend: `backend/` directory with pluggable transport (TCP/EEBUS)
- Auto-discovery: connect to ebusd, run `find` command, auto-generate entities from all 362 registers
- Full entity coverage: sensors, binary sensors, numbers, selects, switches, buttons
- HA services: `read_parameter`, `write_parameter`, `refresh`, `rediscover`
- Write verification: read-after-write with rollback on rejection
- Error handling: connection lost, ebusd restart, timeout, unknown register
- Diagnostics: firmware, adapter status, discovered circuits, register count
- Testing: unit tests (>95% core), integration tests (fake ebusd TCP server)
- EEBUS supplement: optional, adds 4 energy measurements alongside ebusd data

**Non-Goals:**
- No direct eBUS protocol implementation (always through ebusd)
- No MQTT broker dependency (direct TCP to ebusd)
- No cloud dependency (all local)
- No changes to EEBUS code (retained as optional supplement)

## Decisions

1. **TCP direct over MQTT** — Connect to ebusd via TCP port 8888 using async TCP sockets. Rationale: one less service dependency, simpler architecture, faster discovery (single `find` call vs waiting for MQTT topics), direct write via `write -c <circuit> <name> <value>`.

2. **Backend abstraction** — Abstract base class `Backend` in `backend/base.py`. `EbusdTcpBackend` and `EebusBackend` subclasses. Coordinator selects backend based on config.

3. **Discovery via `find` command** — On startup, connect to ebusd and run `find` (lists all 362 registers with current values). Parse output to build entity catalog. Rationale: single TCP call gives complete picture, no timing window needed, includes value/availability in one response.

4. **Poll strategy** — `DataUpdateCoordinator` polls key registers at configurable interval (default 30s). Poll list defined in code (not all 362 — only ones that change). Rationale: keep bus traffic low, only watch what matters.

5. **Write via direct TCP command** — `write -c <circuit> <name> <value>` over TCP socket. Read-after-write for verification. Rationale: verified in `ebusctl` documentation, no MQTT publish needed.

6. **entities.yaml** — Loaded from `config/vaillant_ebus/entities.yaml`. Overrides auto-detected metadata (friendly name, icon, unit, device_class, writable, min/max/step). Rationale: user-tunable without code changes.

7. **HA services over entities as primary control** — Services (`read_parameter`, `write_parameter`, `refresh`, `rediscover`) work regardless of entity configuration. Number/Select/Switch/Button entities are for UI convenience.

## ebusd TCP protocol reference

### Connection
- Host: `192.168.1.100` (configurable via config flow)
- Port: `8888` (configurable, default 8888)
- Protocol: plain TCP, text commands terminated by `\n`, text responses terminated by `\n`

### Commands
| Command | Purpose | Example response |
|---------|---------|-----------------|
| `i` | Info (version) | `version: ebusd 26.1.26.1` |
| `s` | Signal status | `signal acquired, 173 symbols/sec, 5 masters` |
| `f` | Find all registers + values | `Broadcast Outsidetemp = 17.477` (362 lines) |
| `r <circuit> <name>` | Read single register | `22.5` or `ERR: element not found` |
| `r <circuit> <name> <field>` | Read single field | `22.5` |
| `write -c <circuit> <name> <value>` | Write value | `done` or `ERR: ...` |
| `grab` | Start raw bus capture | |
| `grab result` | Get captured messages | |
| `scan result` | List scanned slaves | |

### Read value format
Value-only responses are plain strings:
```
22.5
21
off
auto;21.0;-;-;0;1;1;0;0;0
```

Multi-field registers (like `Status01`) return semicolon-separated values matching the field order.

### Write format
```
write -c ctlv2 HwcTempDesired 45
```
Response: `done` on success, `ERR: ...` on failure. Read-after-write confirms value took effect.

## Live confirmed data

Captured via TCP `find` command against live ebusd + `r` reads.

### Circuit `hmu` (Hydraulic Module Unit)
| Register | Fields | Status | Notes |
|----------|--------|--------|-------|
| `Status01` | temp, temp_1-4, pumpstate | **LIVE**: 22.5;22.5;-;-;-;off | |
| `SetMode` | hcmode, flowtempdesired, ... | **LIVE**: auto;21.0;... | All writable params |
| `StatusCirPump` | value | **LIVE**: on | |
| `Currenterror` | error, error_1-4 | **LIVE**: -;-;-;-;- | No errors |
| `FlowTemp` | value | Defined, no data | Only when heating active |
| `FlowTemperature` | value | Defined, no data | Alias? |
| `RunDataCompressorSpeed` | value | Defined, no data | Compressor idle |
| `RunDataHighPressure` | value | Defined, no data | Compressor idle |
| `RunDataLowPressure` | value | Defined, no data | Compressor idle |
| `RunDataCompressorInletTemp` | value | Defined, no data | Compressor idle |
| `RunDataCompressorOutletTemp` | value | Defined, no data | Compressor idle |
| `RunDataEEVOutletTemp` | value | Defined, no data | Compressor idle |
| `RunDataEEVPositionAbs` | value | Defined, no data | Compressor idle |
| `RunDataFan1Speed` | value | Defined, no data | Compressor idle |
| `RunDataFan2Speed` | value | Defined, no data | Compressor idle |
| `RunDataStatuscode` | value | Defined, no data | Compressor idle |
| `RunDataAirInletTemp` | value | Defined, no data | Compressor idle |
| `RunDataBuildingCPumpPower` | value | Defined, no data | Compressor idle |
| `CurrentConsumedPower` | value | Defined, no data | Compressor idle |
| `CurrentYieldPower` | value | Defined, no data | Compressor idle |
| `CurrentCompressorUtil` | value | Defined, no data | Compressor idle |
| `SupplyTempWeighted` | value | Defined, no data | |
| `TotalEnergyUsage` | value | Defined, no data | |
| `CopHc` | value | Defined, no data | |
| `CopHwc` | value | Defined, no data | |
| `CopCooling` | value | Defined, no data | |
| `YieldHc` | value | Defined, no data | |
| `YieldHcDay` | value | Defined, no data | |
| `YieldHwc` | value | Defined, no data | |
| `YieldCoolDay` | value | Defined, no data | |
| `RunStatsCompressorHours` | value | Defined, no data | |
| `RunStatsCompressorStarts` | value | Defined, no data | |
| `RunStatsFan1Hours` / `Fan2Hours` | value | Defined, no data | |
| `PowerConsumptionHmu` | value | Defined, no data | |
| `BuildingCircuitFlow` | value | Defined, no data | |
| `DateTime` | value | Defined, no data | |

### Circuit `ctlv2` (Heating Control)
| Register | Fields | Status | Notes |
|----------|--------|--------|-------|
| `Hc1ActualFlowTempDesired` | value | **LIVE**: 21 | Current flow temp setpoint |
| `Hc1PumpStatus` | value | **LIVE**: 1 | HC1 pump running |
| `Z1ActualRoomTempDesired` | value | **LIVE**: 20 | Zone 1 target |
| `Z1DayTemp` | value | **LIVE**: 20 | |
| `Z1NightTemp` | value | **LIVE**: 19 | |
| `Z1OpMode` | value | **LIVE**: day | |
| `Hc1FlowTemp` | value | Defined, no data | |
| `Hc1HeatCurve` | value | Defined, no data | |
| `Hc1MaxFlowTempDesired` | value | Defined, no data | |
| `Hc1MinFlowTempDesired` | value | Defined, no data | |
| `Hc1SummerTempLimit` | value | Defined, no data | |
| `Hc1RoomTempSwitchOn` | value | Defined, no data | |
| `Hc1Status` | value | Defined, no data | |
| `Hc1CircuitType` | value | Defined, no data | |
| `Hc2*` | ... | All defined, no data | HC2 not configured |
| `Hc3*` | ... | Some live (HeatCurve) | |
| `HwcTempDesired` | value | Defined, no data | DHW not active |
| `HwcStorageTemp` | value | Defined, no data | |
| `HwcOpMode` | value | Defined, no data | |
| `HwcMaxFlowTempDesired` | value | Defined, no data | |
| `WaterPressure` | value | Defined, no data | |
| `PrEnergySum*` | value | Defined, no data | |
| `PrFuelSum*` | value | Defined, no data | |
| `Z2*` / `Z3*` | ... | All defined, no data | Zone 2/3 not configured |
| `CcTimer_*` | htm, htm_1 | **LIVE**: timer configs | |
| `AdaptHeatCurve` | value | **LIVE**: no | |
| `Currenterror` | error, error_1-4 | **LIVE**: no errors | |
| `SystemFlowTemp` | value | Defined, no data | |

### Circuit `Broadcast` (System)
| Register | Fields | Status |
|----------|--------|--------|
| `Outsidetemp` | value | **LIVE**: 17.5°C |
| `Vdatetime` | time, date | **LIVE**: current |
| `Datetime` | value | Defined, no data |
| `Error` | value | Defined, no data |

### Circuit `vwz` (Valve)
| Register | Fields | Status |
|----------|--------|--------|
| `TestHwcTemp` | value | Defined, no data |
| `TestOutdoorTemp` | value | Defined, no data |
| `TestThreeWayValve` | value | Defined, no data |

### Circuit `scan.*` (Discovered slaves)
| Register | Value |
|----------|-------|
| `scan.08` | Vaillant;HMU00;0522;5103 |
| `scan.15` | Vaillant;CTLV2;0514;1104 |
| `scan.76` | Vaillant;VWZ00;0522;5103 |
| `scan.f6` | Vaillant;NETX2;4039;5703 |

### Circuit `global` (ebusd daemon)
| Register | Value |
|----------|-------|
| `running` | true |
| `signal` | true |
| `scan` | finished |
| `uptime` | 305s |
| `version` | ebusd 26.1.26.1 |

## Identified hardware

| Address | Type | HW | SW | Week/Year |
|---------|------|----|----|-----------|
| 08 | HMU00 (Hydraulic Module Unit) | 5103 | 0522 | wk29-2022 |
| 15 | CTLV2 (Heating Control) | 1104 | 0514 | wk23-2022 |
| 76 | VWZ00 (Valve/Zone) | 5103 | 0522 | wk25-2022 |
| f6 | NETX2 (Network) | 5703 | 4039 | wk07-2023 |

## Entity grouping strategy
- **1 HA device** "Vaillant eBUS" (identifiers: `ebusd_<serial>`)
- Groups per circuit with English names:
  - `hmu` → "Heat Pump" (HMU = Hydraulic Module Unit)
  - `ctlv2` → "Control" (heating circuit control, all writable params)
  - `Broadcast` → "System"
  - `vwz` → "Valve"
  - `scan.*` → not exposed as entities (internal device info)
- Entity unique ID: `ebusd_<circuit>_<name>[_<field>]`
- Entity name: `<Group> <Parameter>` (e.g. "Heat Pump Compressor Speed")

## Local development workflow
1. Custom_component connects directly to ebusd TCP (192.168.1.100:8888)
2. Use `f` and `r` commands for testing via Python asyncio
3. No local ebusd needed — data comes from HA server
4. `.env` contains SSH credentials for emergency access

## entities.yaml format
```yaml
# <ha-config>/vaillant_ebus/entities.yaml
# Overrides per circuit.name.field
ctlv2.HwcTempDesired:
  friendly_name: "DHW Target Temperature"
  icon: "mdi:water-thermometer"
  unit: "°C"
  device_class: "temperature"
  writable: true
  min: 30
  max: 70
  step: 1

ctlv2.Z1DayTemp:
  friendly_name: "Day Temperature"
  icon: "mdi:thermometer"
  unit: "°C"
  device_class: "temperature"
  writable: true
  min: 5
  max: 30
  step: 0.5
```

## Poll strategy
- Main poll interval: 30s (configurable)
- Always poll (changes often): `Broadcast Outsidetemp`, `hmu Status01`, `hmu SetMode`, `ctlv2 Hc1PumpStatus`, `ctlv2 Z1OpMode`
- Poll if compressor running: all `hmu RunData*` + `hmu FlowTemp` + `hmu CurrentConsumedPower`
- Rarely poll (6h): `ctlv2 CcTimer*`, `scan.*`, static config registers
- Discover poll list from `find` output: registers with data get shorter interval, "no data stored" registers get longer interval or are skipped

## Risks / Trade-offs
- **ebusd restart** — TCP connection drops. Mitigation: auto-reconnect with exponential backoff (1s-60s).
- **Write without confirmation** — ebusd may accept write but heat pump rejects it. Mitigation: read-after-write verification.
- **Poll bus load** — Too many polled registers generate eBUS traffic. Mitigation: only poll registers that change (detected by comparing against previous `find` snapshot).
- **Migration from EEBUS** — Entity unique_ids change. Mitigation: phase migration, document manual entity cleanup.
- **Heat pump idle** — Many registers show "no data stored" when compressor is off. Mitigation: mark entities as unavailable when no data, auto-enable when data appears.
- **ebusd version differences** — Different ebusd versions may have different command syntax. Mitigation: test against min supported version (26.x), document known-good versions.
