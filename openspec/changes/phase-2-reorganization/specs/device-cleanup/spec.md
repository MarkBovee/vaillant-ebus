## ADDED Requirements

### Requirement: HC2/HC3/Z2/Z3 register filtering
The system SHALL NOT create entities for HC2, HC3, Z2, or Z3 heating circuits and zones.

#### Scenario: HC2 registers hidden
- **WHEN** `find` returns HC2 register definitions (e.g. `ctlv2.Hc2FlowTemp`, `ctlv2.Hc2HeatCurve`)
- **THEN** no entity is created for any `Hc2*`, `Hc3*`, `Z2*`, or `Z3*` register name

#### Scenario: Schedule timer variants also hidden
- **WHEN** `find` returns `ctlv2.Z2Timer_Monday0` or `ctlv2.Z3Timer_Friday0`
- **THEN** no entity is created (timer variants are covered by the prefix filter)

### Requirement: Poll reliability fallback
The system SHALL perform individual `read` requests for known REGISTER_MAP entries that returned no data from `find`, to catch values the bulk scan misses.

#### Scenario: Compressor power fallback
- **WHEN** `find` returns `hmu CurrentConsumedPower = no data stored`
- **AND** `hmu.CurrentConsumedPower` is in REGISTER_MAP
- **THEN** coordinator issues `read -c hmu CurrentConsumedPower`
- **THEN** if read returns a value (e.g. `0.0`), the sensor shows that value
- **THEN** if read also returns no data, sensor shows unavailable

#### Scenario: Humidity sensor restored
- **WHEN** `find` returns `ctlv2 MaxRoomHumidity = no data stored`
- **AND** `ctlv2.MaxRoomHumidity` is in REGISTER_MAP
- **THEN** coordinator issues `read -c ctlv2 MaxRoomHumidity`
- **THEN** sensor shows the humidity percentage

#### Scenario: Fallback is limited to REGISTER_MAP entries
- **WHEN** `find` returns no data for an unmapped register
- **THEN** no fallback read is attempted (unknown/unexpected registers are not worth individual reads)

### Requirement: Entity category classification
The system SHALL assign `entity_category` to all sensor entities based on their role.

#### Scenario: Diagnostic run stats
- **WHEN** a register represents cumulative run statistics (hours, starts)
- **THEN** its entity category is `diagnostic`

#### Scenario: Diagnostic errors and config
- **WHEN** a register represents error history, circuit type, hydraulic config
- **THEN** its entity category is `diagnostic`

#### Scenario: Config writable controls
- **WHEN** a register is writable and modifies system behavior
- **THEN** its entity category is `config`

#### Scenario: Primary measurements
- **WHEN** a register represents a live measurement (temperature, pressure, humidity, power)
- **THEN** its entity category is not set (primary view)
