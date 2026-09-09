# Discovery Dump Schema

Discovery dumps are YAML files intended for user support, device comparison, and automated analysis.

## Compatibility

Existing fields remain unchanged:

- `metadata`
- `raw_find_lines`
- `before_registers`
- `after_registers`
- `raw_find_lines_after`
- `grab`
- `labeled_telegrams`
- `unknown_telegrams`

Current dumps use `metadata.dump_version: 4`. Dumps with no version are treated as legacy version 1. Future versions are preserved and reported as unsupported by the normalizer instead of being interpreted as a different schema.

## Structured fields

Current exports add these fields alongside the raw representation:

- `registers.discovered`: register keys found by ebusd.
- `registers.mapped`: register keys supplied by `REGISTER_MAP`.
- `registers.unavailable`: discovered or mapped registers without usable data.
- `registers.disabled`: mapped registers disabled by default.
- `changes.new_registers`: registers appearing only in the after snapshot.
- `changes.changed_registers`: meaningful value changes with before/after values.
- `changes.disappeared_registers`: registers absent from the after snapshot.
- `traffic.summary`: grouped known and unknown telegrams with counts, requests, and responses.
- `traffic.unknown`: grouped telegrams without an ebusd register label.

Sentinel-only changes such as `no data stored`, `empty`, `-`, and `unknown` are not treated as meaningful value changes.

## Analysis API

Use `normalize_dump(dump)` from `custom_components/vaillant_ebus/backend/dump_analysis.py` for both old and new dumps:

```python
from custom_components.vaillant_ebus.backend.dump_analysis import normalize_dump

normalized = normalize_dump(yaml.safe_load(path.read_text()))
```

The function does not modify or migrate files on disk. It preserves raw data under `normalized["raw"]` and exposes one stable analysis representation for legacy and current dumps.

Review the generated file for sensitive information before sharing it. The exporter continues to redact sensitive register names and writes this warning into every file.
