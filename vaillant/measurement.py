"""Measurement subscribe/read — request, subscribe, parse description and list data."""

import json
import logging
from typing import Any, cast

from .ship import MsgCounter
from .spine import _spine_addr, send_spine_call, send_spine_read

_LOGGER = logging.getLogger(__name__)


# POC line 1099
async def request_remote_measurement_once(
    ws,
    *,
    local_device_address: str,
    remote_device_address: str,
    remote_measurement_feature: dict[str, Any],
    msg_counter: MsgCounter,
):
    entity_list = remote_measurement_feature.get("entity")
    feature = remote_measurement_feature.get("feature")
    if not isinstance(entity_list, list) or not entity_list or not all(isinstance(x, int) for x in entity_list):
        return
    if not isinstance(feature, int):
        return

    # Use our Measurement client feature as source.
    src = _spine_addr(device=local_device_address, entity=1, feature=1)
    dst = {"device": remote_device_address, "entity": [int(x) for x in entity_list], "feature": int(feature)}

    await send_spine_read(
        ws,
        address_source=src,
        address_destination=dst,
        cmd={"measurementDescriptionListData": {}},
        msg_counter=msg_counter,
        ack_request=True,
    )
    await send_spine_read(
        ws,
        address_source=src,
        address_destination=dst,
        cmd={"measurementListData": {}},
        msg_counter=msg_counter,
        ack_request=True,
    )


# POC line 1136
async def subscribe_remote_feature(
    ws,
    *,
    local_device_address: str,
    remote_device_address: str,
    feature: dict[str, Any],
    feature_type: str,
    msg_counter: MsgCounter,
):
    entity_list = feature.get("entity")
    feature_id = feature.get("feature")
    if not isinstance(entity_list, list) or not entity_list or not all(isinstance(x, int) for x in entity_list):
        return
    if not isinstance(feature_id, int):
        return

    src_nm = _spine_addr(device=local_device_address, entity=0, feature=0)
    dst_nm = _spine_addr(device=remote_device_address, entity=0, feature=0)
    local_client = _spine_addr(device=local_device_address, entity=1, feature=1)
    remote_server = {
        "device": remote_device_address,
        "entity": [int(x) for x in entity_list],
        "feature": int(feature_id),
    }

    sub_call = {
        "subscriptionRequest": {
            "clientAddress": local_client,
            "serverAddress": remote_server,
            "serverFeatureType": feature_type,
        }
    }
    await send_spine_call(
        ws,
        address_source=src_nm,
        address_destination=dst_nm,
        cmd={"nodeManagementSubscriptionRequestCall": sub_call},
        msg_counter=msg_counter,
        ack_request=True,
    )


async def subscribe_remote_measurement(
    ws,
    *,
    local_device_address: str,
    remote_device_address: str,
    remote_measurement_feature: dict[str, Any],
    msg_counter: MsgCounter,
):
    entity_list = remote_measurement_feature.get("entity")
    feature = remote_measurement_feature.get("feature")
    if not isinstance(entity_list, list) or not entity_list or not all(isinstance(x, int) for x in entity_list):
        return
    if not isinstance(feature, int):
        return

    # NodeManagement call sets up subscriptions.
    src_nm = _spine_addr(device=local_device_address, entity=0, feature=0)
    dst_nm = _spine_addr(device=remote_device_address, entity=0, feature=0)
    local_meas_client = _spine_addr(device=local_device_address, entity=1, feature=1)
    remote_meas_server = {
        "device": remote_device_address,
        "entity": [int(x) for x in entity_list],
        "feature": int(feature),
    }

    sub_call = {
        "subscriptionRequest": {
            "clientAddress": local_meas_client,
            "serverAddress": remote_meas_server,
            "serverFeatureType": "Measurement",
        }
    }
    await send_spine_call(
        ws,
        address_source=src_nm,
        address_destination=dst_nm,
        cmd={"nodeManagementSubscriptionRequestCall": sub_call},
        msg_counter=msg_counter,
        ack_request=True,
    )


async def read_remote_measurement_values(
    ws,
    *,
    local_device_address: str,
    remote_device_address: str,
    remote_measurement_feature: dict[str, Any],
    msg_counter: MsgCounter,
):
    """Read only measurementListData (values), not descriptions. Use in poll loop."""
    entity_list = remote_measurement_feature.get("entity")
    feature = remote_measurement_feature.get("feature")
    if not isinstance(entity_list, list) or not entity_list or not all(isinstance(x, int) for x in entity_list):
        return
    if not isinstance(feature, int):
        return

    src = _spine_addr(device=local_device_address, entity=1, feature=1)
    dst = {"device": remote_device_address, "entity": [int(x) for x in entity_list], "feature": int(feature)}

    await send_spine_read(
        ws,
        address_source=src,
        address_destination=dst,
        cmd={"measurementListData": {}},
        msg_counter=msg_counter,
        ack_request=True,
    )


# POC line 1174
def parse_measurement_description(cmd: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Parse measurementDescriptionListData and return {measurementId: {scopeType, unit, measurementType}}.

    Vaillant/VR921 commonly returns this as:
      {"measurementDescriptionListData": [ {measurementId, scopeType, unit, ...}, ... ]}
    (i.e. the value is a list directly).
    """

    desc_map: dict[int, dict[str, Any]] = {}

    mdl = cmd.get("measurementDescriptionListData")
    mdl_list: list | None = None

    if isinstance(mdl, list):
        mdl_list = mdl
    elif isinstance(mdl, dict):
        # Fallbacks for alternate nesting seen in other stacks.
        if isinstance(mdl.get("measurementDescriptionListData"), list):
            mdl_list = cast(list, mdl.get("measurementDescriptionListData"))
        elif isinstance(mdl.get("measurementDescriptionData"), list):
            mdl_list = cast(list, mdl.get("measurementDescriptionData"))

    if not isinstance(mdl_list, list):
        try:
            _LOGGER.warning(
                "⚠️  [MEASUREMENT] measurementDescriptionListData unexpected type: %s keys=%s",
                type(mdl).__name__,
                list(mdl.keys()) if isinstance(mdl, dict) else "",
            )
        except Exception:
            pass
        return desc_map

    for entry in mdl_list:
        if not isinstance(entry, dict):
            continue
        mid = entry.get("measurementId")
        if not isinstance(mid, int):
            continue
        desc_map[mid] = {
            "scopeType": entry.get("scopeType"),
            "unit": entry.get("unit"),
            "measurementType": entry.get("measurementType"),
        }

    if desc_map:
        scope_summary = {mid: meta["scopeType"] for mid, meta in sorted(desc_map.items())}
        _LOGGER.debug("📋 Measurement descriptions (%d): %s", len(desc_map), scope_summary)

    return desc_map


# POC line 1220
def parse_measurement_list(
    cmd: dict[str, Any],
    desc_map: dict[int, dict[str, Any]],
    *,
    source_address: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Parse measurementListData and return structured updates.

    Vaillant/VR921 commonly returns this as:
      {"measurementListData": [ {measurementId, measurementData:{value:{number,scale}}}, ... ]}
    """

    def _scaled_number_to_float(v: Any) -> float | None:
        if not isinstance(v, dict):
            return None
        number = v.get("number")
        scale = v.get("scale", 0)
        if not isinstance(number, int):
            return None
        if not isinstance(scale, int):
            scale = 0
        try:
            return float(number) * (10.0 ** float(scale))
        except Exception:
            return None

    ml = cmd.get("measurementListData")
    ml_list: list | None = None

    if isinstance(ml, list):
        ml_list = ml
    elif isinstance(ml, dict):
        # Fallback for alternate nesting.
        if isinstance(ml.get("measurementListData"), list):
            ml_list = cast(list, ml.get("measurementListData"))
        elif isinstance(ml.get("measurementData"), list):
            ml_list = cast(list, ml.get("measurementData"))

    if not isinstance(ml_list, list):
        try:
            _LOGGER.warning(
                "⚠️  [MEASUREMENT] measurementListData unexpected type: %s keys=%s",
                type(ml).__name__,
                list(ml.keys()) if isinstance(ml, dict) else "",
            )
        except Exception:
            pass
        return []

    updates: list[dict[str, Any]] = []
    any_printed = False
    skipped_ids: list[int] = []
    parsed_ids: list[int] = []

    src_entity: list[int] | None = None
    src_feature: int | None = None
    if isinstance(source_address, dict):
        ent = source_address.get("entity")
        feat = source_address.get("feature")
        if isinstance(ent, list) and all(isinstance(x, int) for x in ent):
            src_entity = [int(x) for x in ent]
        if isinstance(feat, int):
            src_feature = int(feat)

    for entry in ml_list:
        if not isinstance(entry, dict):
            continue

        mid = entry.get("measurementId")
        mdata = entry.get("measurementData")
        if not isinstance(mid, int):
            continue

        # Prefer the canonical shape: entry.measurementData.value (scaledNumber)
        val = None
        if isinstance(mdata, dict):
            val = _scaled_number_to_float(mdata.get("value"))
        # Fallbacks: some devices may inline value
        if val is None:
            val = _scaled_number_to_float(entry.get("value"))
        if val is None:
            skipped_ids.append(mid)
            if len(skipped_ids) <= 3:
                try:
                    _LOGGER.info("📋 Skipped measurement ID %s raw: %s", mid, json.dumps(entry, ensure_ascii=False))
                except Exception:
                    pass
            continue

        parsed_ids.append(mid)
        meta = desc_map.get(mid, {})
        scope = meta.get("scopeType") or "unknown"
        unit = meta.get("unit") or ""
        mtype = meta.get("measurementType") or ""

        # unit can be string/enum-like; keep it printable
        if isinstance(unit, dict):
            unit = unit.get("unit") or unit.get("name") or json.dumps(unit, separators=(",", ":"), ensure_ascii=False)

        scope_str = scope if isinstance(scope, str) else str(scope)
        unit_str = unit if isinstance(unit, str) else str(unit)
        mtype_str = mtype if isinstance(mtype, str) else str(mtype)

        updates.append(
            {
                "measurementId": mid,
                "scopeType": scope_str,
                "unit": unit_str,
                "measurementType": mtype_str,
                "value": val,
                "source": {"entity": src_entity, "feature": src_feature},
            }
        )

        # Keep human output helpful but short
        if isinstance(scope_str, str) and ("outdoortemperature" in scope_str.lower()):
            _LOGGER.info("🌡️  Außentemperatur: %s %s (ID %s)", val, unit_str, mid)
            any_printed = True
        elif isinstance(scope_str, str) and ("dhwtemperature" in scope_str.lower()):
            _LOGGER.info("🚿 DHW: %s %s (ID %s)", val, unit_str, mid)
            any_printed = True
        elif isinstance(scope_str, str) and (
            "acpowertotal" in scope_str.lower() or "power" == scope_str.lower() or "power" in scope_str.lower()
        ):
            _LOGGER.info("⚡ Leistung: %s %s (ID %s, scope=%s)", val, unit_str, mid, scope_str)
            any_printed = True
        else:
            _LOGGER.info("📊 Measurement: %s %s (scope=%s, ID %s)", val, unit_str, scope_str, mid)
            any_printed = True

    if skipped_ids:
        _LOGGER.info(
            "📋 MeasurementList: parsed IDs=%s, skipped(no-value) IDs=%s",
            parsed_ids, skipped_ids,
        )
        if not parsed_ids:
            try:
                sample = json.dumps(ml_list[:5], indent=2, ensure_ascii=False)
                _LOGGER.warning("⚠️  [MEASUREMENT] No parsable values; sample raw entries:\n%s", sample)
            except Exception:
                pass

    if not any_printed:
        try:
            sample = json.dumps(ml_list[:3], indent=2, ensure_ascii=False)
            _LOGGER.warning("⚠️  [MEASUREMENT] No values printed; sample entries:\n%s", sample)
        except Exception:
            pass

    return updates
