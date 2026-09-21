# Release 1.9.2 — Plan

Status: **DRAFT** (voor plan-check)
Branch: `release/1.9.2`
Datum: 2026-09-21

## Risicoklasse: Significant

Release-gevoelig project. Elke wijziging is additief/opt-in, gegated op
gediscoverde apparatuur, en dekt een veilig absent-pad. Geen brede refactors.

## Must / Should / Could

### Must

- **#31-BUG: `config/vaillant_ebus/entities.yaml` overrides worden niet geladen.**
  - Bewijs: `docs/setup.md:32`, `README.md:196`, `docs/troubleshooting.md:48` beloven
    het bestand. `entity_factory.py` kent `yaml_overrides` (genereer + `_redistribute...`),
    maar `coordinator.py:380/480/1279` roept `generate(graph)` aan zonder overrides,
    en nergens in `custom_components/` wordt het bestand gelezen of geladen.
  - Fix: laad `config/vaillant_ebus/entities.yaml` (bestaand pad, `hass.config.path(DOMAIN)`
    zoals `register_cache.json` op regel 997), parse veilig, en geef het dict door aan
    `entity_factory.generate(graph, yaml_overrides=...)` op de drie aanroepsites.
  - Acceptatie: fixtures/unit-test dat een override (`friendly_name`/`unit`/`icon`,
    `device_circuit`) wordt toegepast; absent-bestand-path blijft werken (leeg dict,
    geen crash); bestand met ongeldige YAML geeft veilige fout + melding, geen productiecrash.
  - Bron: discussion #31, bericht Rijo038 (2026-09-21).
  - Status: **geïmplementeerd** (commit `cf6bc5a`). `_async_load_yaml_overrides()`
    + doorgeven aan alle drie `generate()`-aanroepen; regressietests voor geldig,
    absent en ongeldig YAML.

### Should

- **#141: `hmu.*ElecConsDay` zijn kWh maar gedeclareerd Wh (1000x); `HcElecConsTotal` inconsistent.**
  - Bewijs: issue #141 (jlrosende) met raw `read -f` waarden; eigenaar heeft 09-18
    toegezegd de fix op te nemen. Eigenaar stelt 09-19 voor unitwijziging op te houden
    tot een huidige dump met grab + raw reads de upstream schaling bevestigt (geen
    dekfout op andere HMU/HMUX0 captures).
  - **Nieuwe fixture-analyse (2026-09-21):** de community-fixtures bevestigen dat de
   zelfde register-mapping per installatie een andere schaal decodeert. Samengevat
    (HcElecConsDay / HwcElecConsDay, beide gedeclareerd Wh):
    - flexotherm: 270 / 3159
    - aroTHERM Pro 7: 122 / 0
    - aroTHERM hmux0: 133 / 996
    - ecoTEC/VRT380: 55 / 24.9
    - jlrosende (#141): **1.12 / 0.97** — ~100× kleiner dan alle andere
    Alle community-waarden zitten in dezelfde Wh-orde; alleen jlrosende's installatie
    rapporteert ~100× kleiner (kWh-schaal). Er is **geen universeel correcte unit**:
    een blanket `Day → kWh` zet jlrosende' correct maar maakt álle andere installaties
    1000× fout, en het tegengestelde is even waar.
  - Blokkering: **jlrosende's specifieke dump + `ebusctl info`/`find -v`/`read -f`
    output is onmisbaar, niet alleen wenselijk** — zonder die capture is elke
    schalingsfix op een andere installatie gegarandeerd onjuist. De schaal wordt door
    de lokale ebusd-CSV-config bepaald (EbusService geeft ruwe ebusd-waarden door,
    geen transport-decoding).
  - Acceptatie: zodra jlrosende's capture binnen is en de lokale ebusd
    definitie de deler toont, een hardware/installatie-gebonden fix (of decode-subset)
    met fixture-regressie. **Geen blanket unit-wijziging in v1.9.2** zonder die capture.
  - Status: **geblokkeerd op jlrosende's dump**; plan bewaart de write-up van wat er
    ontbreekt, geen gok.

### Could

- **#152: optimaliseer default entity enablement voor optionele/zeldzame registers.**
  - Bewijs: issue #152 (eigen) + discussion #148. Er zijn expliciete `RegisterMeta.enabled`
    en `enabled_by_default`; een regressie is dat een no-data pass een door de gebruiker
    ingeschakelde entity niet mag terugdraaien.
  - Scope: beperk tot de registry-overgang (user-enabled mag niet worden gedisabled door
    een latere no-data pass); geen polling-wijzigingen, geen brede heuristiek.
  - Acceptatie: test dat een user-enabled entry stabiel overleeft over no-data polls en
    rediscovery, terwijl integratie-gedisablede entries herstelbaar blijven bij een
    geldige waarde.
  - Kans op schaal: medium — vraagt geduldige expressie van "user-enabled" vs
    "integration-disabled" in de registry.
  - Status: **geïmplementeerd** (commit `c4d4c37`). De no-data pass disabled alleen
    default-enabled entities zonder data en respecteert non-default enabled entries
    (gebruikerskeuze) + user-disabled entries. Regressietest
    `test_disable_no_data_preserves_user_enabled_optional_entities` pin-eert dit;
    mutant-check bevestigde dat de test faalt op de oude logica.

## Out of scope (expliciet)

- **#101 Quiet mode aroTHERM Pro (HMUX0 SW0406/HW0504):** blijft **discovery-only**.
  Geen veilige B508/0209-layout zonder een capture die beide richtingen in één sessie
  en een `grab result all` met volgorde bewijst. Geen hardware-specifieke gok.
  → blokkerend op community-evidence.
- **#102 Energy Manager heating-state:** DHW is bevestigd (`Status01.pumpstate=hwc`);
  heating-verificatie wacht op een capture rond standby→heating zodra het
  verwarmingsseizoen begint. Geen actie nu, alleen state bijhouden.

## Validatie-eisen

- Gemeenschappelijk: haal de betreffende community-fixtures op onder
  `tests/fixtures/community/` waar de code op gebaseerd wordt, met
  provenance-metadata + `raw_find_lines`.
- `#31-BUG`: unit-test op de YAML-loader (geldig bestand, ongeldig bestand, absent
  bestand) + integratie-test dat overrides de entity-descriptions beïnvloeden.
  → **gedaan** (`cf6bc5a`): 3 coordinato-tests, 670 pytest groen.
- `#141`: vereist jlrosende's dump; nul-code gedeeld in v1.9.2 ivm gegarandeerde
  dekfout. Niet van toepassing tot de capture binnen is.
- `#152`: regressie user-enabled vs integration-disabled over meerdere no-data passes.
  → **gedaan** (`c4d4c37`): `test_disable_no_data_preserves_user_enabled_optional_entities` +
  mutant-check, 670 pytest groen.
- CI-gates: `.venv/bin/ruff check .`, scoped `ruff format --check`,
  `python3 tools/version.py check` (1.9.2), `python3 -m compileall -f`, `.venv/bin/pytest -q`.
- Home Assistant: na merge/release live deployen en entity-behavior verifiëren vóór
  de branch als definitief te markeren.

## Release-gate

- `tools/version.py bump` + `## 1.9.2 - <datum>` heading in CHANGELOG.md met
  mens-geschreven release notes per issue.
- Onafhankelijke review + audit-subagent over `#31-BUG` en `#152` registry-overgang
  vóór merge/tag; nooit self-review-only groen verklaren.
- `#141` wordt niét in v1.9.2 meegenomen zolang jlrosende's dump ontbreekt; dit wordt
  apart gelogd als blokkering, niet verborgen.