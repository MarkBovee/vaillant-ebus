## ADDED Requirements

### Requirement: read_parameter service
The backend SHALL expose a `read_parameter` service to read any parameter by name or topic.

#### Scenario: Read parameter by name
- **WHEN** the `read_parameter` service is called with a parameter name
- **THEN** backend SHALL return the current value from the latest MQTT message

### Requirement: write_parameter service
The backend SHALL expose a `write_parameter` service to write any writable parameter.

#### Scenario: Write parameter
- **WHEN** the `write_parameter` service is called with parameter name and value
- **THEN** backend SHALL publish the value to the corresponding MQTT set topic

#### Scenario: Write validation
- **WHEN** the `write_parameter` service is called with an invalid value (out of range, wrong type)
- **THEN** backend SHALL reject the write and return an error message

### Requirement: refresh service
The backend SHALL expose a `refresh` service to refresh all parameter values.

#### Scenario: Refresh all parameters
- **WHEN** the `refresh` service is called
- **THEN** backend SHALL request ebusd to re-publish all current values

### Requirement: rediscover service
The backend SHALL expose a `rediscover` service to re-run MQTT topic discovery.

#### Scenario: Rediscover topics
- **WHEN** the `rediscover` service is called
- **THEN** backend SHALL clear existing discovered topics, re-subscribe, and re-run discovery
