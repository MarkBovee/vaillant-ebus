# Plan: first-time setup UX improvement

## Scope

Non-breaking additions to existing stable codebase. Focus on onboarding flow for new users — everything else untouched.

## Files

| File | Change |
|------|--------|
| `custom_components/vaillant_ebus/const.py` | Discovery candidates, empty default host |
| `custom_components/vaillant_ebus/config_flow.py` | Auto-discovery step before manual form, better `i` response validation |
| `custom_components/vaillant_ebus/translations/en.json` | New errors: `no_bus_signal`, `no_vaillant_device` |
| `custom_components/vaillant_ebus/strings.json` | Same new errors |
| `custom_components/vaillant_ebus/coordinator.py` | Startup logging: version, circuits, step-by-step |
| `custom_components/vaillant_ebus/repairs.py` (new) | `async_create_issue` for unreachable ebusd |
| `custom_components/vaillant_ebus/__init__.py` | Register repairs module |
| `custom_components/vaillant_ebus/diagnostics.py` | Add `bus_signal`, `protocol_version`, circuit list |
| `README.md` | C6 adapter setup guide, mermaid diagram, updated install flow |

## Config flow behavior

```
User clicks "Add Integration"
  → async_step_user probeert discovery op:
      core-ebusd:8888 (Docker hostname, beide addons)
      localhost:8888     (standalone HA + ebusd zelfde host)
      homeassistant.local:8888 (addon op host network)
  → Bij success op een endpoint:
      Stuur "i" command, parse response
      Check "signal acquired" in output
      Check "Vaillant" in output
      OK? async_create_entry — klaar
      Fail? toon specifieke error, val terug op manual form
  → Alle candidates falen?
      Toon manual form (host/port) ongewijzigd
```

## Error messages

- `cannot_connect` — "Cannot reach ebusd at {host}:{port}"
- `no_bus_signal` — "Connected to ebusd but no eBUS signal detected"
- `no_vaillant_device` — "ebusd running but no Vaillant device found on bus"

## README additions

- C6 adapter: connect to PC via USB-C, configure WiFi, assign fixed IP
- C6 adapter: TCP enhanced mode after connecting to heat pump
- Architecture mermaid diagram: C6 → ebusd → integration
- Data flow explanation
- Updated Step 1 to match
