## ADDED Requirements

### Requirement: Backward-compatible entity migration
The migration from EEBUS to ebusd SHALL preserve existing entity identities where possible.

#### Scenario: Preserve EEBUS entities
- **WHEN** migration runs
- **THEN** existing EEBUS entities SHALL remain functional (not deleted)

#### Scenario: Add ebusd entities alongside EEBUS
- **WHEN** ebusd backend starts
- **THEN** ebusd entities SHALL be added as new entities, not replacing EEBUS entities

### Requirement: Migration guide
The integration SHALL include a migration guide for users switching from EEBUS-only to ebusd+MQTT.

#### Scenario: Provide migration documentation
- **WHEN** user reads the documentation
- **THEN** it SHALL include: hardware setup, ebusd installation, MQTT broker setup, entities.yaml configuration, and troubleshooting

### Requirement: Architecture documentation
The integration SHALL include an architecture diagram and documentation.

#### Scenario: Provide architecture docs
- **WHEN** migration is complete
- **THEN** docs SHALL include: system architecture, changed files list, rationale for changes, migration guide, future improvements, known limitations

### Requirement: Incremental migration
The migration SHALL be implementable incrementally in logical commits.

#### Scenario: Incremental implementation
- **WHEN** implementing the migration
- **THEN** it SHALL be split into logical changes: backend abstraction, MQTT transport, auto-discovery, entity mapping, testing, documentation
