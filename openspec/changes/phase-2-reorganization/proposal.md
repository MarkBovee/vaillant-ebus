## Why

After initial eBUS integration rollout, three issues remain: (1) ~90 entities for non-existent HC2/HC3/Z2/Z3 zones clutter the registry, (2) `find` bulk scan misses ~20 HMU registers including CurrentConsumedPower and MaxRoomHumidity — forcing cloud fallback for humidity and compressor power, (3) away mode requires separate date/number entities instead of a single switch. Also, sensors lack proper device-classification (diagnostic vs primary).

## What Changes

- **Poll reliability fix**: After `find` completes, do targeted `read` pass for known REGISTER_MAP entries that returned no data. This restores compressor power, humidity, COP, and all HMU run-data registers.
- **Device re-organization**: Assign entity_category (`diagnostic`/`config`) to all HMU run-stats, error registers, system config, and ebusd daemon entities. Improve circuit device names.
- **Zone noise removal**: Filter out HC2, HC3, Z2, Z3 registers from entity generation. These circuits don't exist on this system (`Hc2CircuitType=inactive`, etc).
- **Away mode switch**: New `switch.away_mode` that writes Z1HolidayStartPeriod/EndPeriod/Temp as a single toggle, replacing manual holiday date/number entities.
- **Humidity sensor**: Re-enable `ctlv2.MaxRoomHumidity` — confirmed working via direct `read` (40%). Currently hidden by `find` bug.

## Capabilities

### New Capabilities
- `away-mode`: Single-switch away/holiday activation. Toggle writes holiday dates + frost-protection temp to eBUS. Switch state derived from holiday period comparison vs today.
- `device-cleanup`: Entity filtering (hide HC2/HC3/Z2/Z3 noise), entity_category classification, device name improvement.

### Modified Capabilities
- (none)

## Impact

- `backend/tcp.py` — minor: `async_find()` may be extended or coordinator logic changed
- `backend/mapping.py` — entity_category additions, humidity entry
- `backend/entity_factory.py` — `_is_hidden_register` expansion for HC2/HC3/Z2/Z3
- `coordinator.py` — fallback read pass after `find`
- `switch.py` — new away_mode platform
- `sensor.py` — humidity entity (may already work after poll fix)
- Existing holiday `date` and `number` entities may be deprecated in favor of away mode switch
- Compressor power restores from "unknown" to live value
- Humidity becomes available locally instead of cloud-only
