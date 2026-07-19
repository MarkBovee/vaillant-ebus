"""VaillantClient — EEBUS SHIP/SPINE client for Vaillant VR921."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
import ssl
import time
from typing import Any, cast

from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from . import const
from .certificate import get_or_create_certificate
from .discovery import (
    MDNSHandler,
    _extract_entities,
    _extract_measurement_servers,
    _extract_remote_landmap,
    _extract_servers_by_types,
    _extract_setpoint_servers,
    handle_spine_read,
    request_remote_detailed_discovery,
    request_remote_node_management_use_case_data,
)
from .measurement import (
    parse_measurement_description,
    parse_measurement_list,
    read_remote_measurement_values,
    request_remote_measurement_once,
    subscribe_remote_feature,
    subscribe_remote_measurement,
)
from .model import CapabilityRegistry, UnknownFeatureRegistry
from .ship import (
    MsgCounter,
    _parse_spine_datagram,
    json_from_eebus_json,
    perform_ship_handshake,
    send_ship_json,
)
from .spine import _spine_addr, send_spine_call, send_spine_read, send_spine_result_ok

_LOGGER = logging.getLogger(__name__)

FEATURE_READ_CMDS: dict[str, list[str]] = {
    "ElectricalConnection": [
        "electricalConnectionParameterDescriptionListData",
        "electricalConnectionParameterListData",
    ],
    "Setpoint": ["setpointData"],
    "HVAC": ["hvacModeListData"],
    "SmartEnergyManagementPs": ["deviceConfigurationData"],
}


def _dump_full_discovery(discovery: dict[str, Any]) -> None:
    """Log VR921 discovery as compact grouped summary."""
    entities = discovery.get("entityInformation", [])
    features = discovery.get("featureInformation", [])
    if isinstance(entities, list):
        by_type: dict[str, list[str]] = {}
        for item in entities:
            if not isinstance(item, dict):
                continue
            desc = item.get("description", {})
            if not isinstance(desc, dict):
                continue
            eaddr = desc.get("entityAddress", {})
            ent = str(eaddr.get("entity")) if isinstance(eaddr, dict) else "?"
            etype = desc.get("entityType", "?")
            by_type.setdefault(etype, []).append(ent)
        groups = [f"{t}={','.join(es)}" for t, es in sorted(by_type.items())]
        _LOGGER.info("📋 VR921 entities: %s", " | ".join(groups))
    if isinstance(features, list):
        by_addr: dict[str, list[str]] = {}
        for item in features:
            if not isinstance(item, dict):
                continue
            desc = item.get("description", {})
            if not isinstance(desc, dict):
                continue
            faddr = desc.get("featureAddress", {})
            ent = str(faddr.get("entity")) if isinstance(faddr, dict) else "?"
            feat = str(faddr.get("feature")) if isinstance(faddr, dict) else "?"
            ftype = desc.get("featureType", "?")
            role = desc.get("role", "?")
            by_addr.setdefault(f"{ftype}({role})", []).append(f"e{ent}f{feat}")
        groups = [f"{t}={','.join(addrs)}" for t, addrs in sorted(by_addr.items())]
        _LOGGER.info("📋 VR921 features: %s", " | ".join(groups))


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unknown"


def _unit_to_ha(unit: Any) -> str:
    if unit is None:
        return ""
    if isinstance(unit, str):
        u = unit.strip()
        if u == "degC":
            return "°C"
        if u == "degF":
            return "°F"
        return u
    if isinstance(unit, dict):
        u = unit.get("unit") or unit.get("name")
        return _unit_to_ha(str(u)) if u is not None else ""
    return str(unit)


def _guess_ha_metadata(scope_type: str, unit: str) -> dict[str, str]:
    s = (scope_type or "").lower()
    u = (unit or "").strip()
    if "temperature" in s:
        return {"device_class": "temperature", "state_class": "measurement", "unit": u or "°C"}
    if "power" in s:
        return {"device_class": "power", "state_class": "measurement", "unit": u or "W"}
    if "energy" in s:
        return {"device_class": "energy", "state_class": "total_increasing", "unit": u or "Wh"}
    if "current" in s:
        return {"device_class": "current", "state_class": "measurement", "unit": u or "A"}
    if "voltage" in s:
        return {"device_class": "voltage", "state_class": "measurement", "unit": u or "V"}
    return {"device_class": "", "state_class": "measurement", "unit": u}


def _friendly_sensor_name(scope_type: str, *, source_entity: list[int] | None = None) -> str:
    s = (scope_type or "").strip()
    low = s.lower()
    if low == "outsideairtemperature":
        return "Outside Temperature"
    if low == "dhwtemperature":
        return "DHW Temperature"
    if low == "roomairtemperature":
        return "Room Temperature"
    if low == "acpowertotal":
        return "Compressor Power"
    if low.startswith("acpower"):
        return "Power"
    if "temperature" in low:
        return "Temperature"
    if source_entity:
        return f"{s} (entity={source_entity})"
    return s or "Measurement"


def _parse_and_register_use_cases(
    use_case_data: dict[str, Any],
    capabilities: CapabilityRegistry,
) -> None:
    data = use_case_data
    if not isinstance(data, dict):
        return
    info = data.get("useCaseInformation") or data.get("nodeManagementUseCaseData")
    if not isinstance(info, list):
        info = [data]
    for entry in info:
        if not isinstance(entry, dict):
            continue
        eaddr = entry.get("entityAddress") or entry.get("entity")
        if not isinstance(eaddr, dict):
            continue
        entity_list = eaddr.get("entity")
        if not isinstance(entity_list, list) or not entity_list:
            continue
        entity = [int(x) for x in entity_list]
        use_cases: list[str] = []
        support_list = entry.get("useCaseSupportList") or entry.get("useCases")
        if isinstance(support_list, list):
            for uc in support_list:
                if not isinstance(uc, dict):
                    continue
                ucinfo = uc.get("useCaseInformation") or uc
                if isinstance(ucinfo, dict):
                    name = ucinfo.get("useCaseName") or ucinfo.get("name") or ""
                    if isinstance(name, str) and name:
                        use_cases.append(name)
        for feat_entry in [entry] if not use_cases else []:
            if "feature" in feat_entry:
                feat_val = feat_entry.get("feature")
                if isinstance(feat_val, int):
                    capabilities.register_use_cases(entity, feat_val, [])
        # No feature address in useCaseData — apply to all capabilities for this entity
        for cap in capabilities.all:
            if tuple(int(x) for x in cap.entity) == tuple(entity):
                best = [uc for uc in use_cases if uc not in cap.supported_use_cases]
                if best:
                    cap.supported_use_cases.extend(best)
                    _LOGGER.info("📋 UseCase: entity=%s use_cases=%s", entity, best)


class _WrappedWs:
    """Wrap a WebSocket to record tx/rx through a SessionRecorder."""

    def __init__(self, ws: Any, recorder: Any) -> None:
        self._ws = ws
        self._recorder = recorder

    async def recv(self) -> Any:
        data = await self._ws.recv()
        if self._recorder and isinstance(data, bytes) and len(data) > 0:
            self._recorder.record_rx(data, msg_type=data[0])
        return data

    async def send(self, data: Any) -> None:
        if self._recorder and isinstance(data, bytes) and len(data) > 0:
            self._recorder.record_tx(data, msg_type=data[0])
        await self._ws.send(data)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ws, name)


class VaillantClient:
    """Manage one EEBUS SHIP/SPINE connection to a Vaillant VR921.

    Call run() to start the full lifecycle. Measurements arrive via the
    callback or are readable via latest_measurements.
    """

    def __init__(
        self,
        *,
        measurement_callback: Any | None = None,
        spine_message_callback: Any | None = None,
        publish_jsonl: bool = False,
        cert_ski: str | None = None,
        recorder: Any | None = None,
        test_transport: Any | None = None,
    ):
        if cert_ski is not None:
            self._cert_ski = cert_ski
        else:
            self._cert_ski = get_or_create_certificate()
        self._msg_counter = MsgCounter()
        self._local_ship_id = f"ha-vaillant-eebus-{self._cert_ski[:12]}"
        self._local_device_address = f"d:_i:1_{self._local_ship_id}"
        self._measurement_callback = measurement_callback
        self._spine_message_callback = spine_message_callback
        self._publish_jsonl = publish_jsonl
        self._recorder = recorder
        self._test_transport = test_transport

        self._ws: Any = None
        self._remote_device_address: str | None = None
        self._aiozc: AsyncZeroconf | None = None
        self._zc_owned = True
        self._task: asyncio.Task | None = None

        self._capabilities = CapabilityRegistry()
        self._unknown = UnknownFeatureRegistry(capacity=100)

        self._latest_measurements: dict[str, dict[str, Any]] = {}
        self._device_info: dict[str, Any] = {}
        self._remote_entities: list[dict[str, Any]] = []
        self._remote_measurement_servers: list[dict[str, Any]] = []
        self._remote_setpoint_servers: list[dict[str, Any]] = []
        self._remote_all_server_features: dict[str, list[dict[str, Any]]] = {}
        self._measurement_desc_maps: dict[tuple[tuple[int, ...], int], dict[int, dict[str, Any]]] = {}
        self._electrical_connection_descriptions: dict[
            tuple[tuple[int, ...], int], dict[int, dict[str, Any]]
        ] = {}
        self._device_config_data: dict[tuple[tuple[int, ...], int], Any] = {}

        self._running = False

    @property
    def latest_measurements(self) -> dict[str, dict[str, Any]]:
        return dict(self._latest_measurements)

    @property
    def device_info(self) -> dict[str, Any]:
        return dict(self._device_info)

    @property
    def measurement_descriptions(self) -> list[dict[str, Any]]:
        descriptions: list[dict[str, Any]] = []
        for (entity, feature), desc_map in sorted(self._measurement_desc_maps.items()):
            for measurement_id, meta in sorted(desc_map.items()):
                descriptions.append(
                    {
                        "entity": list(entity),
                        "feature": feature,
                        "measurementId": measurement_id,
                        **meta,
                    }
                )
        return descriptions

    @property
    def electrical_connection_descriptions(self) -> list[dict[str, Any]]:
        descriptions: list[dict[str, Any]] = []
        for (entity, feature), ec_map in sorted(self._electrical_connection_descriptions.items()):
            for pid, meta in sorted(ec_map.items()):
                descriptions.append(
                    {
                        "entity": list(entity),
                        "feature": feature,
                        "parameterId": pid,
                        **meta,
                    }
                )
        return descriptions

    @property
    def device_config_data(self) -> dict[tuple[tuple[int, ...], int], Any]:
        return dict(self._device_config_data)

    @property
    def connected(self) -> bool:
        return self._running and self._ws is not None

    @property
    def capabilities(self) -> CapabilityRegistry:
        return self._capabilities

    @property
    def unknown(self) -> UnknownFeatureRegistry:
        return self._unknown

    @property
    def setpoint_servers(self) -> list[dict[str, Any]]:
        return list(self._remote_setpoint_servers)

    @property
    def all_server_features(self) -> dict[str, list[dict[str, Any]]]:
        return dict(self._remote_all_server_features)

    async def discover_target(
        self, *, timeout: int = 30, aiozc_instance: AsyncZeroconf | None = None
    ) -> dict[str, Any] | None:
        """Discover VR921 via mDNS. Returns target dict or None."""
        owns_zc = aiozc_instance is None
        aiozc = aiozc_instance or AsyncZeroconf(ip_version=IPVersion.V4Only)
        handler = MDNSHandler(self._cert_ski)

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()

        desc = {"txtvers": "1", "path": "/ship/", "ski": self._cert_ski, "register": "true"}
        info = AsyncServiceInfo(
            const.SHIP_SERVICE_TYPE,
            f"HomeAssistant-Vaillant-EEBUS.{const.SHIP_SERVICE_TYPE}",
            addresses=[socket.inet_aton(local_ip)],
            port=54885,
            properties=desc,
        )
        await aiozc.async_register_service(info, allow_name_change=True)
        AsyncServiceBrowser(aiozc.zeroconf, const.SHIP_SERVICE_TYPE, handler)

        elapsed = 0
        while handler.target_info is None and elapsed < timeout:
            await asyncio.sleep(1)
            elapsed += 1

        if owns_zc:
            await aiozc.async_unregister_all_services()
            await aiozc.async_close()

        if handler.target_info is None:
            return None

        target_ip = socket.inet_ntoa(handler.target_info.addresses[0])
        target_port = handler.target_info.port
        target_ski = handler.target_info.properties.get(b"ski", b"unknown").decode("utf-8")

        return {"host": target_ip, "port": target_port, "ski": target_ski, "local_ip": local_ip}

    async def connect_and_subscribe(
        self, host: str, port: int, *, local_ip: str | None = None
    ) -> bool:
        """Connect, handshake, discover, subscribe, and enter receive loop.

        Returns when connection drops or stop() is called. Returns True
        if at least one cycle of measurements was received.
        """
        await self._run_managed(host, port, local_ip)
        return bool(self._latest_measurements)

    async def start(
        self, host: str, port: int, *, local_ip: str | None = None, aiozc: AsyncZeroconf | None = None
    ) -> None:
        """Start connection in background task."""
        self._task = asyncio.create_task(self._run_managed(host, port, local_ip, aiozc))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._cleanup()

    async def _run_managed(
        self, host: str, port: int, local_ip: str | None, aiozc: AsyncZeroconf | None = None
    ) -> None:
        self._running = True
        try:
            _LOGGER.info("Connecting to %s:%s", host, port)
            await self._run(host, port, local_ip, aiozc)
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOGGER.exception("Connection error")
        finally:
            self._running = False
            await self._cleanup()

    async def _run(self, host: str, port: int, local_ip: str | None, aiozc: AsyncZeroconf | None = None) -> None:
        if self._test_transport is not None:
            self._ws = self._test_transport
            await self._ws.send(b"\x00\x00")
            success = await perform_ship_handshake(self._ws, self._local_ship_id)
            if not success:
                _LOGGER.error("Handshake failed (replay)")
                return
            _LOGGER.info("SHIP handshake successful (replay)")
            await self._receive_loop(self._ws)
            return

        if local_ip is None:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            except Exception:
                local_ip = "0.0.0.0"

        if aiozc is not None:
            self._aiozc = aiozc
            self._zc_owned = False
        else:
            self._aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
            self._zc_owned = True

        if self._zc_owned:
            handler = MDNSHandler(self._cert_ski)
            desc = {"txtvers": "1", "path": "/ship/", "ski": self._cert_ski, "register": "true"}
            info = AsyncServiceInfo(
                const.SHIP_SERVICE_TYPE,
                f"HomeAssistant-Vaillant-EEBUS.{const.SHIP_SERVICE_TYPE}",
                addresses=[socket.inet_aton(local_ip)],
                port=54885,
                properties=desc,
            )
            await self._aiozc.async_register_service(info, allow_name_change=True)
            AsyncServiceBrowser(self._aiozc.zeroconf, const.SHIP_SERVICE_TYPE, handler)

        ssl_ctx = await asyncio.to_thread(self._build_ssl_context)

        try:
            import websockets

            async with websockets.connect(
                f"wss://{host}:{port}/ship/",
                ssl=ssl_ctx,
                subprotocols=cast(Any, ["ship"]),
                open_timeout=const.WS_OPEN_TIMEOUT,
                    ) as ws:
                if self._recorder:
                    ws = _WrappedWs(ws, self._recorder)
                self._ws = ws
                await ws.send(b"\x00\x00")

                success = await perform_ship_handshake(ws, self._local_ship_id)
                if not success:
                    _LOGGER.error("Handshake failed")
                    return

                _LOGGER.info("SHIP handshake successful")
                await self._receive_loop(ws)
        except OSError as e:
            _LOGGER.error("Connection failed: %s", e)
        finally:
            self._ws = None

    async def _receive_loop(self, ws: Any) -> None:
        message_count = 0
        remote_device_address: str | None = None
        discovery_requested = False
        remote_feature_map: dict[str, dict[str, Any]] = {}
        peer_use_case_received = False
        measurement_subscription_sent = False
        measurement_read_sent = False
        selected_measurement_servers: list[dict[str, Any]] = []
        poll_task: asyncio.Task | None = None

        def _desc_key_from_address(addr: Any) -> tuple[tuple[int, ...], int] | None:
            if not isinstance(addr, dict):
                return None
            ent = addr.get("entity")
            feat = addr.get("feature")
            if not (isinstance(ent, list) and ent and all(isinstance(x, int) for x in ent)):
                return None
            if not isinstance(feat, int):
                return None
            return (tuple(int(x) for x in ent), int(feat))

        try:
            while True:
                try:
                    data = await asyncio.wait_for(ws.recv(), timeout=const.WS_RECV_TIMEOUT)
                except TimeoutError:
                    try:
                        await send_ship_json(
                            ws,
                            {"connectionHello": {"phase": "ready", "waiting": const.HELLO_WAITING_MS}},
                        )
                    except Exception:
                        pass
                    continue

                message_count += 1

                if not isinstance(data, bytes) or len(data) == 0:
                    continue

                if data[0] == 1:
                    continue

                if data[0] != 2:
                    continue

                try:
                    payload_text = data[1:].decode("utf-8", errors="ignore")
                    payload_text = json_from_eebus_json(payload_text)
                    msg = json.loads(payload_text)

                    parsed = _parse_spine_datagram(msg)
                    if parsed is None:
                        continue

                    hdr, cmd = parsed
                    cmd_classifier = hdr.get("cmdClassifier")
                    if self._spine_message_callback:
                        try:
                            self._spine_message_callback(hdr, cmd, cmd_classifier)
                        except Exception:
                            pass

                    if remote_device_address is None:
                        addr_src = hdr.get("addressSource")
                        if isinstance(addr_src, dict):
                            dev = addr_src.get("device")
                            if isinstance(dev, str) and dev:
                                remote_device_address = dev
                                self._remote_device_address = dev

                    if remote_device_address is not None and not discovery_requested:
                        discovery_requested = True
                        await request_remote_detailed_discovery(
                            ws,
                            local_device_address=self._local_device_address,
                            remote_device_address=remote_device_address,
                            msg_counter=self._msg_counter,
                        )

                    try:
                        if cmd_classifier != "result":
                            await send_spine_result_ok(
                                ws,
                                request_header=hdr,
                                local_device_address=self._local_device_address,
                                msg_counter=self._msg_counter,
                            )

                        if cmd_classifier == "result":
                            if "resultData" in cmd:
                                rd = cmd.get("resultData", {})
                                err = rd.get("errorNumber")
                                _LOGGER.debug("📋 Call result errorNumber=%s", err)

                        elif cmd_classifier == "read":
                            await handle_spine_read(
                                ws,
                                request_header=hdr,
                                cmd=cmd,
                                local_device_address=self._local_device_address,
                                msg_counter=self._msg_counter,
                            )

                        elif cmd_classifier == "reply":
                            if "nodeManagementDetailedDiscoveryData" in cmd:
                                discovery = cmd.get("nodeManagementDetailedDiscoveryData")
                                if isinstance(discovery, dict):
                                    hp_entity, feature_map = _extract_remote_landmap(discovery)
                                    remote_feature_map.update(feature_map)
                                    self._remote_entities = _extract_entities(discovery)
                                    self._remote_measurement_servers = _extract_measurement_servers(discovery)
                                    self._remote_setpoint_servers = _extract_setpoint_servers(discovery)
                                    self._remote_all_server_features = _extract_servers_by_types(discovery)

                                    _dump_full_discovery(discovery)

                                    if remote_device_address:
                                        self._capabilities.register_from_discovery(
                                            remote_device_address, discovery
                                        )

                                    self._device_info = {
                                        "entities": self._remote_entities,
                                        "feature_map": remote_feature_map,
                                        "remote_device_address": remote_device_address,
                                        "setpoint_servers": list(self._remote_setpoint_servers),
                                    }

                                    skip = {"Measurement", "NodeManagement", "DeviceClassification"}
                                    explore_types = [t for t in self._remote_all_server_features if t not in skip]
                                    if explore_types:
                                        _LOGGER.info("📋 Exploring server features: %s", explore_types)

                                    if self._remote_measurement_servers:
                                        selected_measurement_servers = list(self._remote_measurement_servers)

                                    if remote_device_address is not None:
                                        await request_remote_node_management_use_case_data(
                                            ws,
                                            local_device_address=self._local_device_address,
                                            remote_device_address=remote_device_address,
                                            msg_counter=self._msg_counter,
                                        )

                            elif "nodeManagementUseCaseData" in cmd:
                                peer_use_case_received = True
                                use_case_data = cmd.get("nodeManagementUseCaseData", {})
                                _LOGGER.info("📋 UseCaseData: %s", json.dumps(use_case_data, indent=2)[:2000])
                                # Store use cases per feature for capability enrichment
                                if isinstance(use_case_data, dict):
                                    _parse_and_register_use_cases(use_case_data, self._capabilities)
                                if not selected_measurement_servers and self._remote_measurement_servers:
                                    selected_measurement_servers = list(self._remote_measurement_servers)

                            elif "measurementDescriptionListData" in cmd:
                                desc_map = parse_measurement_description(cmd)
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                if key is not None and desc_map:
                                    self._measurement_desc_maps[key] = desc_map
                                    self._capabilities.load_measurement_descriptions(
                                        list(key[0]), key[1], desc_map
                                    )

                            elif "measurementListData" in cmd:
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                desc_map = self._measurement_desc_maps.get(key, {}) if key is not None else {}
                                updates = parse_measurement_list(
                                    cmd,
                                    desc_map,
                                    source_address=hdr.get("addressSource") if isinstance(hdr, dict) else None,
                                )
                                self._process_measurement_updates(updates)

                            elif "deviceConfigurationData" in cmd:
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                config_data = cmd.get("deviceConfigurationData")
                                if key is not None:
                                    self._device_config_data[key] = config_data
                                _LOGGER.info("📋 DeviceConfigurationData (%s): %s", key, config_data)

                            elif "electricalConnectionParameterDescriptionListData" in cmd:
                                descs = cmd.get("electricalConnectionParameterDescriptionListData", {}).get(
                                    "electricalConnectionParameterDescriptionData", []
                                )
                                _LOGGER.info("📋 ElectricalConnection params: %d measurements mapped", len(descs))
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                if key is not None:
                                    ec_map: dict[int, dict[str, Any]] = {}
                                    for d in descs if isinstance(descs, list) else []:
                                        pid = d.get("parameterId")
                                        if isinstance(pid, int):
                                            ec_map[pid] = {
                                                "scopeType": d.get("scopeType"),
                                                "unit": d.get("unit"),
                                                "measurementType": d.get("measurementType"),
                                            }
                                    self._electrical_connection_descriptions[key] = ec_map
                                    self._capabilities.load_electrical_connection_descriptions(
                                        list(key[0]), key[1], ec_map
                                    )
                                    _LOGGER.info(
                                        "📋 EC descriptions (%d): %s",
                                        len(ec_map),
                                        {pid: m["scopeType"] for pid, m in sorted(ec_map.items())},
                                    )

                            elif "electricalConnectionParameterListData" in cmd:
                                vals = cmd.get("electricalConnectionParameterListData", {}).get(
                                    "electricalConnectionParameterData", []
                                )
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                ec_desc = self._electrical_connection_descriptions.get(key, {}) if key else {}
                                if isinstance(vals, list):
                                    for v in vals:
                                        pid = v.get("parameterId")
                                        if not isinstance(pid, int):
                                            continue
                                        meta = ec_desc.get(pid, {})
                                        scope = meta.get("scopeType", "unknown")
                                        unit = _unit_to_ha(meta.get("unit", ""))
                                        raw_val = v.get("value", {})
                                        number = raw_val.get("number") if isinstance(raw_val, dict) else None
                                        scale = raw_val.get("scale", 0) if isinstance(raw_val, dict) else 0
                                        if isinstance(number, int):
                                            value = float(number) * (10.0 ** float(scale))
                                        else:
                                            value = None
                                        _LOGGER.info(
                                            "⚡ EC value: %s = %s %s (ID %s)",
                                            scope, value, unit, pid,
                                        )
                                        if value is not None and scope != "unknown":
                                            self._capabilities.update_value(
                                                list(key[0]), key[1], value,
                                                scope_type=scope,
                                                unit=unit,
                                                measurement_id=pid,
                                            )
                                            object_id = _slug(f"{scope}_ec_pid{pid}")
                                            src_entity = key[0] if key else None
                                            src_feature = key[1] if key else None
                                            self._latest_measurements[object_id] = {
                                                "value": value,
                                                "unit": unit,
                                                "scopeType": scope,
                                                "measurementId": pid,
                                                "source": {"entity": src_entity, "feature": src_feature},
                                                "ts": time.time(),
                                            }

                            elif "hvacModeListData" in cmd:
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                hvac = cmd.get("hvacModeListData", {})
                                mode_list = (
                                    hvac if isinstance(hvac, list)
                                    else hvac.get("hvacMode", []) if isinstance(hvac, dict)
                                    else []
                                )
                                if isinstance(mode_list, list) and mode_list:
                                    mode = mode_list[0].get("mode") if isinstance(mode_list[0], dict) else None
                                    if key is not None and mode is not None:
                                        self._capabilities.update_value(
                                            list(key[0]), key[1], mode,
                                            scope_type="hvacMode",
                                        )
                                        _LOGGER.info("📋 HVAC mode (reply): entity=%s mode=%s", list(key[0]), mode)

                            elif "setpointData" in cmd:
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                sd = cmd.get("setpointData", {})
                                sp_list = (
                                    sd if isinstance(sd, list)
                                    else sd.get("setpoints", []) if isinstance(sd, dict)
                                    else []
                                )
                                if isinstance(sp_list, list) and sp_list:
                                    val = None
                                    for sp in sp_list:
                                        if isinstance(sp, dict) and "value" in sp:
                                            val = sp["value"]
                                            break
                                    if key is not None and val is not None:
                                        self._capabilities.update_value(
                                            list(key[0]), key[1], val,
                                            scope_type="setpoint",
                                        )
                                        _LOGGER.info("📋 Setpoint (reply): entity=%s value=%s", list(key[0]), val)

                            else:
                                cmd_name = list(cmd.keys())[0]
                                self._unknown.record_command(cmd_name, hdr, cmd, direction="rx")
                                _LOGGER.debug("📋 Unhandled reply cmd=%s: %s", cmd_name, str(cmd)[:200])

                        elif cmd_classifier == "notify":
                            if "measurementDescriptionListData" in cmd:
                                desc_map = parse_measurement_description(cmd)
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                if key is not None and desc_map:
                                    self._measurement_desc_maps[key] = desc_map

                            elif "measurementListData" in cmd:
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                desc_map = self._measurement_desc_maps.get(key, {}) if key is not None else {}
                                updates = parse_measurement_list(
                                    cmd,
                                    desc_map,
                                    source_address=hdr.get("addressSource") if isinstance(hdr, dict) else None,
                                )
                                self._process_measurement_updates(updates)

                            elif "deviceConfigurationData" in cmd:
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                config_data = cmd.get("deviceConfigurationData")
                                if key is not None:
                                    self._device_config_data[key] = config_data
                                    self._capabilities.update_value(
                                        list(key[0]), key[1], config_data,
                                        scope_type="deviceConfiguration",
                                    )
                                _LOGGER.info("📋 DeviceConfigurationData(nfy) (%s): %s", key, config_data)

                            elif "hvacModeListData" in cmd:
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                _LOGGER.info("📋 HVAC mode notify: %s", str(cmd)[:500])
                                hvac = cmd.get("hvacModeListData", {})
                                mode_list = (
                                    hvac if isinstance(hvac, list)
                                    else hvac.get("hvacMode", []) if isinstance(hvac, dict)
                                    else []
                                )
                                if isinstance(mode_list, list) and mode_list:
                                    mode = mode_list[0].get("mode") if isinstance(mode_list[0], dict) else None
                                    if key is not None and mode is not None:
                                        self._capabilities.update_value(
                                            list(key[0]), key[1], mode,
                                            scope_type="hvacMode",
                                        )

                            elif "setpointData" in cmd:
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                _LOGGER.info("📋 Setpoint notify: %s", str(cmd)[:500])
                                sp = cmd.get("setpointData", {})
                                setpoints = (
                                    sp if isinstance(sp, list)
                                    else sp.get("setpoints", []) if isinstance(sp, dict)
                                    else []
                                )
                                if isinstance(setpoints, list):
                                    for sp_entry in setpoints:
                                        if not isinstance(sp_entry, dict):
                                            continue
                                        val = sp_entry.get("value")
                                        sid = sp_entry.get("setpointId")
                                        if val is not None and key is not None:
                                            self._capabilities.update_value(
                                                list(key[0]), key[1], float(val),
                                                scope_type="setpoint",
                                                measurement_id=sid if isinstance(sid, int) else None,
                                            )

                            elif "smartEnergyManagementData" in cmd:
                                key = _desc_key_from_address(hdr.get("addressSource"))
                                _LOGGER.info("📋 SmartEnergy notify: %s", str(cmd)[:500])
                                if key is not None:
                                    self._capabilities.update_value(
                                        list(key[0]), key[1], cmd.get("smartEnergyManagementData"),
                                        scope_type="smartEnergy",
                                    )

                            else:
                                cmd_name = list(cmd.keys())[0]
                                self._unknown.record_command(cmd_name, hdr, cmd, direction="rx")
                                _LOGGER.debug("📋 Unhandled notify cmd=%s: %s", cmd_name, str(cmd)[:200])

                        if (
                            peer_use_case_received
                            and remote_device_address is not None
                            and selected_measurement_servers
                            and not measurement_subscription_sent
                        ):
                            measurement_subscription_sent = True
                            for server in selected_measurement_servers:
                                await subscribe_remote_measurement(
                                    ws,
                                    local_device_address=self._local_device_address,
                                    remote_device_address=remote_device_address,
                                    remote_measurement_feature=server,
                                    msg_counter=self._msg_counter,
                                )

                            sub_types = {"Setpoint", "HVAC", "SmartEnergyManagementPs", "ElectricalConnection"}
                            for ftype in sub_types:
                                servers = self._remote_all_server_features.get(ftype, [])
                                for server in servers:
                                    await subscribe_remote_feature(
                                        ws,
                                        local_device_address=self._local_device_address,
                                        remote_device_address=remote_device_address,
                                        feature=server,
                                        feature_type=ftype,
                                        msg_counter=self._msg_counter,
                                    )

                        if (
                            peer_use_case_received
                            and remote_device_address is not None
                            and selected_measurement_servers
                            and not measurement_read_sent
                        ):
                            measurement_read_sent = True
                            for server in selected_measurement_servers:
                                await request_remote_measurement_once(
                                    ws,
                                    local_device_address=self._local_device_address,
                                    remote_device_address=remote_device_address,
                                    remote_measurement_feature=server,
                                    msg_counter=self._msg_counter,
                                )
                            if poll_task is None:
                                poll_task = asyncio.create_task(
                                    self._poll_measurements_loop(
                                        ws,
                                        remote_device_address=remote_device_address,
                                        measurement_servers=list(selected_measurement_servers),
                                    )
                                )

                            src = _spine_addr(device=self._local_device_address, entity=1, feature=1)
                            for ftype, servers in self._remote_all_server_features.items():
                                if ftype in ("NodeManagement", "DeviceClassification"):
                                    continue
                                cmds = FEATURE_READ_CMDS.get(ftype)
                                if not cmds or not servers:
                                    continue
                                for server in servers:
                                    dst = {
                                        "device": remote_device_address,
                                        "entity": list(server["entity"]),
                                        "feature": int(server["feature"]),
                                    }
                                    for cmd_name in cmds:
                                        await send_spine_read(
                                            ws,
                                            address_source=src,
                                            address_destination=dst,
                                            cmd={cmd_name: {}},
                                            msg_counter=self._msg_counter,
                                        )

                    except Exception:
                        _LOGGER.exception("SPINE processing error")

                except Exception:
                    _LOGGER.exception("Message decode error")
        finally:
            if poll_task is not None:
                poll_task.cancel()
                try:
                    await poll_task
                except asyncio.CancelledError:
                    pass

    async def _poll_measurements_loop(
        self,
        ws: Any,
        *,
        remote_device_address: str,
        measurement_servers: list[dict[str, Any]],
    ) -> None:
        while True:
            await asyncio.sleep(const.POLL_FALLBACK_INTERVAL)
            _LOGGER.debug("🔁 Poll fallback: reading %d measurement servers", len(measurement_servers))
            for server in measurement_servers:
                await read_remote_measurement_values(
                    ws,
                    local_device_address=self._local_device_address,
                    remote_device_address=remote_device_address,
                    remote_measurement_feature=server,
                    msg_counter=self._msg_counter,
                )

            src = _spine_addr(device=self._local_device_address, entity=1, feature=1)
            for ftype, cmds in FEATURE_READ_CMDS.items():
                servers = self._remote_all_server_features.get(ftype, [])
                for server in servers:
                    dst = {
                        "device": remote_device_address,
                        "entity": list(server["entity"]),
                        "feature": int(server["feature"]),
                    }
                    for cmd_name in cmds:
                        await send_spine_read(
                            ws,
                            address_source=src,
                            address_destination=dst,
                            cmd={cmd_name: {}},
                            msg_counter=self._msg_counter,
                        )

    async def write_setpoint(
        self, server: dict[str, Any], temperature: float
    ) -> dict[str, Any] | None:
        """Send SPINE call to set a temperature setpoint on Setpoint server feature."""
        if not self._ws or not self._remote_device_address:
            _LOGGER.warning("Cannot write setpoint: not connected")
            return None
        src = _spine_addr(device=self._local_device_address, entity=1, feature=1)
        dst = {
            "device": self._remote_device_address,
            "entity": list(server["entity"]),
            "feature": int(server["feature"]),
        }
        cmd = {
            "setpointData": {
                "setpoints": [{"setpointId": 0, "value": temperature, "valueType": "temperature"}]
            }
        }
        await send_spine_call(
            self._ws,
            address_source=src,
            address_destination=dst,
            cmd=cmd,
            msg_counter=self._msg_counter,
        )
        _LOGGER.info("📝 Setpoint written: %s → %s °C", dst, temperature)
        return {"errorNumber": 0}

    async def write_hvac_mode(
        self, server: dict[str, Any], mode: str
    ) -> dict[str, Any] | None:
        """Send SPINE call to set HVAC operating mode on HVAC server feature."""
        if not self._ws or not self._remote_device_address:
            _LOGGER.warning("Cannot write HVAC mode: not connected")
            return None
        src = _spine_addr(device=self._local_device_address, entity=1, feature=1)
        dst = {
            "device": self._remote_device_address,
            "entity": list(server["entity"]),
            "feature": int(server["feature"]),
        }
        cmd = {
            "hvacModeListData": {
                "hvacMode": [{"mode": mode, "operatingMode": "normal"}]
            }
        }
        await send_spine_call(
            self._ws,
            address_source=src,
            address_destination=dst,
            cmd=cmd,
            msg_counter=self._msg_counter,
        )
        _LOGGER.info("📝 HVAC mode written: %s → %s", dst, mode)
        return {"errorNumber": 0}

    def _process_measurement_updates(self, updates: list[dict[str, Any]]) -> None:
        for u in updates:
            scope = str(u.get("scopeType") or "unknown")
            unit = _unit_to_ha(u.get("unit"))
            mid = u.get("measurementId")
            src = u.get("source") if isinstance(u.get("source"), dict) else {}
            ent = src.get("entity") if isinstance(src, dict) else None
            feat = src.get("feature") if isinstance(src, dict) else None
            value = u.get("value")

            if value is not None and isinstance(ent, list) and isinstance(feat, int):
                self._capabilities.update_value(
                    ent, feat, value,
                    scope_type=scope,
                    unit=unit,
                    measurement_id=mid if isinstance(mid, int) else None,
                )

            object_id = _slug(
                f"{scope}_e{'_'.join(str(x) for x in ent) if isinstance(ent, list) else 'na'}"
                f"_f{feat if isinstance(feat, int) else 'na'}_id{mid}"
            )

            self._latest_measurements[object_id] = {
                "value": value,
                "unit": unit,
                "scopeType": scope,
                "measurementId": mid,
                "source": src,
                "ts": time.time(),
            }

            if self._publish_jsonl:
                print(json.dumps(
                    {"type": "measurement", "object_id": object_id, **self._latest_measurements[object_id]},
                    ensure_ascii=False, separators=(",", ":"),
                ))

        if updates and self._measurement_callback:
            try:
                if asyncio.iscoroutinefunction(self._measurement_callback):
                    asyncio.ensure_future(self._measurement_callback(self._latest_measurements))
                else:
                    self._measurement_callback(self._latest_measurements)
            except Exception:
                _LOGGER.exception("Measurement callback error")

    def _build_ssl_context(self) -> ssl.SSLContext:
        ssl_ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_ctx.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        ssl_ctx.set_ciphers(const.TLS_CIPHERS)
        return ssl_ctx

    async def _cleanup(self) -> None:
        if self._aiozc and self._zc_owned:
            try:
                await self._aiozc.async_unregister_all_services()
                await self._aiozc.async_close()
            except Exception:
                pass
        self._aiozc = None
        self._ws = None
