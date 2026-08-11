# Vaillant eBUS Project

## Scope

- This repository contains a Home Assistant custom integration for Vaillant heat pumps.
- The integration connects directly to the local ebusd TCP interface on port `8888`; it does not use MQTT or cloud services.
- Registers and devices are discovered from ebusd at runtime. The project is intended as a drop-in replacement for `mypyllant-component`.

## Architecture

- `custom_components/vaillant_ebus/coordinator.py` owns connection lifecycle, discovery, polling, caching, and runtime register definitions.
- `custom_components/vaillant_ebus/backend/ebus_service.py` provides the ebusd transport.
- `backend/discovery_service.py` builds the discovered device graph.
- `backend/register_service.py` handles register reads and writes.
- `backend/entity_factory.py` maps the discovered graph to Home Assistant entity descriptions.
- `backend/mapping.py` contains register metadata such as names, icons, units, and limits.
- Platform modules in `custom_components/vaillant_ebus/` expose the generated entities to Home Assistant.

## Discovery And Entities

- The discovery graph is the source of truth for entity existence. Do not hardcode device types, circuit lists, or register lists in entity platforms.
- `REGISTER_MAP` supplies metadata and enabled defaults. It must not cause `EntityFactoryService` to create entities that are absent from the discovery graph.
- The coordinator may explicitly read enabled `REGISTER_MAP` entries as a fallback and must regenerate entity descriptions when that adds registers.
- `CIRCUIT_NAMES` is the only place for hardcoded circuit-to-label descriptions used by the Home Assistant UI.
- Values such as `-`, `no data stored`, and `empty` represent unavailable ebusd data. They must not be exposed as normal sensor values.
- Keep filtering for unsupported circuits, secondary zones, broadcast registers, and no-data devices consistent with the existing discovery and entity-factory logic. Do not create virtual entities for unsupported hardware.

## Runtime-Defined Registers

Some supported registers are not returned by ebusd `find` and must be defined or probed at runtime. `ctlv2.z1RoomHumidity` is one confirmed example, not an exhaustive list.

When functionality is missing, inspect the raw `find` output, discovery dump, ebusd metadata, and unmapped registers before adding a one-off implementation. Test each candidate directly against ebusd, confirm its message format and read-back value, and add only registers supported by the connected hardware.

Keep all runtime definitions in `VaillantCoordinator._define_custom_registers()` and execute them after connecting to ebusd and before discovery. Use one data-driven collection for additional definitions instead of separate register-specific code paths.

The confirmed `z1RoomHumidity` definition is:

```text
r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800,value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity
```

Use `EbusService.define_register()` for runtime definitions. Do not replace them with CSV uploads or an addon `--configpath` override.

When changing `_fallback_read()`, preserve entity regeneration after newly readable registers are added.

## Climate Compatibility

Climate behavior must follow the corresponding `mypyllant` implementation.

- In `day` / manual mode, `async_set_temperature` writes `Z1DayTemp` directly.
- In time-controlled modes, it uses quick veto with `Z1QuickVetoTemp` and `Z1QuickVetoDuration`.
- If quick veto is already active in a time-controlled mode, update its temperature without writing a new duration.
- Preset mapping, HVAC modes, and climate services should remain aligned with `mypyllant`.

## ebusd Safety

- Never modify, upload, or delete ebusd addon CSV files.
- Never set the ebusd addon `--configpath`.
- Before changing integration code for a register write, test the register directly against ebusd over TCP or HTTP, verify a `done` response, and read the value back.
- Treat registers that return `ERR: element not found` or `no data stored` as unsupported or temporarily unavailable; do not fabricate values or entities.

## Known Limitations

- Many heat-pump registers return `no data stored` while the compressor is idle.
- Register classification is inferred from discovery and metadata; YAML overrides may be needed for uncommon registers.
- Some useful registers may require runtime definitions before they can be discovered.

## Test Fixtures

- ebusd `find` output and discovery dumps are captured as fixtures in `tests/fixtures/`. There is no `data-dump/` directory anymore; all community and local captures live in `tests/fixtures/`.
- `tests/fixtures/community/` holds third-party captures: discovery-dump YAML files (`flexotherm_discovery.yaml`, `arotherm_plus_2zone_discovery.yaml`, `arotherm_plus_basv3_discovery.yaml`, `arotherm_pro7_discovery.yaml`) and plain `find` output (`basv_find.txt`, `v32_find.txt`, `flexocompact_find.txt`, `szflo_ebusctl_info.txt`, `second_ebusctl_info.txt`, `dumpvalues.yaml`).
- `dumpvalues.yaml` records multi-field register field names and is the reference for `MULTI_FIELD_MAP` in `tests/fake_ebusd.py`. Keep the two in sync.
- Load fixtures in tests with `load_find_lines("community/<name>")` for `find` output and `load_discovery_dump("community/<name>")` for discovery-dump YAML; both live in `tests/fake_ebusd.py`. Discovery-dump YAML fixtures need `pyyaml` (installed in CI).
- Open GitHub issues may reference specific community dumps. When investigating an issue, load the matching fixture and confirm the register behavior on the discovered device graph before changing production code.
- New community captures should be added under `tests/fixtures/community/` as discovery-dump YAML (preferred, keeps metadata and `raw_find_lines`) with a fixture-load test, never as a separate `data-dump/` folder.

## Validation

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
python3 -m compileall -f custom_components/vaillant_ebus/
```
