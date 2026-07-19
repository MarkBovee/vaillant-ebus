# Measurement Reading

## Scope

Discover and read measurement data from VR921 entities.

## Requirements

### R1: Entity discovery
Request `nodeManagementDetailedDiscoveryData` from VR921. Parse entity tree (DeviceInformation, HeatPumpAppliance, Compressor, DHWCircuit, HeatingZone, TemperatureSensor).

### R2: Measurement server identification
Find features with `featureType=11` (Measurement server) per entity.

### R3: Description
`measurementDescriptionListData` — parse scopeType, unit, measurementId per server.

### R4: Read
`measurementListData` — read current values from each measurement server.

### R5: Subscribe
`NodeManagementSubscriptionRequestCall` — subscribe to measurement updates. Receive notify datagrams with new values.

### R6: Entity mapping
Map VR921 entities to HA sensor entities by entity type and scope type:
- `entityType=Compressor` + `scopeType=acPowerTotal` → Compressor power sensor
- `entityType=DHWCircuit` + `scopeType=dhwTemperature` → DHW temperature sensor
- `entityType=HVACRoom` + `scopeType=roomAirTemperature` → Room temperature sensor
- `entityType=TemperatureSensor` + `scopeType=outsideAirTemperature` → Outdoor temp sensor
- Unknown entity types → generic diagnostic sensor

Mapping must be dynamic: entity type names come from discovery, scope types from measurement descriptions.
No hardcoded entity addresses (e.g. `[3,1]`, `[4]`, `[5,1,1]`). Match by entityType string, not by entity ID.

### R7: Capability model
Discovered features MUST be represented as `Capability` objects containing:
- Protocol address (device, entity, feature)
- Feature type and role
- Supported commands (from UseCase data)
- Measurement metadata (scopeType, unit)
- Runtime value state

See design.md §7 for full capability model specification.

### R8: Empirical data limitations
Empirical testing against a real VR921 shows:
- 19 measurement IDs described, only 4 return live values
- 16 ElectricalConnection parameters described but lack scopeType/unit — unmappable
- `electricalConnectionParameterListData` read returns no response
- Missing values: acCurrent(×3), acPower(×2), acEnergyConsumed, acEnergyProduced, acFrequency, acVoltage

These may be accessible through a different EEBUS path (Loxone integration is known to access more data).
Document all empirical findings in design.md §1.6-1.7.
