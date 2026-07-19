# Auto-Discovery

## Requirements

1. On startup, call `f` (find) on ebusd TCP → returns all 362 registers + current values
2. Parse each line: `<circuit> <name> = <value>`
3. Classify: numeric, enum, boolean based on value content
4. Detect writability: registers in `ctlv2` circuit are writable
5. Generate entity descriptions with inferred metadata:
   - Temperature values → device_class temperature, unit °C
   - Pressure values → device_class pressure, unit bar
   - Energy values → device_class energy, unit kWh
   - Power values → device_class power, unit W
   - Duration → device_class duration, unit h
   - On/Off/Yes/No → binary sensor or switch
   - Enum strings → sensor (readonly) or select (writable)
6. Apply `entities.yaml` overrides after inference
7. Deduplicate: one entity per unique circuit+name+field
8. Mark registers with "no data stored" as unavailable (available when data appears)

## entities.yaml format

```yaml
# Optional overrides
hmu.SetMode:
  enabled: false  # hide complex multi-field register

ctlv2.HwcTempDesired:
  friendly_name: "DHW Target Temperature"
  icon: "mdi:water-thermometer"
  unit: "°C"
  device_class: "temperature"
  writable: true
  min: 30
  max: 70
  step: 1
```

## Implementation

```python
class DiscoveryService:
    async def discover(self, backend) -> list[EntityDescription]
    def load_overrides(self, yaml_path: str) -> dict
    def classify(self, register: Register) -> EntityType
```

## Edge cases
- `find` timeout → retry, fail gracefully
- Empty response → warn, continue with cached discovery
- New register appears between polls → next `find` cycle picks it up
- Register disappears → entity becomes unavailable, removed on next full `find`
