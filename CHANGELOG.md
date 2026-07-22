# Changelog

## 1.0.4 - 2026-07-22

- Extend stale-value fix to all compressor-dependent registers: speed,
  fan speeds, yield power, utilisation, EEV position (compressor power
  already fixed in 1.0.3).
- Rewrite `set_idle_compressor_power` into `zero_idle_registers` and
  add `COMPRESSOR_ZERO_REGISTERS` set for maintainability.

## 1.0.3 - 2026-07-22

- Fix compressor power remaining at its last non-zero value after the
  compressor stops.

