## ADDED Requirements

### Requirement: Diagnostics endpoint
The backend SHALL provide a HA diagnostics endpoint showing the full system state.

#### Scenario: Provide diagnostics data
- **WHEN** user views the integration diagnostics
- **THEN** backend SHALL include: firmware version, adapter type, MQTT connection status, last message timestamp, reconnect count, discovered modules, unsupported messages count, active subscriptions

### Requirement: Diagnostics data for debugging
The backend SHALL include diagnostics data useful for debugging and support.

#### Scenario: Include debug info
- **WHEN** diagnostics is downloaded
- **THEN** it SHALL include: list of all discovered parameters, their current values, last update timestamps, and topic names
