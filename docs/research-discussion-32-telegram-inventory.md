# Discussion #32 — Relevant Unknown Telegram Inventory

Source: community attachment `Discovery.dump.for.vaillant_ebus.txt`, received
2026-09-22. The complete raw dump is not edited or trimmed. This appendix
records the unknown telegrams relevant to the requested CTLV3, HMUX0, and VWZIO
functionality. The complete 68-row machine-readable inventory remains in the
local research scratch area during this research session.

Hardware scope from dump metadata:

- `08`: `Vaillant;HMUX0;SW0302;HW0504`
- `15`: `Vaillant;CTLV3;SW0808;HW8004`
- `76`: `Vaillant;VWZIO;SW0302;HW0504`

Response lengths below count the complete hex response, including ebusd's
leading length byte. The response bytes are copied exactly from the dump.

| Classification | Master | Slave | Message | Sub-address | Request | Response | Raw bytes | Count |
|---|---:|---:|---|---|---|---|---:|---:|
| discovery-only status context | `10` | `08` | `B511` | `0100` | `1008b5110100` | `0976020f000000000000` | 10 | 21 |
| discovery-only status context | `10` | `08` | `B511` | `0101` | `1008b5110101` | `094e537e13ff680000ff` | 10 | 127 |
| discovery-only status context | `f1` | `08` | `B511` | `0100` | `f108b5110100` | `0976020f000000000000` | 10 | 5 |
| discovery-only status context | `f1` | `08` | `B511` | `0101` | `f108b5110101` | `094e537e13ff680000ff` | 10 | 29 |
| strong assumption, exact B509 family; target scope still gated | `f1` | `08` | `B509` | `05540200030b` | `f108b50905540200030b` | `060201030b4801` | 7 | 2 |
| discovery-only | `f1` | `08` | `B509` | `05540200040a` | `f108b50905540200040a` | `050201040a00` | 6 | 1 |
| discovery-only | `f1` | `08` | `B509` | `055402000d0a` | `f108b509055402000d0a` | `0802010d0a00000000` | 9 | 2 |
| discovery-only | `f1` | `08` | `B509` | `05540200190a` | `f108b50905540200190a` | `050201190a00` | 6 | 1 |
| discovery-only | `f1` | `08` | `B509` | `055402004e0d` | `f108b509055402004e0d` | `0502014e0d00` | 6 | 1 |
| strong assumption, B509 electrical power; exact SW0302 semantics need fixture proof | `f1` | `08` | `B509` | `055402005b0d` | `f108b509055402005b0d` | `0802015b0d00001041` | 9 | 20 |
| discovery-only | `f1` | `08` | `B509` | `05540200600b` | `f108b50905540200600b` | `050201600b1d` | 6 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200610b` | `f108b50905540200610b` | `050201610b1d` | 6 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200620b` | `f108b50905540200620b` | `050201620b1d` | 6 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200650b` | `f108b50905540200650b` | `050201650b00` | 6 | 1 |
| discovery-only | `f1` | `08` | `B509` | `055402008813` | `f108b509055402008813` | `0e020188136400ffffffffffffffff` | 15 | 2 |
| discovery-only | `f1` | `08` | `B509` | `055402008b13` | `f108b509055402008b13` | `0e02018b13ffffffffffffffffffff` | 15 | 2 |
| strong assumption, building-pump family | `f1` | `08` | `B509` | `05540200c509` | `f108b50905540200c509` | `080201c50900000000` | 9 | 2 |
| discovery-only | `f1` | `08` | `B509` | `05540200cc10` | `f108b50905540200cc10` | `060201cc10a702` | 7 | 2 |
| discovery-only | `f1` | `08` | `B509` | `05540200d110` | `f108b50905540200d110` | `060201d1103401` | 7 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200d610` | `f108b50905540200d610` | `060201d6100000` | 7 | 1 |
| strong assumption, fan-hours family; target layout still fixture-gated | `f1` | `08` | `B509` | `05540200d70b` | `f108b50905540200d70b` | `080201d70b300f0000` | 9 | 2 |
| strong assumption, fan-starts family; target layout still fixture-gated | `f1` | `08` | `B509` | `05540200d80b` | `f108b50905540200d80b` | `080201d80b840a0000` | 9 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200e10b` | `f108b50905540200e10b` | `080201e10b00000000` | 9 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200e20b` | `f108b50905540200e20b` | `080201e20b00000000` | 9 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200e30b` | `f108b50905540200e30b` | `080201e30b81000000` | 9 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200e40b` | `f108b50905540200e40b` | `080201e40b44020000` | 9 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200e50b` | `f108b50905540200e50b` | `080201e50b9b170000` | 9 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200e60b` | `f108b50905540200e60b` | `080201e60b8c010000` | 9 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200fa0a` | `f108b50905540200fa0a` | `050201fa0a1d` | 6 | 1 |
| discovery-only | `f1` | `08` | `B509` | `05540200fd0a` | `f108b50905540200fd0a` | `060201fd0a8202` | 7 | 2 |
| discovery-only, B516 semantics vary by circuit and hardware | `f1` | `08` | `B516` | `0114` | `f108b5160114` | `09000000004100000000` | 10 | 21 |
| discovery-only, VWZIO target is HW0504 rather than upstream HW5103 scope | `f1` | `76` | `B516` | `0114` | `f176b5160114` | `09000000a04000000000` | 10 | 20 |
| discovery-only, VWZIO status family | `10` | `76` | `B512` | `030f0001` | `1076b512030f0001` | `07460300f6010fff` | 8 | 128 |
| discovery-only | `10` | `08` | `B512` | `020000` | `1008b512020000` | `00` | 1 | 4 |
| discovery-only | `10` | `08` | `B512` | `0204ff` | `1008b5120204ff` | `00` | 1 | 4 |
| discovery-only | `10` | `08` | `B513` | `020528` | `1008b513020528` | `0101` | 2 | 4 |
| discovery-only | `10` | `08` | `B507` | `020900` | `1008b507020900` | `02dc06` | 3 | 21 |
| discovery-only | `f1` | `08` | `B51A` | `0405000c00` | `f108b51a0405000c00` | `020001` | 3 | 1 |
| discovery-only | `f1` | `08` | `B51A` | `0405000c4d` | `f108b51a0405000c4d` | `020001` | 3 | 1 |
| discovery-only | `f1` | `08` | `B51A` | `0405000c50` | `f108b51a0405000c50` | `020001` | 3 | 1 |
| discovery-only | `f1` | `08` | `B51A` | `0405000c51` | `f108b51a0405000c51` | `020001` | 3 | 1 |
| discovery-only | `f1` | `08` | `B51A` | `0405000c52` | `f108b51a0405000c52` | `020001` | 3 | 1 |
| discovery-only | `f1` | `08` | `B51A` | `0405000c53` | `f108b51a0405000c53` | `020001` | 3 | 1 |
| discovery-only | `f1` | `08` | `B51A` | `0405000c54` | `f108b51a0405000c54` | `020001` | 3 | 1 |
| discovery-only | `f1` | `08` | `B51A` | `0405000ca1` | `f108b51a0405000ca1` | `020001` | 3 | 1 |
| discovery-only, not a yield request | `f1` | `08` | `B51A` | `0405ff3546` | `f108b51a0405ff3546` | `0aff083e34010000000000` | 11 | 1 |
| discovery-only, CTLV3 controller energy context | `f1` | `15` | `B516` | `081000ffff01000000` | `f115b516081000ffff01000000` | `0b0000ff0100363500000000` | 12 | 1 |
| discovery-only, CTLV3 B524 register context | `f1` | `15` | `B524` | `06020000004800` | `f115b52406020000004800` | `06010048000000` | 7 | 43 |
| discovery-only, CTLV3 B524 register context | `f1` | `15` | `B524` | `06020001000f00` | `f115b52406020001000f00` | `0601010f000000` | 7 | 75 |
| discovery-only, CTLV3 B524 register context | `f1` | `15` | `B524` | `06020003001b00` | `f115b52406020003001b00` | `0601031b000000` | 7 | 79 |
| discovery-only, other HMUX0 history/status | `f1` | `08` | `B503` | `020001` | `f108b503020001` | `0affffffffffffffffffff` | 11 | 20 |
| discovery-only, other HMUX0 history/status | `f1` | `08` | `B503` | `020002` | `f108b503020002` | `0affffffffffffffffffff` | 11 | 20 |
| discovery-only, other HMUX0 history/status | `f1` | `08` | `B503` | `020003` | `f108b503020003` | `0a6400ffffffffffffffff` | 11 | 8 |
| discovery-only, other HMUX0 history/status | `f1` | `08` | `B503` | `020004` | `f108b503020004` | `0affffffffffffffffffff` | 11 | 20 |
| discovery-only, other HMUX0 history/status | `f1` | `08` | `B503` | `020005` | `f108b503020005` | `0affffffffffffffffffff` | 11 | 20 |
| discovery-only, VWZIO history/status | `f1` | `76` | `B503` | `020001` | `f176b503020001` | `0affffffffffffffffffff` | 11 | 20 |
| discovery-only, VWZIO diagnostic | `f1` | `76` | `B509` | `05540200040a` | `f176b50905540200040a` | `050201040a00` | 6 | 1 |
| discovery-only, VWZIO diagnostic | `f1` | `76` | `B509` | `05540200640b` | `f176b50905540200640b` | `060201640b1400` | 7 | 1 |
| discovery-only, VWZIO diagnostic | `f1` | `76` | `B509` | `05540200cc10` | `f176b50905540200cc10` | `060201cc10a702` | 7 | 2 |

The three `fe` broadcast candidates (`B505/025c00`, `B508/020900`, and
`B510/020601`) are excluded from implementation candidates because broadcast
messages are not normal register entities. The `15:B503` and `15:B531` rows
are likewise retained in the raw dump but are outside the requested feature
families. No row is production-ready solely because it appears in this table.
