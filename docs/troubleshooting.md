# Troubleshooting

## Integration won't connect

Verify ebusd is running and TCP port 8888 is open:

```bash
echo 'i' | nc <ebusd-host> 8888
# Expected: "version: ebusd 26.x.x.x"
```

If that fails:

- Check ebusd addon is started in **Settings → Add-ons → ebusd**
- Verify `--port=8888` is in `commandline_options`
- Ensure no firewall blocks port 8888 on the HA server
- For addon-only setups (ebusd on same host), use `127.0.0.1` as the host

## Entities show "unavailable"

The coordinator lost connection to ebusd. Auto-reconnect retries with backoff (1s–60s).

If it persists:

- Restart the ebusd addon
- Check the eBUS adapter (network cable, power to the adapter)
- Verify ebusd logs for errors: **Settings → Add-ons → ebusd → Logs**

## All heat pump registers show "unavailable" or "no data stored"

This is normal when the compressor is idle — summer mode, no heating or DHW demand. Registers that depend on the compressor (energy counters, flow temperatures, COP) only return data during active cycles.

They become available automatically when the heat pump starts a heating, DHW, or cooling cycle.

## A register is "ERR: element not found"

The register exists in the CSV definition files but is not supported by your specific hardware. Different firmware versions support different register sets. This is expected — the integration won't create an entity for registers that error.

## Entity type is wrong (sensor vs binary_sensor vs number)

The integration auto-classifies registers based on their value format:

- Numeric values ≥ 0 → `sensor`
- "0" or "1" → `binary_sensor` (heuristic — sometimes wrong)
- Discrete options → `select`
- Known writable registers → `number`

If the classification is wrong, override it in `config/vaillant_ebus/entities.yaml`:

```yaml
hmu.SomeCounter:
  entity_type: "sensor"
```

Then reload the integration: **Settings → Devices & Services → Vaillant eBUS → Reload**.

## Duplicate entities after reconnect

If the integration is reloaded while registers are idle (value "0"), a new entity may be created with a different type than the original. After restarting HA the duplicates are cleaned up.

To clean manually:

1. Go to **Settings → Devices & Services → Entities**
2. Enable "Show disabled entities"
3. Remove the duplicate entries
4. Restart HA

## Register write fails

- Verify `--accesslevel=*` is set in ebusd commandline_options
- Some registers are read-only by hardware design (eBUS spec limitation)
- The integration returns a clear error message with the ebusd response

## HMUX0 heat pump variants (aroTHERM VWL 55/8.2 etc.)

Some aroTHERM heat pumps scan as `HMUX0` (e.g. `MF=Vaillant;ID=HMUX0;SW=0303;HW=0504`).
For `HMUX0;SW=0303;HW=0504`, version 1.8.0-rc2 recognizes the scan even when ebusd has no matching CSV and defines the community-evidenced, fixture-backed telemetry registers: `RunDataReturnTemp`, heating/DHW `Yield*`, heating/DHW `Cop*`, and the shared b516 heating/DHW/cooling electrical-consumption statistics. No `08.hmux0.csv -> 08.hmu.csv` symlink is needed for this supported set.

Remove the old symlink before restarting the ebusd addon. Then restart Home Assistant or reload the integration so it rediscovers the heat pump. Do not copy the generic `08.hmu.csv`: several of its register layouts return `(ERR: invalid position ...)` on HMUX0 HW0504 and are intentionally not enabled by the integration.

This does not provide the complete generic HMU register catalog. Additional HMUX0 registers need their own hardware-specific layout evidence before they can be added safely.

## Domestic Hot Water shows "unknown"

On a `HMUX0` + `CTLV3` installation the DHW registers live on the `ctlv3` controller while the heat-pump telemetry lives on `hmux0`. Older releases could resolve the controller to a leftover `ctlv2` probe circuit, so the water-heater entity read no value and showed "unknown" even though `ctlv3.HwcOpMode` was valid.

v1.8.0-rc2 makes controller resolution prefer the circuit that actually owns the control/DHW registers. After upgrading, the `Domestic Hot Water` entity reads its state, temperature, target, and away values from `ctlv3`. The away/holiday date fields use `01.01.2015` and `01.01.2019` as unset markers; these now show as "not away" instead of "unknown", consistent with the DHW away switch.


## Need more help

Enable debug logging in `config/configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.vaillant_ebus: debug
```

Check the logs at **Settings → System → Logs** and look for `custom_components.vaillant_ebus` entries.
