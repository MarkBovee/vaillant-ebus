# Changelog

## 1.0.5b3 - 2026-07-23

- Fix PowerConsumptionHmu decode error (CSV defines IGN:1+EXP for 1-byte
  response; override with define -r as UCH+W).
- Translate compressor numeric status codes to human-readable labels.
- Disable 3 unsupported registers (RunDataLowPressure, HcStorageTempBottom,
  HcStorageTempTop) to suppress repeated fallback warnings.
- Skip disabled REGISTER_MAP entries in fallback read loop.

## 1.0.4 - 2026-07-22

- Extend stale-value fix to all compressor-dependent registers: speed,
  fan speeds, yield power, utilisation, EEV position (compressor power
  already fixed in 1.0.3).
- Rewrite `set_idle_compressor_power` into `zero_idle_registers` and
  add `COMPRESSOR_ZERO_REGISTERS` set for maintainability.

## 1.0.3 - 2026-07-22

- Fix compressor power remaining at its last non-zero value after the
  compressor stops.

