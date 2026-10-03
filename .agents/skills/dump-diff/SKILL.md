# Dump Diff Skill

Compare two discovery dumps from HA to detect eBUS register changes after an action (e.g., changing thermostat settings, toggling features).

## Trigger
- "compare dumps", "diff discovery dumps", "what changed in the dump"

## Workflow

1. Ensure at least 2 dumps exist on HA (`/config/vaillant_ebus/discovery_dump_*.yaml`)
2. Trigger new dump via `export_discovery_dump` service if needed
3. Run comparison:
   ```bash
   PASS=$(grep SSH_PASSWORD .env | cut -d= -f2-)
   python3 tools/compare_dumps.py
   ```
4. Analyze changes — focus on circuits/names that changed, ignore natural drift (temp, time, runtime)

## Manual reference

If the script isn't available, on HA:
```bash
# Diff all register values between two latest dumps
diff <(grep -E 'name:|value:' /config/path/dump1.yaml) <(grep -E 'name:|value:' /config/path/dump2.yaml)
```

## Notes
- Temperature, time, runtime counters drift naturally — ignore those
- Focus on mode changes (on/off, auto/manual), date changes, boolean flag changes
- Some r5 registers return `ERR: element not found` — these are conditional on features not present on this hardware
- Dumps include both discovered (`find`) and REGISTER_MAP entries (via fallback_read)
