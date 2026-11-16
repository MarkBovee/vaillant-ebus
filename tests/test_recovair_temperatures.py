"""Four recoVAIR temperatures retain their base entity and real sensor status."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.backend_loader import load_backend

MAPPING = load_backend("mapping")
MODELS = load_backend("models")
FACTORY = load_backend("entity_factory")
EBUS = load_backend("ebus_service")
DISCOVERY = load_backend("discovery_service")
CAPTURE = (Path(__file__).parent / "fixtures/community/recovair_temperature_read.txt").read_text()
READINGS = {}
for line in CAPTURE.splitlines():
    if line.startswith("v32 "):
        circuit, name, payload = line.split(" ", 2)
        fields = dict(part.split("=", 1) for part in payload.split(";"))
        READINGS[f"{circuit}.{name}"] = {"value": fields["temp"], "sensor": fields["sensor"]}
KEYS = tuple(READINGS)


# Intent: strip verbose field labels to exercise non-verbose reads as well.
# Why: the real capture uses -v while production read_register does not.
def _raw(key: str) -> str:
    fields = READINGS[key]
    return f"{fields['value']};{fields['sensor']}"


# Intent: expose one temperature and one diagnostic status per captured register.
# Why: primary entity IDs must stay stable when the real second field is mapped.
@pytest.mark.parametrize("key", KEYS)
def test_recovair_primary_temperature_and_status_entities(key):
    node = MODELS.DeviceNode(
        circuit="v32", device_type=MODELS.DeviceType.VENTILATION, registers=list(KEYS), has_data=True
    )
    graph = MODELS.DeviceGraph(
        nodes={"v32": node}, raw_registers={name: _raw(name) for name in KEYS}, placeholder_registers=set()
    )
    entities = {entity.key: entity for entity in FACTORY.EntityFactoryService().generate(graph)}
    primary = entities[f"{key}.value"]
    assert primary.unique_id == f"ebusd_{key.replace('.', '_').lower()}"
    assert primary.entity_type == "sensor"
    assert primary.meta.unit == "°C"
    assert primary.meta.device_class == "temperature"
    assert primary.meta.state_class == "measurement"
    status = entities[f"{key}.sensor"]
    assert status.entity_type == "sensor"
    assert status.meta.entity_category == "diagnostic"
    assert not status.meta.unit
    assert not status.meta.device_class
    assert not status.meta.state_class
    assert MAPPING.split_multi_field(key, _raw(key)) == READINGS[key]


# Intent: keep zero, negative and positive readings with healthy status.
# Why: fault filtering must not use numeric truthiness or discard winter temperatures.
@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("reading", ["0", "-4.5", "20.06"])
@pytest.mark.parametrize("status", ["ok", "0"])
def test_recovair_valid_status_keeps_temperature(key, reading, status):
    assert MAPPING.split_multi_field(key, f"{reading};{status}")["value"] == reading


# Intent: retain diagnostic text but invalidate temperatures with non-healthy status.
# Why: an apparently plausible numeric value must not hide a reported sensor fault.
@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("status", ["circuit", "cutoff", "85", "170", "unknown", "", "unexpected"])
def test_recovair_fault_status_invalidates_temperature_but_is_retained(key, status):
    fields = MAPPING.split_multi_field(key, f"20.06;{status}")
    assert fields == {"value": None, "sensor": status}


# Intent: missing status is unknown, never assumed healthy.
# Why: truncated or unavailable responses must not produce a valid measurement.
@pytest.mark.parametrize("key", KEYS)
def test_recovair_missing_status_is_not_a_healthy_sensor(key):
    assert MAPPING.split_multi_field(key, "20.06") == {"value": None, "sensor": None}
    assert MAPPING.split_multi_field(key, None)["value"] is None


# Intent: preserve complete non-verbose replies for cached and forced reads.
# Why: stripping the trailing ok would erase the real sensor-status field.
@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("force", [False, True])
async def test_transport_retains_actual_status_field(key, force):
    service = EBUS.EbusService("127.0.0.1", 8888)
    service.send_command = AsyncMock(return_value=MODELS.SendResult(data=_raw(key), error=None))
    circuit, name = key.split(".")
    assert await service.read_register(circuit, name, force=force) == _raw(key)
    flag = " -f" if force else ""
    service.send_command.assert_awaited_once_with(f"read{flag} -c {circuit} {name}")


# Intent: preserve a non-healthy field through transport and splitting.
# Why: generic unknown-suffix stripping would conceal the diagnostic reason.
@pytest.mark.parametrize("key", KEYS)
async def test_transport_keeps_fault_for_downstream_filter(key):
    service = EBUS.EbusService("127.0.0.1", 8888)
    service.send_command = AsyncMock(return_value=MODELS.SendResult(data="20.06;unknown", error=None))
    circuit, name = key.split(".")
    raw = await service.read_register(circuit, name)
    assert MAPPING.split_multi_field(key, raw) == {"value": None, "sensor": "unknown"}


# Intent: keep suffix stripping unchanged outside the exact four register keys.
# Why: V32 also represents boilers and must not be treated globally as recoVAIR.
@pytest.mark.parametrize("circuit,name", [("v32", "FlowTemp"), ("ctlv3", "OutsideAirTemp"), ("v32", "Unrelated")])
async def test_other_registers_keep_existing_suffix_contract(circuit, name):
    service = EBUS.EbusService("127.0.0.1", 8888)
    service.send_command = AsyncMock(return_value=MODELS.SendResult(data="20.06;ok", error=None))
    assert await service.read_register(circuit, name) == "20.06"


# Intent: preserve the existing V32 boiler temperature layouts.
# Why: sharing a circuit name does not imply sharing recoVAIR field semantics.
def test_v32_boiler_fields_are_not_reinterpreted_as_ventilation():
    assert MAPPING.split_multi_field("v32.FlowTemp", "47.06;ok")["value"] == "47.06"
    assert MAPPING.split_multi_field("v32.ReturnTemp", "55.31;64650;ok")["value"] == "55.31"


# Intent: drive discovery and entity generation from all four captured readings.
# Why: a read transcript can be projected to find syntax without inventing scan ownership evidence.
def test_recovair_read_projection_through_discovery():
    lines = [f"{key.replace('.', ' ', 1)} = {_raw(key)}" for key in KEYS]
    graph = DISCOVERY.DiscoveryService.build_device_graph(lines)
    assert set(graph.raw_registers) == set(KEYS)
    entities = {entity.key: entity for entity in FACTORY.EntityFactoryService().generate(graph)}
    for key in KEYS:
        assert entities[f"{key}.value"].meta.device_class == "temperature"
        assert entities[f"{key}.sensor"].meta.entity_category == "diagnostic"


# Intent: metadata alone must not create a ventilation device or temperature entities.
# Why: an unrelated V32 boiler or an empty bus must not acquire phantom sensors.
@pytest.mark.parametrize("lines", [[], ["v32 FlowTemp = 47.06;ok", "v32 ReturnTemp = 40.0;64000;ok"]])
def test_missing_recovair_registers_create_no_recovair_entities(lines):
    graph = DISCOVERY.DiscoveryService.build_device_graph(lines)
    keys = {entity.key for entity in FACTORY.EntityFactoryService().generate(graph)}
    assert not any(key.startswith(f"{register}.") for key in keys for register in KEYS)


# Intent: retain the mapping and healthy status when ebusd varies capitalization.
# Why: register lookups elsewhere in the integration are case-insensitive too.
def test_recovair_case_insensitive_key_and_status():
    assert MAPPING.split_multi_field("V32.SUPPLYAIRTEMP", "0;OK") == {"value": "0", "sensor": "OK"}


# Intent: preserve the existing single-field read command and result.
# Why: the status-preserving path applies only to whole-register reads.
async def test_recovair_explicit_field_read():
    service = EBUS.EbusService("127.0.0.1", 8888)
    service.send_command = AsyncMock(return_value=MODELS.SendResult(data="ok", error=None))
    assert await service.read_register("v32", "SupplyAirTemp", "sensor") == "ok"
    service.send_command.assert_awaited_once_with("read -c v32 SupplyAirTemp sensor")


# Intent: keep an empty response unknown rather than fabricate a reading.
# Why: matching a known register name is not proof that the device supplied data.
async def test_recovair_empty_read():
    service = EBUS.EbusService("127.0.0.1", 8888)
    service.send_command = AsyncMock(return_value=MODELS.SendResult(data="", error=None))
    assert await service.read_register("v32", "SupplyAirTemp") is None


# Intent: retain ordinary and raising transport-error behavior on the new path.
# Why: preserving a data field must not swallow connection failures or add reads.
@pytest.mark.parametrize("raises", [False, True])
async def test_recovair_transport_error(raises):
    service = EBUS.EbusService("127.0.0.1", 8888)
    service.send_command = AsyncMock(return_value=MODELS.SendResult(data="", error="timeout"))
    service.disconnect = AsyncMock()
    if raises:
        with pytest.raises(TimeoutError):
            await service.read_register("v32", "SupplyAirTemp", raise_transport_errors=True)
        service.disconnect.assert_awaited_once()
    else:
        assert await service.read_register("v32", "SupplyAirTemp") is None
        service.disconnect.assert_not_awaited()
    service.send_command.assert_awaited_once()
