# Reference: dump-structuur & Vaillant eBUS patterns

Deze tafel is opgebouwd uit evidence-backed analyse van community dumps (issues #99/#102/#109/#111 en de GOLDEN fixtures). Item-bronnen: dump-secties en `custom_components/vaillant_ebus/coordinator.py` (`_define_custom_registers`).

## Discovery dump (v4) structuur

| sectie | inhoud |
|---|---|
| `metadata` | timestamp, ebusd_version, register_count, grab_duration, dump_version=4, integration_version, ebusd_info, ebusd_configuration (addon-opties meestal `available: false`) |
| `raw_find_lines` | ruwe `find` output (`circuit Name = value`), incl. `no data stored` / `(ERR: ...)` |
| `raw_find_lines_after` | effective state na de runtime `define` pass (optioneel) — gebruik `after=True` voor effectieve runtime-tests |
| `before_registers` / `after_registers` | genormaliseerd: circuit, name, value, writable, has_data, from_map, disabled; alle ontdekte + fallback-probes |
| `grab` | ruwe bus-telegram lijnen (`... / 09410111... = 3`) |
| `unknown_telegrams` / `labeled_telegrams` | door `backend/grab_parser.py` afgeleide traffic: master, slave, message, sub, bytes, count |

Sentinels (unavailable, niet als normale waarde): `no data stored`, `(empty ...)`, `(ERR: element not found)`, `(ERR: invalid position ...)`, `-`, en NaN payloads zoals `0x7fffffff`.

## B524 / ctlv* register-adressering

B524 is het CTLV2/CTLV3-controller-message. Sub-address pattern: read `0602 00 <zone> <reg> 00`, write `0702 01 <zone> <reg> 00`. Bekende reg-ids:

| reg-id | register | opmerking |
|---|---|---|
| `0004` | HwcTempDesired | |
| `0005` | HwcStorageTemp | tempv, 2-byte; NaN-sentinel bij geen tank (boiler-detectie, strong assumption) |
| `0009` / `000a` | HwcHolidayStartPeriod / HwcHolidayEndPeriod | HDA:3 datum; reset 01.01.2015/01.01.2019 |
| `000d` | HwcSFMode | myVaillant "Hwc Load" backend (upstream #568) |
| `000f` | HwcStatus (zonestatus2) | auto=0, load=9, off=10 |
| `00da`/`00db` | ManualCoolingStartDate / ManualCoolingEndDate | runtime define, HDA:3 |
| `0028` (z1) | z1RoomHumidity | `IGN:4 ... EXP` |
| `0020..0025` | Hc1/Hc2 FlowTempCalc..PumpStarts | EXP/ULG, runtime define |

Runtime define formaat: `r5,ctlv2,<naam>,<label>,31,15,B524,<read-sub>,value,,IGN:4,,,,value,,<type>,` en een losse `w,ctlv2,<naam>,...,0201<...>,value,m,HDA:3` voor writes.

## Message-write conventies

- **B509 (BAI/boiler)**: read request prefix `0d`, write prefix `0e`. `0dF203`/`0dF303` lezen, `0eF203`/`0eF303` schrijven. Dit is de upstream product-specific include-conventie.
- **`onoff` veldtype is NIET beschikbaar in runtime define scope** (template zit in `vaillant/_templates.csv`, niet in de globale scope). Gebruik `UCH,0=off;1=on`.
- **B510 SetMode**: semicolon-velden; `releaseCooling` is **index 9** (0-based na `hcmode;flowtempdesired;...`). `find -v` toont write-only registers niet — gebruik `find -w` of de define zelf.
- **Write-verificatie**: ebusd `read` antwoordt uit cache die de write zelf vult → een cached read-back "verifeert" altijd. Forced `read -f` (en een retry) is de enige echte controle.

## Statusfields (B511)

| circuit-veld | layout | waarden |
|---|---|---|
| `Status01.pumpstate` | veld 6 | `0=off 1=on 2=overrun 4=hwc` → **DHW-actief signaal** op units zonder Status00/07 |
| `Status00` | multi-field | supplytemp, waterpressure, compressormodulation, compressorstate, heatingstate, field6, defrost, compressorpower |
| `Status07` | heatermain bits | `b3_heating`, `b4_cooling`, `b7_warmwater` (en `display_b5_noisereduction` op HW5103) |

Energy Manager State afleiding: `RunDataStatuscode` → anders `Status00`/`Status07` bits → anders `SetMode.releaseCooling` (Cooling) / `Status01.pumpstate==hwc` (DHW). Expliciete shutdown/standby/compressor-off wint altijd.

## Circuit-resolutie

- `15.ctlv3.tsp` is een **symlink naar `15.ctlv2.tsp`** (upstream PR #266): ebusd kan dezelfde controller als `ctlv2` of `ctlv3` benoemen. Gebruik de SCAN-identiteit (`scan.15` regel in metadata/raw) en de graph-owner-resolutie (`resolve_register_circuit`), nooit de circuitnaam als waarheid.
- Een exact node (bv. bare `ctlv2`) is alleen autoritatief als die de owner van de control/DHW registers is. Logische sub-devices (dhw-node) aggregeren registers van meerdere source-circuits — resolve owner per register via de source-circuit.
- Dubbele find-lijnen (één live, één `no data stored`) = duplicate elementen in de geladen CSV; check welke element een write resolveert (`ebusctl elements`).

## Runtime define rules

- Definities zijn vluchtig: re-inject op elke connect in `_define_custom_registers()`; alleen gewijzigde/gefailleerde worden herverzonden.
- Additief: absent/`ERR` → register blijft unavailable zonder normale entiteit; geen actieve polling die busgedrag verandert.
- Community-data → fixture-backed test (decoded value én absent-pad); classificatie confirmed / strong assumption / speculative / discovery-only in de analyse-notitie.

## Handige B509/B511/B51A/B516 definities (uit coordinator, evidence-backed)

- HMUX0 `Status00`: `r,hmu,Status00,...,31,8,B511,00,<velden incl. compressorstate UCH 0=off;4=heating;24=hot_water;110=defrosting,...>`
- HMUX0 `RunDataElPowerConsumption`: `r,hmu,...,31,8,B509,055402005b0d,value,,IGN:4,,,,value,,EXP,,W,` (upstream #522)
- `SourceTempInput`: `r,hmu,...,31,8,B51A,05ff3222,value,,IGN:3,,,,value,,D2C,,°C,` (upstream PR #565; air/water geeft 3-byte stub → unavailable)
- B516 cooling-energie: `CoolEnvYieldTotal` `1000ffff02050000`, `CoolElecConsTotal` `1000ffff03050000`, en day/month varianten met `b516_date_bytes` (upstream #490/#600)

## Data-dump vs losse commando's

Voor "werkt een write niet?" / "welk telegram accepteert de controller?" is de **export_discovery_dump met een grab** de makkelijkste, sterkste stap: de passieve grab vangt báse de write-telegram (integratie én app), en `before/after_registers` tonen de read-back. Vraag de gebruiker: draai `export_discovery_dump` met `grab_duration: 30` en doe de actie (HA-write óf app-write) terwijl de grab draait; beide dumps vergelijken → write-vs-app transacties.