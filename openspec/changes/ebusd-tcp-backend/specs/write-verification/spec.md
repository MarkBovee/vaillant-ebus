## ADDED Requirements

### Requirement: Read-after-write verification
After writing a value, the backend SHALL verify the write by reading back the value from MQTT.

#### Scenario: Successful write verification
- **WHEN** a write is published to MQTT
- **THEN** backend SHALL wait for the corresponding MQTT message reflecting the new value (timeout: 3s configurable)

#### Scenario: Write verification timeout
- **WHEN** no confirmation message arrives within the timeout
- **THEN** backend SHALL log a warning and mark the write as unconfirmed

### Requirement: Rollback on rejection
If the write is rejected or the value does not match, the backend SHALL roll back the entity state.

#### Scenario: Rollback on value mismatch
- **WHEN** the confirmed value does not match the written value
- **THEN** backend SHALL revert the entity state to the previous value and log an error

### Requirement: Unavailable device guard
The backend SHALL reject writes when the ebusd device or MQTT connection is unavailable.

#### Scenario: Reject write when unavailable
- **WHEN** the MQTT connection is down or ebusd is not responding
- **THEN** backend SHALL reject the write and return an unavailable error
