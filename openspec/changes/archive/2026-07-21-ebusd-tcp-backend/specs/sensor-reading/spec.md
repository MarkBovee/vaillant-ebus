## ADDED Requirements

### Requirement: Temperature sensors
The backend SHALL create sensor entities for all temperature values from ebusd.

#### Scenario: Create temperature sensors
- **WHEN** a temperature parameter is discovered (flow temp, return temp, outside temp, DHW temp, room temp)
- **THEN** backend SHALL create a sensor entity with device_class temperature and appropriate unit

### Requirement: Pressure sensors
The backend SHALL create sensor entities for all pressure values.

#### Scenario: Create pressure sensors
- **WHEN** a pressure parameter is discovered
- **THEN** backend SHALL create a sensor entity with device_class pressure

### Requirement: Energy and power sensors
The backend SHALL create sensor entities for energy and power values.

#### Scenario: Create energy sensors
- **WHEN** an energy or power parameter is discovered
- **THEN** backend SHALL create a sensor entity with device_class energy or power

### Requirement: Runtime and counter sensors
The backend SHALL create sensor entities for runtime hours, compressor starts, and other counters.

#### Scenario: Create runtime sensors
- **WHEN** a runtime or counter parameter is discovered
- **THEN** backend SHALL create a sensor entity with device_class duration or generic sensor

### Requirement: COP and efficiency sensors
The backend SHALL create sensor entities for COP and efficiency values.

#### Scenario: Create COP sensors
- **WHEN** a COP or efficiency parameter is discovered
- **THEN** backend SHALL create a sensor entity with appropriate device class and unit

### Requirement: Electrical sensor entities
The backend SHALL create sensor entities for electrical values (current, voltage, frequency).

#### Scenario: Create electrical sensors
- **WHEN** an electrical parameter is discovered
- **THEN** backend SHALL create a sensor entity with appropriate device_class

### Requirement: State class and entity category
Every sensor SHALL have appropriate state_class and entity_category set.

#### Scenario: Set state class
- **WHEN** a sensor is created
- **THEN** backend SHALL set state_class to measurement for live values, total_increasing for counters

#### Scenario: Set entity category
- **WHEN** a diagnostic or infrequent sensor is created
- **THEN** backend SHALL set entity_category to diagnostic
