## ADDED Requirements

### Requirement: Away mode switch toggle
The system SHALL provide a switch entity that activates/deactivates away (holiday) mode on the heat pump via eBUS writes.

#### Scenario: Away mode activation
- **WHEN** user turns on `switch.vaillant_ctlv2_heating_control_away_mode`
- **THEN** system writes today's date to `Z1HolidayStartPeriod`
- **THEN** system writes `01.01.2099` to `Z1HolidayEndPeriod`
- **THEN** system writes `Z1HolidayTemp` (configured frost protection temp) to eBUS
- **THEN** system mirrors the same writes to `HwcHolidayStartPeriod` / `HwcHolidayEndPeriod`
- **THEN** switch state shows `on`

#### Scenario: Away mode deactivation
- **WHEN** user turns off `switch.vaillant_ctlv2_heating_control_away_mode`
- **THEN** system writes `01.01.2099` to both `Z1HolidayStartPeriod` and `Z1HolidayEndPeriod`
- **THEN** system writes `01.01.2099` to both `HwcHolidayStartPeriod` and `HwcHolidayEndPeriod`
- **THEN** switch state shows `off`

#### Scenario: Away mode state detection on startup
- **WHEN** coordinator starts or updates
- **THEN** system reads `Z1HolidayStartPeriod` and `Z1HolidayEndPeriod`
- **THEN** if `Z1HolidayStartPeriod` is before or equal today AND `Z1HolidayEndPeriod` is after today, switch state shows `on`
- **THEN** otherwise switch state shows `off`

### Requirement: Away mode preserves quick-veto and program
The system SHALL NOT modify Z1QuickVeto or timer program registers when toggling away mode.

#### Scenario: Quick veto unaffected
- **WHEN** user toggles away mode
- **THEN** `Z1QuickVetoDuration`, `Z1QuickVetoTemp`, `Z1QuickVetoEndDate`, `Z1QuickVetoEndTime` are not modified

### Requirement: Holiday temp entity retained
The existing `number.vaillant_ctlv2_heating_control_holiday_temperature` SHALL remain configurable independently.

#### Scenario: Holiday temp separate
- **WHEN** user changes `number.vaillant_ctlv2_heating_control_holiday_temperature`
- **THEN** away mode switch reads the new value at next activation
- **THEN** away mode deactivation does not reset holiday temperature
