## ADDED Requirements

### Requirement: Number entities for writable numeric parameters
The backend SHALL create Number entities for every writable numeric parameter.

#### Scenario: Create number entities
- **WHEN** a writable numeric parameter is discovered (temperature setpoint, pressure target)
- **THEN** backend SHALL create a Number entity with appropriate min/max/step from mapping or entities.yaml

#### Scenario: Value validation
- **WHEN** user sets a value on a Number entity
- **THEN** backend SHALL validate the value against min/max range before sending

### Requirement: Select entities for enum parameters
The backend SHALL create Select entities for every enum parameter.

#### Scenario: Create select entities
- **WHEN** an enum parameter is discovered (operating mode, fan speed level)
- **THEN** backend SHALL create a Select entity with available options from the parameter definition

#### Scenario: Enum validation
- **WHEN** user selects an option on a Select entity
- **THEN** backend SHALL validate the option against the available options before sending

### Requirement: Switch entities for writable booleans
The backend SHALL create Switch entities for writable boolean parameters.

#### Scenario: Create switch entities
- **WHEN** a writable boolean parameter is discovered
- **THEN** backend SHALL create a Switch entity

### Requirement: Button entities for actions
The backend SHALL create Button entities for actions: reset fault, refresh, rediscover.

#### Scenario: Create reset fault button
- **WHEN** integration starts
- **THEN** backend SHALL create a Button entity for resetting faults

#### Scenario: Create refresh button
- **WHEN** integration starts
- **THEN** backend SHALL create a Button entity for refreshing all parameters

#### Scenario: Create rediscover button
- **WHEN** integration starts
- **THEN** backend SHALL create a Button entity for triggering MQTT rediscovery

### Requirement: Readonly protection
The backend SHALL prevent writes to parameters not marked as writable.

#### Scenario: Block readonly write
- **WHEN** user attempts to write to a readonly parameter via service or entity
- **THEN** backend SHALL reject the write and log a warning
