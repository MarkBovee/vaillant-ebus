# Setup Guide

> For installation steps, see the [README](../README.md). This guide covers details and background.

## Connection verification

Check raw TCP from any machine on your network:

```bash
echo 'i' | nc <ebusd-host> 8888
# Expected: "version: ebusd 26.x.x.x"
```

If `nc` is not available, use telnet or the HA addon log.

## Expected devices

| Device | Circuit | What you get |
|--------|---------|--------------|
| Vaillant aroTHERM heat pump | `hmu` | Temperatures, pressures, energy counters, runtime, errors |
| Vaillant CTLV2 heating control | `ctlv2` | Zone temps, DHW, heating curve, schedules, operation modes |
| Vaillant VWZ00 ventilation | `vwz00` | Ventilation status, fan speeds |
| Vaillant system | `Broadcast` | Outdoor temperature, water pressure (system-wide values) |

## Register discovery

- On first connect, the integration runs `find` to discover all registers ebusd knows about
- Each register becomes an entity: sensor, number, select, switch, etc.
- Some registers only return data when the compressor is running (heating/DHW active). They show "unavailable" or "no data stored" when idle
- Custom registers (like room humidity `ctlv2.z1RoomHumidity`) are defined at runtime via `--enabledefine`

## YAML overrides

Create `config/vaillant_ebus/entities.yaml` to override auto-detected metadata:

```yaml
hmu.CurrentConsumedPower:
  device_class: "power"
  unit: "W"
  entity_category: "diagnostic"
```

Available keys: `friendly_name`, `icon`, `unit`, `device_class`, `entity_category`, `entity_type`, `enabled`, `writable`, `min`, `max`, `step`, `options`.

Reload after changes: **Settings → Devices & Services → Vaillant eBUS → Reload**.
