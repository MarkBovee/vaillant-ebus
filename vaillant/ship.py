"""SHIP transport layer — message framing, EEBUS JSON conversion, handshake."""

import asyncio
import json
import time
from collections import OrderedDict
from typing import Any


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
    print(f"📤 Gesendet: {list(data.keys())}")


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
        print(f"📥 [CMI] Initial-Bytes empfangen: {init_ack.hex()}")
    else:
        print(f"📥 [CMI] Initial empfangen (nicht-bytes): {init_ack}")

    # === PHASE 2: HELLO ===
    print("📤 [HELLO] Sende connectionHello (phase: ready)...")
    await send_ship_json(ws, {"connectionHello": {"phase": "ready", "waiting": 60000}})

    # State machine for the SHIP handshake phases.
    # We deliberately do not "jump ahead" while the peer is still pending (waiting
    # for the user to press Trust in the myVAILLANT app).
    state = "WAITING_HELLO"
    protocol_handshake_received = False
    pin_state_received = False
    last_pending_hello_sent = 0.0

    while True:
        try:
            raw_msg = await ws.recv()
        except Exception as e:
            # websockets raises ConnectionClosedError/OK subclasses
            code = getattr(e, "code", None)
            reason = getattr(e, "reason", None)
            print(f"❌ WebSocket geschlossen während Handshake: code={code} reason={reason} err={e}")
            return False
        if not isinstance(raw_msg, bytes) or len(raw_msg) < 2:
            continue

        # SHIP control frames use message type 0x01.
        # During/after handshake we might also see data frames (0x02).
        header = raw_msg[0]
        if header != 0x01:
            # During/after handshake we might also see data messages (0x02)
            print(f"⚠️  Unerwarteter SHIP MessageType: 0x{header:02x} (len={len(raw_msg)})")
            continue

        payload_raw = raw_msg[1:]
        payload_text = payload_raw.decode("utf-8", errors="ignore")
        payload_text = json_from_eebus_json(payload_text)

        try:
            msg = json.loads(payload_text)
            print(f"📥 Empfangen: {json.dumps(msg, indent=2)}")
        except json.JSONDecodeError:
            print(f"⚠️  JSON Decode Error: {payload_text[:200]}")
            continue

        # === PHASE 2: HELLO RESPONSE ===
        if "connectionHello" in msg and state == "WAITING_HELLO":
            hello = msg.get("connectionHello") or {}
            phase = hello.get("phase")

            if phase == "pending":
                prolong = hello.get("prolongationRequest")
                waiting_ms = hello.get("waiting")

                print("⏳ [HELLO] STATUS: PENDING - Warte auf Bestätigung in der myVAILLANT App...")
                print("👉 JETZT in der App den Zugriff bestätigen!")

                # Important: while the remote side is still pending (waiting for user trust/pairing),
                # we MUST NOT proceed to protocol/pin/access. To keep the hello phase alive and
                # avoid timeouts, we answer with our own PENDING + waiting.
                if isinstance(waiting_ms, int):
                    print(f"⏳ [HELLO] Remote waiting={waiting_ms}ms prolongationRequest={prolong}")
                else:
                    print(f"⏳ [HELLO] Remote prolongationRequest={prolong}")

                now = time.monotonic()
                if now - last_pending_hello_sent > 5.0:
                    await send_ship_json(ws, {"connectionHello": {"phase": "pending", "waiting": 60000}})
                    last_pending_hello_sent = now
                # Bleibe in WAITING_HELLO State

            elif phase == "ready":
                print("✅ [HELLO] Phase abgeschlossen - beide Seiten READY")

                # === PHASE 3: PROTOCOL HANDSHAKE ===
                print("📤 [PROTOCOL] Sende messageProtocolHandshake...")
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
                print("❌ [HELLO] Verbindung von Wärmepumpe abgelehnt (Aborted).")
                return False

        # === PHASE 3: PROTOCOL RESPONSE ===
        elif "messageProtocolHandshake" in msg and state == "WAITING_PROTOCOL":
            handshake = msg.get("messageProtocolHandshake") or {}

            # ship-go client behavior: remote replies with "select" -> client must send "select" confirmation
            handshake_type = handshake.get("handshakeType")
            if handshake_type != "select":
                print(f"❌ [PROTOCOL] Unerwarteter handshakeType: {handshake_type}")
                return False

            # Validiere Protokoll-Version
            version = handshake.get("version", {})
            if version.get("major") != 1:
                print(f"❌ [PROTOCOL] Nicht unterstützte Version: {version}")
                return False

            print("✅ [PROTOCOL] Protokoll-Handshake bestätigt (Version 1.0)")
            protocol_handshake_received = True

            print("📤 [PROTOCOL] Bestätige Auswahl (select)...")
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
            print("📤 [PIN] Sende connectionPinState (none)...")
            await send_ship_json(ws, {"connectionPinState": {"pinState": "none"}})
            state = "WAITING_PIN"

        elif "messageProtocolHandshakeError" in msg:
            err = (msg.get("messageProtocolHandshakeError") or {}).get("error")
            print(f"❌ [PROTOCOL] messageProtocolHandshakeError empfangen: error={err}")
            return False

        # === PHASE 4: PIN RESPONSE (Optional - manche Geräte bestätigen, manche nicht) ===
        elif "connectionPinState" in msg and state == "WAITING_PIN":
            pin_state = (msg.get("connectionPinState") or {}).get("pinState")
            print(f"✅ [PIN] PIN-State bestätigt: {pin_state}")
            if pin_state != "none":
                print("❌ [PIN] Gerät verlangt PIN (oder sendet unerwarteten Zustand). ship-go unterstützt nur 'none'.")
                return False

            pin_state_received = True

            # === PHASE 5: ACCESS METHODS ===
            print("📤 [ACCESS] Sende accessMethodsRequest...")
            await send_ship_json(ws, {"accessMethodsRequest": {}})
            state = "WAITING_ACCESS"

        # In ship-go ist PIN eine eigene Phase; ohne PIN-State nicht zur Access-Phase springen.

        # === PHASE 5: ACCESS RESPONSE ===
        elif "accessMethodsRequest" in msg and state == "WAITING_ACCESS":
            print("📥 [ACCESS] accessMethodsRequest vom Gerät empfangen → sende accessMethods...")
            await send_access_methods(ws, local_ship_id)
            # Stay in WAITING_ACCESS until we receive accessMethods

        elif "accessMethods" in msg and state == "WAITING_ACCESS":
            remote_id = (msg.get("accessMethods") or {}).get("id", "unknown")
            print(f"✅ [ACCESS] Access Methods empfangen (Remote ID: {remote_id})")
            print("")
            print("=" * 60)
            print("💎 SHIP HANDSHAKE ERFOLGREICH BEENDET!")
            print("=" * 60)
            print("")
            return True

        elif (
            state == "WAITING_ACCESS"
            and "connectionPinState" not in msg
            and "accessMethods" not in msg
            and "accessMethodsRequest" not in msg
        ):
            # Falls wir im ACCESS-State sind, aber die falsche Nachricht kommt
            print(f"⚠️  [STATE: {state}] Unerwartete Nachricht: {list(msg.keys())}")
