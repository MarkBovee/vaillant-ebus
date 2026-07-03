"""mDNS and entity discovery — MDNSHandler, discovery builders, reply handlers."""

import asyncio
import logging
from typing import Any

from zeroconf import ServiceListener

from . import const
from .ship import MsgCounter, _make_spine_reply_addresses, send_ship_data
from .spine import _spine_addr, send_spine_read

_LOGGER = logging.getLogger(__name__)


# POC line 517
class MDNSHandler(ServiceListener):
    """Collect the first discovered `_ship._tcp.local.` service that isn't ourselves.

    The VR921 advertises itself via mDNS. We listen for services and keep the first
    candidate in `target_info`.
    """

    def __init__(self, ski):
        self.ski, self.target_info = ski, None

    def add_service(self, zc, type, name):
        asyncio.ensure_future(self.async_add_service(zc, type, name))

    async def async_add_service(self, zc, type, name):
        """Async callback invoked by Zeroconf when a new service appears."""
        info = await zc.async_get_service_info(type, name)
        if info and b"ski" in info.properties:
            try:
                remote_ski = info.properties.get(b"ski", b"").decode("utf-8")
            except Exception:
                remote_ski = ""
            if remote_ski and remote_ski == self.ski:
                return
            if not self.target_info:
                self.target_info = info

    def remove_service(self, zc, type, name):
        pass

    def update_service(self, zc, type, name):
        pass


# POC line 794
def _extract_remote_landmap(discovery: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]:
    """Return (heat_pump_entity_address, feature_type_to_feature_address)."""
    heat_pump_entity_addr: dict[str, Any] | None = None
    feature_type_to_addr: dict[str, dict[str, Any]] = {}

    entity_info = discovery.get("entityInformation")
    if isinstance(entity_info, list):
        for item in entity_info:
            if not isinstance(item, dict):
                continue
            desc = item.get("description")
            if not isinstance(desc, dict):
                continue
            if desc.get("entityType") == "HeatPumpAppliance":
                ent_addr = desc.get("entityAddress")
                if isinstance(ent_addr, dict):
                    heat_pump_entity_addr = ent_addr
                    break

    feature_info = discovery.get("featureInformation")
    if isinstance(feature_info, list):
        for item in feature_info:
            if not isinstance(item, dict):
                continue
            desc = item.get("description")
            if not isinstance(desc, dict):
                continue
            feature_type = desc.get("featureType")
            feature_addr = desc.get("featureAddress")
            if isinstance(feature_type, str) and isinstance(feature_addr, dict):
                feature_type_to_addr[feature_type] = feature_addr

    return heat_pump_entity_addr, feature_type_to_addr


# POC line 829
def _entity_addr_list(entity_address: Any) -> list[int] | None:
    if not isinstance(entity_address, dict):
        return None
    entity = entity_address.get("entity")
    if not isinstance(entity, list) or not entity:
        return None
    if not all(isinstance(x, int) for x in entity):
        return None
    return [int(x) for x in entity]


# POC line 840
def _is_prefix(prefix: list[int], value: list[int]) -> bool:
    if len(prefix) > len(value):
        return False
    return value[: len(prefix)] == prefix


# POC line 846
def _extract_entities(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    entity_info = discovery.get("entityInformation")
    if not isinstance(entity_info, list):
        return out
    for item in entity_info:
        if not isinstance(item, dict):
            continue
        desc = item.get("description")
        if not isinstance(desc, dict):
            continue
        ent_addr = _entity_addr_list(desc.get("entityAddress"))
        if ent_addr is None:
            continue
        out.append(
            {
                "entity": ent_addr,
                "entityType": desc.get("entityType"),
                "description": desc.get("description"),
            }
        )
    out.sort(key=lambda d: d.get("entity") or [])
    return out


# POC line 871
def _extract_measurement_servers(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_servers_by_types(discovery).get("Measurement", [])


def _extract_servers_by_types(discovery: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return {featureType: [{entity, feature}, ...]} for all server features."""
    result: dict[str, list[dict[str, Any]]] = {}
    feature_info = discovery.get("featureInformation")
    if not isinstance(feature_info, list):
        return result
    for item in feature_info:
        if not isinstance(item, dict):
            continue
        desc = item.get("description")
        if not isinstance(desc, dict):
            continue
        if desc.get("role") != "server":
            continue
        ftype = desc.get("featureType")
        if not isinstance(ftype, str):
            continue
        faddr = desc.get("featureAddress")
        if not isinstance(faddr, dict):
            continue
        entity = faddr.get("entity")
        feature = faddr.get("feature")
        if not isinstance(entity, list) or not entity or not all(isinstance(x, int) for x in entity):
            continue
        if not isinstance(feature, int):
            continue
        result.setdefault(ftype, []).append({"entity": [int(x) for x in entity], "feature": int(feature)})
    for lst in result.values():
        lst.sort(key=lambda d: (d.get("entity") or [], d.get("feature") or 0))
    return result


def _extract_setpoint_servers(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_servers_by_types(discovery).get("Setpoint", [])


# POC line 591
def build_local_detailed_discovery(local_device_address: str) -> dict[str, Any]:
    """Minimal NodeManagementDetailedDiscoveryData reply.

    Enough to let a remote device identify us and keep the session alive.
    """
    return {
        "specificationVersionList": {"specificationVersion": [const.SPECIFICATION_VERSION]},
        "deviceInformation": {
            "description": {
                "deviceAddress": {"device": local_device_address},
                "deviceType": const.DEVICE_TYPE,
                "featureSet": const.FEATURE_SET,
                "brandName": const.BRAND_NAME,
                "deviceModel": const.DEVICE_MODEL,
                "serialNumber": local_device_address,
                "deviceCode": const.DEVICE_CODE,
            }
        },
        "entityInformation": [
            {
                "description": {
                    "entityAddress": {"entity": [0]},
                    "entityType": const.ENTITY_TYPE_DEVICE_INFORMATION,
                    "description": "DeviceInformation",
                }
            },
            {
                "description": {
                    "entityAddress": {"entity": [1]},
                    "entityType": const.ENTITY_TYPE_CEM,
                    "description": "CEM",
                }
            },
        ],
        "featureInformation": [
            {
                "description": {
                    "featureAddress": {"entity": [0], "feature": 0},
                    "featureType": const.FEATURE_TYPE_NODE_MANAGEMENT,
                    "role": const.ROLE_SPECIAL,
                    "description": "NodeManagement",
                }
            },
            {
                "description": {
                    "featureAddress": {"entity": [0], "feature": 1},
                    "featureType": const.FEATURE_TYPE_DEVICE_CLASSIFICATION,
                    "role": const.ROLE_SERVER,
                    "description": "DeviceClassification",
                }
            },
            {
                "description": {
                    "featureAddress": {"entity": [1], "feature": 1},
                    "featureType": const.FEATURE_TYPE_MEASUREMENT,
                    "role": const.ROLE_CLIENT,
                    "description": "MeasurementClient",
                }
            },
            {
                "description": {
                    "featureAddress": {"entity": [1], "feature": 2},
                    "featureType": const.FEATURE_TYPE_SENSING,
                    "role": const.ROLE_CLIENT,
                    "description": "SensingClient",
                }
            },
        ],
    }


# POC line 662
def build_device_classification_manufacturer_data(local_device_address: str) -> dict[str, Any]:
    """Minimal DeviceClassificationManufacturerData.

    Keep values simple/consistent; VR921 mostly needs something parseable.
    """
    return {
        "deviceName": const.DEVICE_CODE.replace("-", " ").title(),
        "deviceCode": const.DEVICE_CODE,
        "brandName": const.BRAND_NAME,
        "powerSource": "mains3Phase",
        "serialNumber": local_device_address,
    }


# POC line 676
def build_device_classification_user_data() -> dict[str, Any]:
    """Minimal DeviceClassificationUserData."""
    return {
        "deviceName": const.DEVICE_CODE.replace("-", " ").title(),
    }


# POC line 900
async def reply_node_management_detailed_discovery(
    ws,
    *,
    request_header: dict[str, Any],
    local_device_address: str,
    msg_counter: MsgCounter,
):
    """Reply to a SPINE read request for nodeManagementDetailedDiscoveryData."""
    ref = request_header.get("msgCounter")
    if ref is None:
        _LOGGER.warning("⚠️  [SPINE] Kein msgCounter im Request-Header → kann nicht antworten")
        return

    addresses = _make_spine_reply_addresses(request_header, local_device_address=local_device_address)
    if addresses is None:
        _LOGGER.warning("⚠️  [SPINE] Request ohne addressSource/addressDestination → kann nicht antworten")
        return

    address_source, address_destination = addresses

    reply_datagram: dict[str, Any] = {
        "datagram": {
            "header": {
                "specificationVersion": request_header.get("specificationVersion", const.SPECIFICATION_VERSION),
                "addressSource": address_source,
                "addressDestination": address_destination,
                "msgCounter": await msg_counter.next(),
                "msgCounterReference": ref,
                "cmdClassifier": const.CMD_CLASSIFIER_REPLY,
            },
            "payload": {
                "cmd": [
                    {
                        "nodeManagementDetailedDiscoveryData": build_local_detailed_discovery(local_device_address),
                        "function": "nodeManagementDetailedDiscoveryData",
                    }
                ]
            },
        }
    }

    await send_ship_data(ws, reply_datagram)
    _LOGGER.info("📤 [SPINE] Reply gesendet: nodeManagementDetailedDiscoveryData")


# POC line 945
async def reply_device_classification_manufacturer_data(
    ws,
    *,
    request_header: dict[str, Any],
    local_device_address: str,
    msg_counter: MsgCounter,
):
    ref = request_header.get("msgCounter")
    if ref is None:
        return

    addresses = _make_spine_reply_addresses(request_header, local_device_address=local_device_address)
    if addresses is None:
        return
    address_source, address_destination = addresses

    reply_datagram: dict[str, Any] = {
        "datagram": {
            "header": {
                "specificationVersion": request_header.get("specificationVersion", const.SPECIFICATION_VERSION),
                "addressSource": address_source,
                "addressDestination": address_destination,
                "msgCounter": await msg_counter.next(),
                "msgCounterReference": ref,
                "cmdClassifier": const.CMD_CLASSIFIER_REPLY,
            },
            "payload": {
                "cmd": [
                    {
                        "deviceClassificationManufacturerData": build_device_classification_manufacturer_data(
                            local_device_address
                        )
                    }
                ]
            },
        }
    }

    await send_ship_data(ws, reply_datagram)
    _LOGGER.info("📤 [SPINE] Reply gesendet: deviceClassificationManufacturerData")


# POC line 987
async def reply_device_classification_user_data(
    ws,
    *,
    request_header: dict[str, Any],
    local_device_address: str,
    msg_counter: MsgCounter,
):
    ref = request_header.get("msgCounter")
    if ref is None:
        return

    addresses = _make_spine_reply_addresses(request_header, local_device_address=local_device_address)
    if addresses is None:
        return
    address_source, address_destination = addresses

    reply_datagram: dict[str, Any] = {
        "datagram": {
            "header": {
                "specificationVersion": request_header.get("specificationVersion", const.SPECIFICATION_VERSION),
                "addressSource": address_source,
                "addressDestination": address_destination,
                "msgCounter": await msg_counter.next(),
                "msgCounterReference": ref,
                "cmdClassifier": const.CMD_CLASSIFIER_REPLY,
            },
            "payload": {"cmd": [{"deviceClassificationUserData": build_device_classification_user_data()}]},
        }
    }

    await send_ship_data(ws, reply_datagram)
    _LOGGER.info("📤 [SPINE] Reply gesendet: deviceClassificationUserData")


# POC line 1021
async def handle_spine_read(
    ws,
    *,
    request_header: dict[str, Any],
    cmd: dict[str, Any],
    local_device_address: str,
    msg_counter: MsgCounter,
):
    """Handle SPINE cmdClassifier='read' with minimal required replies."""
    if "nodeManagementDetailedDiscoveryData" in cmd:
        await reply_node_management_detailed_discovery(
            ws,
            request_header=request_header,
            local_device_address=local_device_address,
            msg_counter=msg_counter,
        )
        return

    if "deviceClassificationManufacturerData" in cmd:
        await reply_device_classification_manufacturer_data(
            ws,
            request_header=request_header,
            local_device_address=local_device_address,
            msg_counter=msg_counter,
        )
        return

    if "deviceClassificationUserData" in cmd:
        await reply_device_classification_user_data(
            ws,
            request_header=request_header,
            local_device_address=local_device_address,
            msg_counter=msg_counter,
        )
        return

    _LOGGER.warning("⚠️  [SPINE] Unhandled read cmd keys: %s", list(cmd.keys()))


# POC line 1060
async def request_remote_detailed_discovery(
    ws,
    *,
    local_device_address: str,
    remote_device_address: str,
    msg_counter: MsgCounter,
):
    src = _spine_addr(device=local_device_address, entity=0, feature=0)
    dst = _spine_addr(device=remote_device_address, entity=0, feature=0)
    await send_spine_read(
        ws,
        address_source=src,
        address_destination=dst,
        cmd={"nodeManagementDetailedDiscoveryData": {}},
        msg_counter=msg_counter,
    )
    _LOGGER.info("📤 [SPINE] Read gesendet: nodeManagementDetailedDiscoveryData")


# POC line 1079
async def request_remote_node_management_use_case_data(
    ws,
    *,
    local_device_address: str,
    remote_device_address: str,
    msg_counter: MsgCounter,
):
    # Per user requirement: NodeManagement (Entity 0, Feature 0), function nodeManagementUseCaseData
    src = _spine_addr(device=local_device_address, entity=0, feature=0)
    dst = _spine_addr(device=remote_device_address, entity=0, feature=0)
    await send_spine_read(
        ws,
        address_source=src,
        address_destination=dst,
        cmd={"nodeManagementUseCaseData": {}},
        msg_counter=msg_counter,
    )
    _LOGGER.info("📤 [SPINE] Read gesendet: nodeManagementUseCaseData")
