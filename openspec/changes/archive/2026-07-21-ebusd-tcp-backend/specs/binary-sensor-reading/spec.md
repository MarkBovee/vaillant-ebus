## ADDED Requirements

### Requirement: Heating active binary sensor
The backend SHALL create a binary sensor for heating active state.

#### Scenario: Create heating active sensor
- **WHEN** a heating active parameter is discovered
- **THEN** backend SHALL create a binary sensor entity with device_class heat

### Requirement: Cooling active binary sensor
The backend SHALL create a binary sensor for cooling active state.

#### Scenario: Create cooling active sensor
- **WHEN** a cooling active parameter is discovered
- **THEN** backend SHALL create a binary sensor entity with device_class cold

### Requirement: DHW active binary sensor
The backend SHALL create a binary sensor for DHW active state.

#### Scenario: Create DHW active sensor
- **WHEN** a DHW active parameter is discovered
- **THEN** backend SHALL create a binary sensor entity

### Requirement: Compressor running binary sensor
The backend SHALL create a binary sensor for compressor running state.

#### Scenario: Create compressor running sensor
- **WHEN** a compressor running parameter is discovered
- **THEN** backend SHALL create a binary sensor entity with device_class running

### Requirement: Defrost active binary sensor
The backend SHALL create a binary sensor for defrost active state.

#### Scenario: Create defrost active sensor
- **WHEN** a defrost active parameter is discovered
- **THEN** backend SHALL create a binary sensor entity with device_class defrost (or generic)

### Requirement: Alarm active binary sensor
The backend SHALL create a binary sensor for alarm active state.

#### Scenario: Create alarm active sensor
- **WHEN** an alarm or error active parameter is discovered
- **THEN** backend SHALL create a binary sensor entity with device_class problem
