## Context

Current coordinator uses `find` (ebusd `f` command) for all data collection. `find` performs a bus broadcast — fast but incomplete: ~20 HMU registers return "no data stored" despite having live values accessible via direct `read`. This affects compressor power (CurrentConsumedPower), humidity (MaxRoomHumidity), and all COP/energy integral registers.

Additionally, ebusd returns register definitions for HC2, HC3, Z2, Z3 even though this Vaillant system has only HC1+Z1. These entities clutter the registry with "unavailable" states.

Holiday/away mode currently requires manual date-set and temperature-set entities. A single on/off switch would match the myPyllant user experience.

## Goals / Non-Goals

**Goals:**
- All known (REGISTER_MAP) registers show live values regardless of `find` completeness
- HC2/HC3/Z2/Z3 entities not created (2+ zones nonexistent)
- Away mode controllable via single switch entity
- Humidity and compressor power operational without cloud fallback
- Clear entity_category classification: diagnostic for stats/config, none for primary sensors

**Non-Goals:**
- Full per-subsystem device hierarchy (HC1 device, DHW device, etc.) — one device per circuit suffices
- Historical data recovery for idle periods
- Dynamic zone detection (HcXCircuitType=inactive → auto-hide)

## Decisions

### D1: Find + targeted read fallback, not full sequential reads
- Coordinator runs one `find` per interval (fast bulk), then iterates REGISTER_MAP entries that got None and does individual `read -c <circuit> <name>` for each
- ~20 fallback reads, ~2s total added latency per poll cycle
- Alternative considered: full sequential read for all registers — rejected, too slow (254 × 200ms = 50s)

### D2: Static filter for HC2/HC3/Z2/Z3 in `_is_hidden_register`
- Register name prefix match (`hc2_`, `hc3_`, `z2_`, `z3_`) in entity_factory.py
- Alternative considered: dynamic check via `Hc2CircuitType=inactive` — too complex, adds state dependency
- Downside: multi-zone users must remove filter — acceptable, this integration targets single-zone Vaillant

### D3: Away mode as switch entity, not automation blueprint
- `switch.py` reads Z1HolidayStartPeriod + Z1HolidayEndPeriod to derive state
- ON: writes today to Start, (today+7d or configurable) to End, Z1HolidayTemp
- OFF: writes 01.01.2099 to both Start and End
- Also sets HwcHolidayStart/End parallel
- Alternative considered: automation with service calls — rejected, switch is more intuitive

### D4: Entity_category assignment inline in mapping.py
- Add `entity_category="diagnostic"` to all HMU run-stats, error history, circuit types, daemon info
- Add `entity_category="config"` to all writable controls (mostly already done)
- Primary sensors (temps, pressure, humidity) get no category

## Risks / Trade-offs

- Fallback reads increase poll latency by ~2s → still well under 30s interval
- Static HC2/HC3 filter may hide valid entities for multi-zone systems → document in comments
- Away mode switch duplicates holiday date/temp entities → keep as separate entities for power users
- `find` inconsistency may be firmware-specific (ebusd 26.1.26.1 + Vaillant HMU 0522) → monitor
