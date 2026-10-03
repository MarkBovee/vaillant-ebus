---
name: ebusd-expert
description: Expert-level Vaillant eBUS/ebusd skill for reverse engineering undocumented registers, crafting define commands, and deep TCP-level debugging. Use when hunting hidden parameters, interpreting raw bus data, or extending register coverage beyond CSV definitions.
license: MIT
metadata:
  author: Mark Bovee
  version: "1.1"
---

## Context & Role

Specialized AI architect for Vaillant heating systems (heat pumps, ecoTEC, VRC) via ebusd TCP on port 8888. **No MQTT.** All communication is raw TCP socket.

**Project structure:**
- `custom_components/vaillant_ebus/coordinator.py` — bootstrap & poll loop
- `custom_components/vaillant_ebus/backend/tcp.py` — `EbusdTcpBackend` asyncio TCP client
- `custom_components/vaillant_ebus/backend/mapping.py` — `REGISTER_MAP` fallback metadata
- `custom_components/vaillant_ebus/backend/entity_factory.py` — HA entity generation from discovered registers

When communicating ebusd findings in GitHub issues or discussions, use clear English and clean
Markdown. Write complete sentences with correct punctuation, separate paragraphs with blank lines,
and put lists or distinct points on separate lines. Never post compressed or run-on prose.

---

## 1. TCP Protocol

- **Host:Port**: `[EBUSD_HOST]:8888`
- **Terminator**: `\n` (newline) on every command
- **Commands**: `read -c <circuit> <name> [field]`, `write -c <circuit> <name> <value>`, `f` (find all)
- **Status suffix**: ebusd appends `;ok`, `;err`, etc. Strip via `_strip_suffix()` in `tcp.py:27`
- **Responses**: `done` on successful write; `ERR:*` on failure; value string on read
- **Timeout**: `READ_TIMEOUT = 10s` in `tcp.py:20`
- **Serialized**: global `asyncio.Lock` in `async_send_raw()` — one command at a time

---

## 2. Define Command Format (Bootstrap)

**DO NOT modify CSV files** — see AGENTS.md "CRITICAL: Never touch ebusd addon CSV files".

Use `define -r` to inject runtime registers. Format:

```
define -r "<type>,<circuit>,<name>,<name>,<master_addr>,<slave_addr>,<message_id>,<field_id>,<field_defs>"
```

**Example** (working, from `coordinator.py:_define_custom_registers()`):
```
define -r "r5,ctlv2,z1RoomHumidity,z1RoomHumidity,31,15,B524,020003002800,value,,IGN:4,,,,value,,EXP,,%,z1 Room Humidity"
```

**Field definition format**: `<name>,,<datatype>,,<unit>,<label>` or `<name>,,IGN:<bytes>` for padding.

**Datatypes for Vaillant:**
| Datatype | Meaning |
|----------|---------|
| `EXP` | Exponential (e.g. humidity sensor, nonlinear) |
| `temp` | Temperature (2 bytes signed /16) |
| `press` | Pressure |
| `percent` | Modulation/pump 0-100% |
| `uch` / `sch` | 1-byte unsigned/signed int |
| `IGN:N` | Skip N bytes of padding |
| `hex` | Raw bytes (fallback for unknown struct) |

**Vaillant message IDs seen:**
- `B524` — CTLV2 (room controller)
- `B509` — common heat pump messages
- `B510` — HC/zone commands

---

## 3. Register Discovery

**Preferred: `find` command** sends `f` over TCP, returns all known registers. Handled by `EbusdTcpBackend.async_find()` in `tcp.py:165`.

**Fallback: `REGISTER_MAP`** in `mapping.py`. Registers with metadata here are always created as entities, even if `find` missed them. `_fallback_read()` in `coordinator.py` reads them directly.

**Hex scanning** (only when hardware register is completely undocumented):

```python
cmd = f"hex {master:02x} {cmd_hi:02x} {cmd_lo:02x} {subcmd_hi:02x} {subcmd_lo:02x} {reg:02x}"
```

Example — scan `B509` subcmd `030D` range:
```python
for reg in range(0x00, 0x100):
    resp = await backend.async_send_raw(f"hex 08 B5 09 03 0D {reg:02x}")
```

Response `ERR:` → no register at that address. Valid bytes → potential discovery.

**Never hex-scan without purpose** — floods the eBUS network. Each `hex` command is a direct bus transaction. Use targeted ranges.

---

## 4. Register Names & Entity Mapping

**Key circuit prefixes:**
- `hmu` — Heat pump main unit
- `ctlv2` — Room controller (CTLV2)
- `dhw` / `Hwc*` — Domestic hot water
- `hc1`/`hc2`/`hc3` — Heating circuits
- `z1`/`z2`/`z3` — Zones
- `Broadcast` — Shared broadcast registers
- `vwz` — Passive cooling (hidden when no data, see `entity_factory.py:43`)

**Hidden registers** (see `entity_factory.py:_is_hidden_register()`):
- `general` circuit — always hidden
- `hc2`/`hc3`/`z2`/`z3` — hidden when no data (single-zone assumption)
- Broadcast: `id`, `idanswer`, `load`, `signoflife`
- `installer*`, `phonenumber`, `keycode`, etc.
- Empty registers (`-`, `no data stored`) → `enabled_by_default=False`

---

## 5. Testing Writes

**Always test writes directly via TCP** before modifying integration code (AGENTS.md "CRITICAL: Test writes on ebusd TCP"):

```python
async def test_write(circuit, name, value):
    r, w = await asyncio.open_connection(HOST, PORT)
    w.write(f"write -c {circuit} {name} {value}\n".encode())
    await w.drain()
    resp = (await asyncio.wait_for(r.readline(), 5)).decode().strip()
    # Verify: new connection, read back
    r2, w2 = await asyncio.open_connection(HOST, PORT)
    w2.write(f"read -c {circuit} {name}\n".encode())
    await w2.drain()
    val = (await asyncio.wait_for(r2.readline(), 5)).decode().strip()
    return resp, val
```

Each command gets its own TCP connection. Write returns `done` on success.

**Also test via HTTP** (ebusd port 8889):
```bash
curl -s "http://<HOST>:8889/read?circuit=ctlv2&name=HwcOpMode"
```

---

## 6. Volatility & Bootstrap

Runtime `define` commands are **volatile** — lost on ebusd restart. The integration re-injects them on every startup via `coordinator.py:_define_custom_registers()`.

If adding a new custom register, add its `define -r` string to the `defines` list at `coordinator.py:186`.

For persistent registers, the user must add CSV files to the ebusd addon via HA addon UI (see AGENTS.md: never do this yourself).

---

## 7. Undocumented Register Discovery Workflow

1. **Check `find`** — `f` command covers most registers, including multi-field
2. **Check existing `REGISTER_MAP`** — known register already mapped?
3. **Check if compressor must be running** — many heat pump registers show "no data stored" when idle (summer)
4. **Check message type** — identify via ebusd `scan` results or existing `define` patterns
5. **Hex probe targeted range** — only if convinced register is hidden and important
6. **Convert to `define -r`** — translate discovered hex field layout into proper field definitions
7. **Add to `_define_custom_registers()`** — bootstrap on every connect
8. **Optionally add to `REGISTER_MAP`** — for friendly name, icon, unit, enabled-by-default

---

## 8. Important Constraints

- **Never touch ebusd CSV files** on the addon — violation corrupts the user's setup
- **Never set `--configpath`** — breaks addon's default CSV loading
- `.env` credentials — never commit or log
- TCP port 8888 is plaintext — trusted network only
- `coordinator.py:_define_custom_registers()` must be preserved — removing it breaks room humidity until HA restart
- `coordinator.py:_fallback_read()` triggers entity regeneration — refactoring must preserve this
- `backend/tcp.py:async_send_raw()` is public — used by `_define_custom_registers()` for raw commands
