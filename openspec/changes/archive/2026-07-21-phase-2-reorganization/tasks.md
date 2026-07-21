## 1. Entity Cleanup (device-cleanup)

- [x] 1.1 Add HC2/HC3/Z2/Z3 prefix filter to `_is_hidden_register` in entity_factory.py
- [x] 1.2 Add `entity_category="diagnostic"` to HMU run-stats, error registers, circuit types, system config in mapping.py
- [x] 1.3 Add `entity_category="diagnostic"` to ebusd daemon entities, date/time in mapping.py
- [x] 1.4 Add `MaxRoomHumidity` to REGISTER_MAP with device_class="humidity", unit="%"
- [x] 1.5 Improve device names in models.py (`CIRCUIT_NAMES`)

## 2. Poll Reliability Fix (device-cleanup)

- [x] 2.1 After `find` in coordinator, implement fallback `read` pass for known REGISTER_MAP entries that returned no data
- [x] 2.2 Add logging for fallback reads to track which registers are consistently missed by `find`

## 3. Away Mode (away-mode)

- [x] 3.1 Add away mode switch entity in switch.py
- [x] 3.2 Implement holiday period detection (read Z1HolidayStartPeriod/EndPeriod, compare to today)
- [x] 3.3 Implement away activation writes (Z1Holiday + HwcHoliday dates + Z1HolidayTemp)
- [x] 3.4 Implement away deactivation writes (reset all holiday dates to 01.01.2099)
- [x] 3.5 Add FALLBACK_READ_REGS set to coordinator for away-mode switch status polling

## 4. Deployment & Validation

- [x] 4.1 Run ruff, pytest, compileall
- [ ] 4.2 Deploy to HA server via custom_component upload
- [ ] 4.3 Restart HA core and verify entities load
- [ ] 4.4 Clean up entity_registry — remove orphaned HC2/HC3/Z2/Z3 entities
- [ ] 4.5 Verify compressor power shows live value
- [ ] 4.6 Verify humidity sensor shows live value
- [ ] 4.7 Test away mode toggle (on/off) and verify eBUS writes
- [ ] 4.8 Restore away mode user setting after test
