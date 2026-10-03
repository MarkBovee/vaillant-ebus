---
name: community-dump-analysis
description: Analyseer een discovery dump van een gebruiker/community (GitHub issue, discussion) of van de lokale HA-installatie voor register- en feature-onderzoek bij Vaillant eBUS. Gebruik bij: dumps die uit issues/discussions komen, unknown-telegram analyse, nieuw register of sensor ontwerpen uit een capture, "wat zit er in deze dump", een gebruiker die om ondersteuning vraagt met een dump. Niet gebruiken voor: losse ebusctl commando's (zie ebusd-expert), vergelijken van twee lokale dumps (zie dump-diff), of schrijven van productiecode zonder een evidence-tabel.
license: MIT
metadata:
  author: Mark Bovee
  version: "1.0"
---

# Community Dump Analysis

Vind, laad en ontleed discovery dumps om register-/feature-claims met bewijs te onderbouwen. Dit is de workflow die gebruikt werd voor de deep-research rond issues #99/#102/#109/#111.

## Rol

Je bent de analyse-spil voor Vaillant eBUS data dumps. Je verzamelt bewijs, geen conclusies zonder bewijs. Community-data van andermans hardware **kan nooit live geverifieerd worden** — de fixture is de correctheidsgate (zie AGENTS.md "Community Data").

## Workflow

### 1. Vind en download dumps

- Lee's GitHub: `gh issue view <n> --json body,comments` → attachment URLs `https://github.com/user-attachments/files/<id>/<name>` → `curl -sL -o`.
- Verzamel **alle** bijlages per issue (niet alleen de nieuwste), sorteer op timestamp/updatedAt.
- Controleer of de dump al als fixture bestaat (`tests/fixtures/community/`); hernoem dan niet dubbel.
- Lokaal aanwezig: `/config/vaillant_ebus/discovery_dump_*.yaml` (via HA, zie `home-assistant` skill).

### 2. Word een fixture

- Kopieer naar `tests/fixtures/community/<hardware>_<issue>_<timestamp>.yaml` (b.v. `hmux0_issue99_2026-09-13_173740.yaml`).
- **Knip nooit raw find lines of provenance weg** — test_fixture_integrity guardt dit. Bewaar alle `raw_find_lines` (en `raw_find_lines_after` als die er is).
- Voeg de fixture toe aan de parametrize-sweep `test_all_fixtures_load` in `tests/test_fake_ebusd.py` (min_registers realistisch per dump).
- Schrijf een fixture-backed regressietest op de discovered graph (register-waarden, owner-circuit, absent-gedrag).

### 3. Bouw de evidence-tabel

Gebruik `backend/grab_parser.py` (`parse_grab_lines`, `unknown_telegrams`, `labeled_telegrams`) op de `grab`/`unknown_telegrams`/`labeled_telegrams` secties. Voor **elke** relevante onbekende of unmapped telegram een rij:

| kolom | waarde |
|---|---|
| lokale dump(s) | filenummer + sectie |
| master / slave | adressen hex |
| message ID | b.v. `B524` |
| sub-address | b.v. `06020001000900` |
| request bytes | exact |
| response lengte + bytes | exact |
| observed state(s) | per state de payload |
| occurrence count | aantal |

Dedupliceer op `(slave, message ID, sub-address)`, behoud state-specifieke payloads en counts. Veld-entries (`Status01.temp`) zijn geen registers — strip field-suffixen en los de parent-register op.

### 4. Upstream zoeken (verplicht)

Voor elke kandidaat: `tools/search_upstream.sh --comments --all` met **meerdere** query-varianten: volledige message ID (`b511`), message+sub (`b511 0101`), request/payload fragmenten met en zonder spaties, slave/device identiteit (`HMUX0`, `HW0504`), hardware- en functietermen (`Quiet mode`, `Cooling`). Een zero-result is bewijs voor die query, nooit dat er geen mapping bestaat.

- Rate-limits: cache output, wait + retry bij HTTP 403, mindeer parallel queries, gebruik `gh issue view <n> --comments` / `gh pr view <n> --comments` voor veelbelovende threads.
- Lees veelbelovende issues/PRs **volledig** (commentaarketen) voordat je een snippet gebruikt. Noteer URL, hardware-context en classificatie.

### 5. Classificeer

- `confirmed`: naam + waarde/layout expliciet (live eigen hw, of fixture met expliciete capture)
- `strong assumption`: meerdere consistent observations / duidelijke before-after correlatie
- `speculative`: onvoldoende bewijs voor productie
- `discovery-only`: geen layout-bewijs, alleen aanwezigheid

### 6. Layout-verificatie vóór runtime define

Controleer álle vóór een `define -r` in `_define_custom_registers()`:
- master/slave + message ID + sub-address matchen het evidence-telegram.
- response byte-lengte en field-offsets kloppen; units/range plausibel.
- Hardware/firmware scope expliciet; definitie is additief en tolereert afwezig/`ERR` zonder normale entiteit te creëren.
- Prefereren passieve `u` definities; geen actieve polling die busgedrag verandert tenzij expliciet nodig en veilig.

### 7. Implementatie-route

- Voeg toe via bestaande data-driven paden: `_define_custom_registers()`, `REGISTER_MAP`, `MULTI_FIELD_MAP`, device-type tabellen. Nooit one-off register-specifieke geïsoleerde code-paden.
- Regressietest laadt de fixture en assert zowel de decoded waarde als het absent-pad van het register.
- Bij writes: zie de write-conventies in REFERENCE.md; test de write eerst direct tegen ebusd en verifieer read-back. Een "write werkt" claim vereist write-vs-app bewijs, niet alleen een `done`.

## Verwijzingen

- Lokale dump-vergelijking (2 dumps diffen): skin `dump-diff`.
- Register reverse-engineering / TCP-level: skill `ebusd-expert`.
- Dump-structuur, telegrams, geleerde patterns: zie `REFERENCE.md`.