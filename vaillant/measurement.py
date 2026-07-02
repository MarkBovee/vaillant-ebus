"""Measurement subscribe/read — request, subscribe, parse description and list data."""

import json
from typing import Any, cast

from .ship import MsgCounter
from .spine import _spine_addr, send_spine_call, send_spine_read


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
            print(
                f"⚠️  [MEASUREMENT] measurementDescriptionListData unexpected type: {type(mdl).__name__} keys={list(mdl.keys()) if isinstance(mdl, dict) else ''}"
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
            print(
                f"⚠️  [MEASUREMENT] measurementListData unexpected type: {type(ml).__name__} keys={list(ml.keys()) if isinstance(ml, dict) else ''}"
            )
        except Exception:
            pass
        return []

    updates: list[dict[str, Any]] = []
    any_printed = False

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
            continue

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
            print(f"🌡️  Außentemperatur: {val} {unit_str} (ID {mid})")
            any_printed = True
        elif isinstance(scope_str, str) and ("dhwtemperature" in scope_str.lower()):
            print(f"🚿 DHW: {val} {unit_str} (ID {mid})")
            any_printed = True
        elif isinstance(scope_str, str) and (
            "acpowertotal" in scope_str.lower() or "power" == scope_str.lower() or "power" in scope_str.lower()
        ):
            print(f"⚡ Leistung: {val} {unit_str} (ID {mid}, scope={scope_str})")
            any_printed = True
        else:
            print(f"📊 Measurement: {val} {unit_str} (scope={scope_str}, ID {mid})")
            any_printed = True

    if not any_printed:
        # If we got here, list existed but no usable values were found.
        try:
            sample = json.dumps(ml_list[:3], indent=2, ensure_ascii=False)
            print(f"⚠️  [MEASUREMENT] No values parsed; sample entries:\n{sample}")
        except Exception:
            pass

    return updates
