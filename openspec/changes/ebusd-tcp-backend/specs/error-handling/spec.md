## ADDED Requirements

### Requirement: MQTT disconnect handling
The backend SHALL handle MQTT disconnection gracefully without crashing the integration.

#### Scenario: Handle MQTT disconnect
- **WHEN** MQTT connection drops
- **THEN** backend SHALL mark all entities as unavailable and start reconnection

### Requirement: ebusd restart handling
The backend SHALL handle ebusd daemon restart gracefully.

#### Scenario: Handle ebusd restart
- **WHEN** ebusd restarts and re-publishes retained messages
- **THEN** backend SHALL re-discover all topics and update entity states

### Requirement: Malformed payload handling
The backend SHALL handle malformed MQTT payloads without crashing.

#### Scenario: Handle malformed payload
- **WHEN** a malformed or non-parseable MQTT message is received
- **THEN** backend SHALL log the raw payload at DEBUG level and continue

### Requirement: Unknown message handling
The backend SHALL handle unknown or unrecognized MQTT topics without crashing.

#### Scenario: Handle unknown topics
- **WHEN** an MQTT message arrives on an unrecognized topic
- **THEN** backend SHALL ignore the message and optionally log at DEBUG level

### Requirement: Unsupported firmware handling
The backend SHALL detect and report unsupported ebusd versions or heat pump firmware.

#### Scenario: Detect unsupported firmware
- **WHEN** ebusd reports a firmware version not in the supported list
- **THEN** backend SHALL log a warning and continue with best-effort discovery

### Requirement: Unavailable value handling
The backend SHALL handle values that are temporarily unavailable (e.g., N/A while heating).

#### Scenario: Handle unavailable value
- **WHEN** ebusd reports a value as unavailable or N/A
- **THEN** backend SHALL set the entity state to unavailable

### Requirement: Timeout handling
The backend SHALL handle MQTT operation timeouts.

#### Scenario: Handle connect timeout
- **WHEN** MQTT connection attempt exceeds the configured timeout
- **THEN** backend SHALL abort the connection and schedule a retry with backoff
