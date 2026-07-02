"""SPINE datagram helpers — address builder, read/call/result senders."""

from typing import Any

from . import const
from .ship import MsgCounter, _make_spine_reply_addresses, send_ship_data


# POC line 683
def _spine_addr(*, device: str, entity: int, feature: int) -> dict[str, Any]:
    """Convenience builder for a SPINE feature address (device/entity/feature)."""
    return {"device": device, "entity": [entity], "feature": feature}


# POC line 693
async def send_spine_read(
    ws,
    *,
    address_source: dict[str, Any],
    address_destination: dict[str, Any],
    cmd: dict[str, Any],
    msg_counter: MsgCounter,
    specification_version: str = const.SPECIFICATION_VERSION,
    ack_request: bool = True,
):
    """Send a SPINE read datagram to the remote device."""
    try:
        print(f"📤 [SPINE] Read send: {list(cmd.keys())}")
    except Exception:
        pass
    datagram: dict[str, Any] = {
        "datagram": {
            "header": {
                "specificationVersion": specification_version,
                "addressSource": address_source,
                "addressDestination": address_destination,
                "msgCounter": await msg_counter.next(),
                "cmdClassifier": const.CMD_CLASSIFIER_READ,
                "ackRequest": ack_request,
            },
            "payload": {"cmd": [cmd]},
        }
    }
    await send_ship_data(ws, datagram)


# POC line 724
async def send_spine_call(
    ws,
    *,
    address_source: dict[str, Any],
    address_destination: dict[str, Any],
    cmd: dict[str, Any],
    msg_counter: MsgCounter,
    specification_version: str = const.SPECIFICATION_VERSION,
    ack_request: bool = True,
):
    """Send a SPINE call datagram to the remote device."""
    try:
        print(f"📤 [SPINE] Call send: {list(cmd.keys())}")
    except Exception:
        pass
    datagram: dict[str, Any] = {
        "datagram": {
            "header": {
                "specificationVersion": specification_version,
                "addressSource": address_source,
                "addressDestination": address_destination,
                "msgCounter": await msg_counter.next(),
                "cmdClassifier": const.CMD_CLASSIFIER_CALL,
                "ackRequest": ack_request,
            },
            "payload": {"cmd": [cmd]},
        }
    }
    await send_ship_data(ws, datagram)


# POC line 755
async def send_spine_result_ok(
    ws,
    *,
    request_header: dict[str, Any],
    local_device_address: str,
    msg_counter: MsgCounter,
):
    """Send SPINE cmdClassifier='result' (errorNumber 0) acknowledging a received datagram."""
    ref = request_header.get("msgCounter")
    if ref is None:
        return

    addresses = _make_spine_reply_addresses(request_header, local_device_address=local_device_address)
    if addresses is None:
        return

    address_source, address_destination = addresses

    result_datagram: dict[str, Any] = {
        "datagram": {
            "header": {
                "specificationVersion": request_header.get("specificationVersion", const.SPECIFICATION_VERSION),
                "addressSource": address_source,
                "addressDestination": address_destination,
                "msgCounter": await msg_counter.next(),
                "msgCounterReference": ref,
                "cmdClassifier": const.CMD_CLASSIFIER_RESULT,
            },
            "payload": {"cmd": [{"resultData": {"errorNumber": 0}}]},
        }
    }

    await send_ship_data(ws, result_datagram)
    try:
        print(f"📤 [SPINE] Result send: msgCounterReference={ref}")
    except Exception:
        pass
