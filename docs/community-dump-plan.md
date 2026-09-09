# Community Dump Processing Plan

## Goal

Process every new community capture as a fixture first, then change production code only when the register layout and behavior are supported by the captures. Do not guess registers from screenshots or add ebusd CSV overrides.

## Capture groups

- Issue #101: three aroTHERM Pro captures for Quiet mode: idle/off, heating/off, and heating/on. Identify `NoiseReduction`, `NoiseReductionFactor`, and timer registers.
- Issue #99: latest aroTHERM VWL 55/8.2 HMUX0 capture. Trace `ctlv3` DHW entity state and holiday start/end behavior; HMUX0 yield/COP coverage already exists.
- Discussion #33: ecoTEC Plus and VRT380 captures using `15.700` and `15.ctlv2`, plus the ebusd log. Compare controller layouts, writable registers, BAI data, and gas/DHW registers.
- Issue #103: eloBLOCK VE 28 capture. Compare with the existing fixture and add only confirmed BAI/B510 behavior.
- Discussion #107: no capture yet. Request discovery, state timestamps, and logs before investigating stale energy values.

## Workflow

1. Download and normalize every attachment.
2. Store new community captures under `tests/fixtures/community/` as discovery-dump YAML where possible.
3. Add fixture-load and discovery/entity regression tests before production changes.
4. Compare captures from the same hardware and classify registers as supported, missing, unavailable, read-only, or writable.
5. Implement only confirmed mappings through existing discovery, `REGISTER_MAP`, runtime definitions, and entity-factory paths.
6. Keep `no data stored`, empty, and error responses unavailable; never expose them as normal values.
7. Keep service lifecycle regression #106 separate from register work.
8. Run focused tests, then the complete validation suite.

## Implementation order

1. Quiet mode register comparison and fixture coverage.
2. HMUX0 DHW and holiday entity tracing.
3. ecoTEC/VRT380 controller comparison and write-path analysis.
4. eloBLOCK fixture comparison.
5. Service async regression #106.
6. Stale energy values from Discussion #107.
7. Energy Manager State and defrost behavior after reliable status data exists.

## Validation

```text
pytest -q tests/test_fake_ebusd.py
pytest -q tests/test_community_issue_fixtures.py
pytest -q tests/test_entity_factory.py tests/test_discovery_service.py
pytest -q
.venv/bin/ruff check .
python3 -m compileall -f custom_components/vaillant_ebus/
```

## GitHub follow-up

- Report confirmed Quiet mode registers and remaining conditional behavior on #101.
- Report HMUX0 coverage and keep DHW/holiday behavior as separate follow-up on #99.
- Explain the confirmed VRT380 controller layout and writable limitations in Discussion #33.
- Reply to #103 only with confirmed eloBLOCK behavior.
- Request the missing capture and logs for Discussion #107 before promising a fix.
