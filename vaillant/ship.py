"""SHIP transport layer — message framing, EEBUS JSON conversion, handshake."""

import asyncio
import json
import logging
import time
from collections import OrderedDict
from typing import Any

_LOGGER = logging.getLogger(__name__)


# POC line 52
class MsgCounter:
    """Async-safe SPINE msgCounter generator.

    SPINE datagrams contain a monotonically increasing msgCounter.
    We guard increments with a lock because this script may send messages from
    different async code paths.
    """

    def __init__(self, start: int = 1):
        self._value = start
        self._lock = asyncio.Lock()

    async def next(self) -> int:
        async with self._lock:
            value = self._value
            self._value += 1
            # SPINE msgCounter is uint64 and may overflow; for this diagnostic client,
            # a simple increment is sufficient.
            return value


# POC line 354
def json_into_eebus_json(payload: Any) -> str:
    """Convert standard JSON objects into the EEBUS array-wrapped JSON format.

    This mirrors the behavior of ship-go's JsonIntoEEBUSJson():
    - Objects (dict) become arrays of single-key objects, recursively.
    - Arrays stay arrays.
    - The top-level array wrapper is stripped.
    """

    def _to_eebus(value: Any) -> Any:
        # ship-go uses an ordered map to preserve field order. Python 3.7+
        # preserves dict insertion order, and we additionally use OrderedDict
        # when parsing from JSON text.
        if isinstance(value, (dict, OrderedDict)):
            return [{k: _to_eebus(v)} for k, v in value.items()]
        if isinstance(value, list):
            return [_to_eebus(v) for v in value]
        return value

    converted = _to_eebus(payload)
    text = json.dumps(converted, separators=(",", ":"), ensure_ascii=False)

    # ship-go trims the first/last bracket (top-level is expected to be an object)
    if text.startswith("[") and text.endswith("]"):
        return text[1:-1]
    return text


# POC line 391
def json_text_into_eebus_json(payload_text: str) -> str:
    """Convert a JSON text into EEBUS JSON using ship-go's ordering approach."""
    parsed = json.loads(payload_text, object_pairs_hook=OrderedDict)
    return json_into_eebus_json(parsed)


# POC line 397
def json_from_eebus_json(payload_text: str) -> str:
    """Convert EEBUS array-wrapped JSON into standard JSON.

    ship-go uses a simple replacement strategy that works for SHIP/SPINE payloads.
    We apply the same rules and also trim trailing NUL bytes (some devices append 0x00).
    """
    b = payload_text.encode("utf-8", errors="ignore")
    b = b.replace(b"[{", b"{")
    b = b.replace(b"},{", b",")
    b = b.replace(b"}]", b"}")
    b = b.replace(b"[]", b"{}")
    b = b.strip(b"\x00")
    return b.decode("utf-8", errors="ignore")


# POC line 412
def _first_cmd(payload_cmd: Any) -> dict[str, Any] | None:
    """Best-effort extraction of the first SPINE cmd object."""
    if isinstance(payload_cmd, dict):
        return payload_cmd

    if not isinstance(payload_cmd, list) or not payload_cmd:
        return None

    first = payload_cmd[0]
    # Sometimes cmd is [[{...}]]
    if isinstance(first, list) and first:
        inner = first[0]
        return inner if isinstance(inner, dict) else None
    return first if isinstance(first, dict) else None


# POC line 428
def _parse_spine_datagram(message: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return (header, first_cmd) from a decoded SHIP data message."""
    data = message.get("data")
    if not isinstance(data, dict):
        return None
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return None
    datagram = payload.get("datagram")
    if not isinstance(datagram, dict):
        return None

    header = datagram.get("header")
    if not isinstance(header, dict):
        return None

    d_payload = datagram.get("payload")
    if not isinstance(d_payload, dict):
        return None

    cmd = _first_cmd(d_payload.get("cmd"))
    if cmd is None:
        return None

    return header, cmd


# POC line 455
def _make_spine_reply_addresses(
    request_header: dict[str, Any],
    *,
    local_device_address: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return (address_source, address_destination) for replies/results.

    SPINE replies swap source/destination. Some devices omit the device field
    in addressDestination in requests; we always set our device on addressSource.
    """
    address_destination = request_header.get("addressSource")
    address_source = request_header.get("addressDestination")
    if not isinstance(address_destination, dict) or not isinstance(address_source, dict):
        return None

    address_source = dict(address_source)
    # Important interop detail:
    # Some devices omit the "device" field in addressDestination when addressing the local side.
    # For result/reply messages, mirror the structure the peer used (do not force-inject "device"
    # unless it was present), otherwise some peers treat it as a protocol error.
    if "device" in address_source:
        address_source["device"] = local_device_address

    return address_source, dict(address_destination)


# POC line 542
async def send_ship_json(ws, data):
    """Sendet SHIP-Control JSON (MessageType=0x01) im EEBUS JSON-Format."""
    # SHIP Control frames are: 0x01 + (EEBUS JSON payload)
    eebus_text = json_into_eebus_json(data)
    msg = b"\x01" + eebus_text.encode("utf-8")
    await ws.send(msg)
    _LOGGER.info("📤 Gesendet: %s", list(data.keys()))


# POC line 551
async def send_ship_data(ws, data):
    """Sendet SHIP-Data JSON (MessageType=0x02) im ship-go kompatiblen Format.

    ship-go serialisiert SPINE in zwei Schritten:
    1) SPINE Datagramm -> EEBUS JSON
    2) SHIP Data Envelope (mit placeholder payload) -> EEBUS JSON
       und danach payload wieder als RawMessage hineinpflastern.

    Damit bleibt das SHIP payload-Objekt unverändert (wird nicht nochmal array-wrapped).
    """

    # SHIP Data frames are: 0x02 + (EEBUS JSON payload)
    # The payload is itself a SHIP "data" envelope containing a SPINE datagram.

    # Expect data to be a standard JSON SPINE message like: {"datagram": {...}}
    spine_std = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    spine_eebus = json_text_into_eebus_json(spine_std)

    payload_placeholder = '{"place":"holder"}'
    ship_std_obj = {
        "data": {
            "header": {"protocolId": "ee1.0"},
            "payload": json.loads(payload_placeholder),
        }
    }
    ship_std = json.dumps(ship_std_obj, separators=(",", ":"), ensure_ascii=False)
    ship_eebus = json_text_into_eebus_json(ship_std)

    # ship-go replaces `[payloadPlaceholder]` with the already-transformed SPINE payload
    ship_eebus = ship_eebus.replace(f"[{payload_placeholder}]", spine_eebus)

    msg = b"\x02" + ship_eebus.encode("utf-8")
    await ws.send(msg)


# POC line 586
async def send_access_methods(ws, local_ship_id: str):
    """Send the SHIP accessMethods response, which carries our local SHIP id."""
    await send_ship_json(ws, {"accessMethods": {"id": local_ship_id}})


# POC line 1355
async def perform_ship_handshake(ws, local_ship_id: str):
    """
    SHIP Handshake nach offizieller Spezifikation:
    Phase 1: CMI (Connection Mode Init) - Initial-Byte
    Phase 2: Hello - Trust establishment
    Phase 3: Protocol - Version negotiation
    Phase 4: PIN - Authentication (nur "none" unterstützt)
    Phase 5: Access - Access methods exchange
    """

    # === PHASE 1: CMI (Connection Mode Init) ===
    init_ack = await ws.recv()
    if isinstance(init_ack, bytes):
        _LOGGER.info("📥 [CMI] Initial-Bytes empfangen: %s", init_ack.hex())
    else:
        _LOGGER.info("📥 [CMI] Initial empfangen (nicht-bytes): %s", init_ack)

    # === PHASE 2: HELLO ===
    _LOGGER.info("📤 [HELLO] Sende connectionHello (phase: ready)...")
    await send_ship_json(ws, {"connectionHello": {"phase": "ready", "waiting": 60000}})

    # State machine for the SHIP handshake phases.
    # We deliberately do not "jump ahead" while the peer is still pending (waiting
    # for the user to press Trust in the myVAILLANT app).
    state = "WAITING_HELLO"
    last_pending_hello_sent = 0.0

    while True:
        try:
            raw_msg = await ws.recv()
        except Exception as e:
            # websockets raises ConnectionClosedError/OK subclasses
            code = getattr(e, "code", None)
            reason = getattr(e, "reason", None)
            _LOGGER.error("❌ WebSocket geschlossen während Handshake: code=%s reason=%s err=%s", code, reason, e)
            return False
        if not isinstance(raw_msg, bytes) or len(raw_msg) < 2:
            continue

        # SHIP control frames use message type 0x01.
        # During/after handshake we might also see data frames (0x02).
        header = raw_msg[0]
        if header != 0x01:
            # During/after handshake we might also see data messages (0x02)
            _LOGGER.warning("⚠️  Unerwarteter SHIP MessageType: 0x%02x (len=%s)", header, len(raw_msg))
            continue

        payload_raw = raw_msg[1:]
        payload_text = payload_raw.decode("utf-8", errors="ignore")
        payload_text = json_from_eebus_json(payload_text)

        try:
            msg = json.loads(payload_text)
            _LOGGER.info("📥 Empfangen: %s", json.dumps(msg, indent=2))
        except json.JSONDecodeError:
            _LOGGER.warning("⚠️  JSON Decode Error: %s", payload_text[:200])
            continue

        # === PHASE 2: HELLO RESPONSE ===
        if "connectionHello" in msg and state == "WAITING_HELLO":
            hello = msg.get("connectionHello") or {}
            phase = hello.get("phase")

            if phase == "pending":
                prolong = hello.get("prolongationRequest")
                waiting_ms = hello.get("waiting")

                _LOGGER.warning(
                    "⏳ [HELLO] PENDING — Approve the EEBUS connection in the "
                    "myVAILLANT app on your phone. The handshake will continue after approval."
                )
                _LOGGER.warning(
                    "⏳ If no prompt appears: put the VR921 into pairing mode "
                    "via the heat pump display or myVAILLANT app."
                )

                if isinstance(waiting_ms, int):
                    _LOGGER.info("⏳ [HELLO] Remote waiting=%sms prolongationRequest=%s", waiting_ms, prolong)
                else:
                    _LOGGER.info("⏳ [HELLO] Remote prolongationRequest=%s", prolong)

                now = time.monotonic()
                if now - last_pending_hello_sent > 5.0:
                    await send_ship_json(ws, {"connectionHello": {"phase": "pending", "waiting": 60000}})
                    last_pending_hello_sent = now

            elif phase == "ready":
                _LOGGER.info("✅ [HELLO] Phase abgeschlossen - beide Seiten READY")

                # === PHASE 3: PROTOCOL HANDSHAKE ===
                _LOGGER.info("📤 [PROTOCOL] Sende messageProtocolHandshake...")
                await send_ship_json(
                    ws,
                    {
                        "messageProtocolHandshake": {
                            "handshakeType": "announceMax",
                            "version": {"major": 1, "minor": 0},
                            "formats": {"format": ["JSON-UTF8"]},
                        }
                    },
                )
                state = "WAITING_PROTOCOL"

            elif phase == "aborted":
                _LOGGER.error("❌ [HELLO] Verbindung von Wärmepumpe abgelehnt (Aborted).")
                return False

        # === PHASE 3: PROTOCOL RESPONSE ===
        elif "messageProtocolHandshake" in msg and state == "WAITING_PROTOCOL":
            handshake = msg.get("messageProtocolHandshake") or {}

            # ship-go client behavior: remote replies with "select" -> client must send "select" confirmation
            handshake_type = handshake.get("handshakeType")
            if handshake_type != "select":
                _LOGGER.error("❌ [PROTOCOL] Unerwarteter handshakeType: %s", handshake_type)
                return False

            # Validiere Protokoll-Version
            version = handshake.get("version", {})
            if version.get("major") != 1:
                _LOGGER.error("❌ [PROTOCOL] Nicht unterstützte Version: %s", version)
                return False

            _LOGGER.info("✅ [PROTOCOL] Protokoll-Handshake bestätigt (Version 1.0)")
            _LOGGER.info("📤 [PROTOCOL] Bestätige Auswahl (select)...")
            await send_ship_json(
                ws,
                {
                    "messageProtocolHandshake": {
                        "handshakeType": "select",
                        "version": {"major": 1, "minor": 0},
                        "formats": {"format": ["JSON-UTF8"]},
                    }
                },
            )

            # === PHASE 4: PIN STATE ===
            _LOGGER.info("📤 [PIN] Sende connectionPinState (none)...")
            await send_ship_json(ws, {"connectionPinState": {"pinState": "none"}})
            state = "WAITING_PIN"

        elif "messageProtocolHandshakeError" in msg:
            err = (msg.get("messageProtocolHandshakeError") or {}).get("error")
            _LOGGER.error("❌ [PROTOCOL] messageProtocolHandshakeError empfangen: error=%s", err)
            return False

        # === PHASE 4: PIN RESPONSE (Optional - manche Geräte bestätigen, manche nicht) ===
        elif "connectionPinState" in msg and state == "WAITING_PIN":
            pin_state = (msg.get("connectionPinState") or {}).get("pinState")
            _LOGGER.info("✅ [PIN] PIN-State bestätigt: %s", pin_state)
            if pin_state != "none":
                _LOGGER.error(
                    "❌ [PIN] Gerät verlangt PIN (oder sendet unerwarteten Zustand). ship-go unterstützt nur 'none'."
                )
                return False

            # === PHASE 5: ACCESS METHODS ===
            _LOGGER.info("📤 [ACCESS] Sende accessMethodsRequest...")
            await send_ship_json(ws, {"accessMethodsRequest": {}})
            state = "WAITING_ACCESS"

        # In ship-go ist PIN eine eigene Phase; ohne PIN-State nicht zur Access-Phase springen.

        # === PHASE 5: ACCESS RESPONSE ===
        elif "accessMethodsRequest" in msg and state == "WAITING_ACCESS":
            _LOGGER.info("📥 [ACCESS] accessMethodsRequest vom Gerät empfangen → sende accessMethods...")
            await send_access_methods(ws, local_ship_id)
            # Stay in WAITING_ACCESS until we receive accessMethods

        elif "accessMethods" in msg and state == "WAITING_ACCESS":
            remote_id = (msg.get("accessMethods") or {}).get("id", "unknown")
            _LOGGER.info("✅ [ACCESS] Access Methods empfangen (Remote ID: %s)", remote_id)
            _LOGGER.info("💎 SHIP HANDSHAKE ERFOLGREICH BEENDET!")
            return True

        elif (
            state == "WAITING_ACCESS"
            and "connectionPinState" not in msg
            and "accessMethods" not in msg
            and "accessMethodsRequest" not in msg
        ):
            # Falls wir im ACCESS-State sind, aber die falsche Nachricht kommt
            _LOGGER.warning("⚠️  [STATE: %s] Unerwartete Nachricht: %s", state, list(msg.keys()))
