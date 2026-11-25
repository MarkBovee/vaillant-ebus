"""Find and remove Vaillant eBUS registry entries that no entity provides any more.

The helpers take the Home Assistant registries and the state machine as arguments, so they hold no Home Assistant
imports and the options flow and the repairs flow can share them.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Registry rows of internal helper entities that earlier releases created and no release provides any more.
LEGACY_HELPER_SUFFIXES = ("_tmpb516montheven",)
PREVIEW_LIMIT = 15

# Unique ids of the hand-built zone entities (climate and flow range); a bare flow range row belongs to zone 1.
_HAND_BUILT_ZONE_ID = re.compile(r"_climate_(?:z(\d+)|flow_temp_range(?:_z(\d+))?)$")


@dataclass(frozen=True)
class OrphanEntity:
    """One registry entry that no entity provides any more."""

    entity_id: str
    unique_id: str
    label: str


@dataclass(frozen=True)
class EmptyDevice:
    """One device of this integration that no entity registry row points to any more."""

    device_id: str
    label: str


@dataclass(frozen=True)
class OrphanReport:
    """Orphans that may be removed, rows that are kept because the user customised them, dormant rows and empty
    devices."""

    orphans: tuple[OrphanEntity, ...]
    kept_customized: tuple[OrphanEntity, ...]
    dormant: tuple[OrphanEntity, ...] = ()
    empty_devices: tuple[EmptyDevice, ...] = ()

    # Report whether the user has anything to confirm: rows to remove, rows to switch off or devices to remove.
    @property
    def has_work(self) -> bool:
        return bool(self.orphans or self.dormant or self.empty_devices)

    # Report whether the confirmation removes registry rows or devices (switching rows off needs no removal).
    @property
    def has_removals(self) -> bool:
        return bool(self.orphans or self.empty_devices)


@dataclass(frozen=True)
class RemovalResult:
    """How many registry entities and empty devices a removal took out."""

    entities: int
    devices: int


# Read a registry "disabled by"/"hidden by" marker as a plain lower-case string.
# Home Assistant stores these as enum members; tests and older versions may hand in plain strings.
def _marker(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value)).casefold()


# Report whether one alias is text the user typed.
# Home Assistant 2026.10 gives every registry row a default alias, the sentinel "use the entity name" (null on
# disk, a truthy enum member in memory). Treating it as user data made every row look customised, so nothing was
# ever offered for removal. Only a non-blank string is a customisation.
def _is_user_alias(alias: Any) -> bool:
    return isinstance(alias, str) and bool(alias.strip())


# Option keys the integration or Home Assistant fill in on their own; everything else under `sensor` is a user choice.
_DEFAULT_SENSOR_OPTION_KEYS = frozenset({"suggested_display_precision", "suggested_unit_of_measurement"})


# Report whether the registry `options` hold a choice the user made, not the defaults of a new row.
# Since Home Assistant 2026.10 every row carries `sensor.suggested_display_precision` and
# `conversation.should_expose: False`; a unit or display precision override or an Assist exposure is user data.
def _has_user_options(options: Any) -> bool:
    if not isinstance(options, Mapping):
        return False
    conversation = options.get("conversation")
    if isinstance(conversation, Mapping) and conversation.get("should_expose") is True:
        return True
    for domain, domain_options in options.items():
        if domain == "conversation" or not isinstance(domain_options, Mapping):
            continue
        if any(key not in _DEFAULT_SENSOR_OPTION_KEYS for key in domain_options):
            return True
    return False


# Report whether the user changed an entity registry entry by hand.
# A renamed, re-iconed, relabelled, categorised or area-assigned entity, a device class, unit or display override
# and an Assist exposure carry user data that cleanup must not delete.
def is_customized(entry: Any) -> bool:
    aliases = getattr(entry, "aliases", None) or ()
    return bool(
        getattr(entry, "name", None)
        or getattr(entry, "icon", None)
        or getattr(entry, "area_id", None)
        or getattr(entry, "labels", None)
        or getattr(entry, "categories", None)
        or getattr(entry, "device_class", None)
        or _has_user_options(getattr(entry, "options", None))
        or any(_is_user_alias(alias) for alias in aliases)
        or _marker(getattr(entry, "hidden_by", None)) == "user"
    )


# Report whether the state machine holds only the placeholder state of a registry entry without an entity.
# Home Assistant marks such a state `restored: true`; a live entity that is merely unavailable (ebusd down) or
# unknown (no holiday set) has no such marker and must never count as an orphan.
def _is_restored_placeholder(state: Any) -> bool:
    if state is None or state.state != "unavailable":
        return False
    return state.attributes.get("restored") is True


# Return the zone number of a hand-built zone entity (climate, flow range), or None for any other unique id.
def _hand_built_zone_number(unique_id: str) -> int | None:
    match = _HAND_BUILT_ZONE_ID.search(unique_id.lower())
    if match is None:
        return None
    return int(match.group(1) or match.group(2) or 1)


# Report whether a unique id has the shape of a generated entity description: entry, `ebusd`, circuit, name.
# Hand-built entities (quick veto end, online, climate) also register as disabled by the integration but have no
# description, so only generated ids can be judged against the set of generated unique ids.
def _is_generated_id(unique_id: str, entry_id: str) -> bool:
    prefix = f"{entry_id}_ebusd_"
    return unique_id.startswith(prefix) and "_" in unique_id[len(prefix) :]


# Report whether a restored row may be offered for removal given the zones the controllers declare unused.
# The climate and flow-range entities exist only while a zone shows a live room temperature, so a short read error on
# the bus drops them after a reload and their rows turn into placeholders although the zone is real (issue #192, the
# Zone 1 climate was deleted). Such a row is an orphan only when the controller itself says the zone is inactive.
def _zone_row_may_go(unique_id: str, unused_zone_numbers: Collection[int]) -> bool:
    number = _hand_built_zone_number(str(unique_id))
    return number is None or number in unused_zone_numbers


# List the registry entries of this config entry that no entity provides any more.
# Removed zones, replaced register layouts and earlier releases leave entries behind; the old purge looked at the
# state `unknown` instead, which deleted live entities and missed these (issue #186 follow-up).
# Enabled entries are orphans when only a restored placeholder state exists. Entries disabled by the integration are
# orphans when the current discovery generates no entity with that unique id. Entries disabled by the user stay.
def find_orphans(
    registry: Any,
    states: Any,
    entry_id: str,
    domain: str,
    generated_unique_ids: Collection[str],
    unused_zone_numbers: Collection[int] = (),
) -> OrphanReport:
    orphans: list[OrphanEntity] = []
    kept: list[OrphanEntity] = []
    for entry in registry.entities.get_entries_for_config_entry_id(entry_id):
        if entry.platform != domain:
            continue
        disabled_by = _marker(getattr(entry, "disabled_by", None))
        if disabled_by == "user":
            continue
        state = states.get(entry.entity_id)
        if str(entry.unique_id).lower().endswith(LEGACY_HELPER_SUFFIXES):
            is_orphan = True
        elif disabled_by is None:
            is_orphan = _is_restored_placeholder(state) and _zone_row_may_go(entry.unique_id, unused_zone_numbers)
        else:
            is_orphan = _is_generated_id(entry.unique_id, entry_id) and entry.unique_id not in generated_unique_ids
        if not is_orphan:
            continue
        label = (state.attributes.get("friendly_name") if state is not None else None) or entry.entity_id
        item = OrphanEntity(entity_id=entry.entity_id, unique_id=entry.unique_id, label=str(label))
        (kept if is_customized(entry) else orphans).append(item)
    return OrphanReport(orphans=tuple(orphans), kept_customized=tuple(kept))


# List enabled registry entries whose live entity has no value and that the current discovery switches off.
# Older releases created sensors for hardware that is not there (storage temperatures) and for service registers as
# enabled. Home Assistant never changes an enabled row, and the integration leaves enabled rows of default-off entities
# alone, so they stay `unknown` for ever. `switched_off_unique_ids` holds the casefolded unique ids of the generated
# descriptions that are off by default; hand-built entities and default-on entities are not in it, so an unset
# holiday date or a live sensor is never listed, and the live state must be `unknown`, so a row that has a value is
# never listed. Returns the dormant rows and the customised rows that are kept.
def find_dormant(
    registry: Any,
    states: Any,
    entry_id: str,
    domain: str,
    switched_off_unique_ids: Collection[str],
) -> tuple[tuple[OrphanEntity, ...], tuple[OrphanEntity, ...]]:
    dormant: list[OrphanEntity] = []
    kept: list[OrphanEntity] = []
    for entry in registry.entities.get_entries_for_config_entry_id(entry_id):
        if entry.platform != domain or _marker(getattr(entry, "disabled_by", None)) is not None:
            continue
        if str(entry.unique_id).casefold() not in switched_off_unique_ids:
            continue
        state = states.get(entry.entity_id)
        if state is None or state.state != "unknown":
            continue
        label = state.attributes.get("friendly_name") or entry.entity_id
        item = OrphanEntity(entity_id=entry.entity_id, unique_id=entry.unique_id, label=str(label))
        (kept if is_customized(entry) else dormant).append(item)
    return tuple(dormant), tuple(kept)


# Report whether a device belongs to this integration, has no entity row left and carries no user data.
# A device the user renamed or labelled stays, because that is user data like a renamed entity.
def _device_may_go(device: Any, domain: str, devices_with_entities: Collection[str]) -> bool:
    return (
        any(identifier[0] == domain for identifier in device.identifiers)
        and device.id not in devices_with_entities
        and not getattr(device, "name_by_user", None)
        and not getattr(device, "labels", None)
    )


# Return the ids of the devices that at least one entity registry row points to.
def _devices_with_entities(registry: Any) -> set[str]:
    return {entry.device_id for entry in registry.entities.values() if entry.device_id}


# Return the circuit names a device is registered under (its identifiers of this domain), casefolded.
def _device_circuits(device: Any, domain: str) -> set[str]:
    return {str(identifier[1]).casefold() for identifier in device.identifiers if identifier[0] == domain}


# List the devices of this config entry that hold no entity row any more.
# Earlier releases created devices for unused zones (Zone 2, Zone 3 on a one-zone system); once their entities were
# removed, by hand or by an older cleanup, the empty device stayed, and the removal of empty devices only ran as a
# side effect of removing an entity, so a purge with no entity to remove left them for ever. A device whose circuit
# still owns a generated entity is never listed, so a device whose rows are being written right now is safe.
def find_empty_devices(
    registry: Any,
    devices: Iterable[Any],
    domain: str,
    live_circuits: Collection[str],
) -> tuple[EmptyDevice, ...]:
    with_entities = _devices_with_entities(registry)
    empty: list[EmptyDevice] = []
    for device in devices:
        if not _device_may_go(device, domain, with_entities):
            continue
        if _device_circuits(device, domain) & set(live_circuits):
            continue
        label = getattr(device, "name", None) or device.id
        empty.append(EmptyDevice(device_id=device.id, label=str(label)))
    return tuple(empty)


# Build the casefolded `circuit.name` key of an entity description, the key of its parent register.
# The runtime-defined register set, the no-data disabling and the cleanup report must agree on one key format.
def register_key_fold(description: Any) -> str:
    return f"{getattr(description, 'circuit', '')}.{getattr(description, 'name', '')}".casefold()


# Map each generated unique id (casefolded, without the config-entry prefix) to the platform its registry rows use.
# The entity factory keeps that platform while a register has no data (issue #152). A unique id whose rows sit on
# different platforms is ambiguous and left out: one of them is a leftover (for example a binary_sensor row from
# before issue #216 next to the current sensor), and guessing would bring the flip back.
def registry_platforms(registry: Any, entry_id: str) -> dict[str, str]:
    prefix = f"{entry_id}_"
    platforms: dict[str, set[str]] = {}
    # Read all rows like the coordinator's registry passes do; the prefix and the config entry keep other entries out.
    for entry in list(registry.entities.values()):
        unique_id = str(entry.unique_id)
        if not unique_id.startswith(prefix) or getattr(entry, "config_entry_id", entry_id) != entry_id:
            continue
        domain = str(entry.entity_id).partition(".")[0]
        platforms.setdefault(unique_id[len(prefix) :].casefold(), set()).add(domain)
    return {unique_id: next(iter(domains)) for unique_id, domains in platforms.items() if len(domains) == 1}


# Build the cleanup report for one config entry, or refuse when the report would not be trustworthy.
# Before ebusd is connected and entities are generated, every registry row looks orphaned; removing rows then
# would delete live entities. The generated unique ids carry the config entry prefix Home Assistant puts on them.
# `discovery_ready` also excludes the window where entities come from the cache and no live discovery has run yet, in
# which a cached `unknown` state would look like a register without data. Registers the integration defined itself
# (passive definitions) are never offered as dormant: they have no value until the gateway sends the frame, a user may
# have switched them on on purpose, and the coordinator leaves them alone for the same reason. `devices` are the device
# entries of this config entry (Home Assistant's `async_entries_for_config_entry`); empty ones are listed for removal.
def stale_report(
    registry: Any,
    states: Any,
    entry_id: str,
    domain: str,
    coordinator: Any,
    devices: Iterable[Any] = (),
) -> OrphanReport | None:
    if coordinator is None or coordinator.ebus is None or not coordinator.ebus.is_connected:
        return None
    if not coordinator.discovery_ready or not coordinator.entities:
        return None
    generated = {f"{entry_id}_{entity.unique_id}" for entity in coordinator.entities}
    runtime_defined = coordinator.runtime_defined_key_folds()
    switched_off = {
        f"{entry_id}_{entity.unique_id}".casefold()
        for entity in coordinator.entities
        if getattr(entity, "enabled_by_default", True) is False and register_key_fold(entity) not in runtime_defined
    }
    report = find_orphans(registry, states, entry_id, domain, generated, coordinator.unused_zone_numbers())
    dormant, kept = find_dormant(registry, states, entry_id, domain, switched_off)
    live_circuits = {
        str(getattr(entity, "device_circuit", None) or "").casefold() for entity in coordinator.entities
    } - {""}
    empty_devices = find_empty_devices(registry, devices, domain, live_circuits)
    return OrphanReport(
        orphans=report.orphans,
        kept_customized=(*report.kept_customized, *kept),
        dormant=dormant,
        empty_devices=empty_devices,
    )


# Switch the given entity registry rows off as disabled by the integration and return how many were changed.
# Only a row the integration disabled is switched on again by the analysis when its register returns a value; the
# caller passes the Home Assistant disabler so this module needs no Home Assistant import. Each row is read again, so a
# row that was removed, switched off or customised after the report was built is left as it is.
def disable_dormant(registry: Any, entity_ids: Iterable[str], disabler: Any) -> int:
    switched = 0
    for entity_id in entity_ids:
        entry = registry.async_get(entity_id)
        # The report was built a moment ago; skip a row that was removed, switched off or customised since then.
        if entry is None or _marker(getattr(entry, "disabled_by", None)) is not None or is_customized(entry):
            continue
        registry.async_update_entity(entity_id, disabled_by=disabler)
        _LOGGER.debug("Switched off %s because its register has no data", entity_id)
        switched += 1
    return switched


# Remove the given registry entities, then those devices of this config entry that have no entity left.
# An empty zone or solar device would otherwise stay in the device list after its entities are gone. A device the
# user renamed or labelled stays (`_device_may_go`). The entity list may be empty: then only the devices that are
# already empty go, which is how a leftover Zone 2 or Zone 3 device is removed. The caller passes the device entries
# of this config entry (Home Assistant's `async_entries_for_config_entry`), because iterating the registry yields ids on
# older versions and reading `DeviceEntry.config_entries` is deprecated since 2026.10.
def remove_orphans(
    registry: Any,
    device_registry: Any,
    domain: str,
    entity_ids: Iterable[str],
    devices: Iterable[Any],
) -> RemovalResult:
    removed = 0
    for entity_id in entity_ids:
        registry.async_remove(entity_id)
        removed += 1
    devices_with_entities = _devices_with_entities(registry)
    removed_devices = 0
    for device in list(devices):
        if _device_may_go(device, domain, devices_with_entities):
            device_registry.async_remove_device(device.id)
            removed_devices += 1
    return RemovalResult(entities=removed, devices=removed_devices)


# Describe a few orphans in one text block for the confirmation step.
# The user confirms a removal only when the names are visible; a long list is cut with a count of the rest.
def preview_text(orphans: Collection[OrphanEntity], limit: int = PREVIEW_LIMIT) -> str:
    return _preview_lines([f"- {item.label} ({item.entity_id})" for item in orphans], limit)


# Cut a list of preview lines to `limit` lines plus a count of the rest; an empty list reads "- none".
def _preview_lines(lines: list[str], limit: int = PREVIEW_LIMIT) -> str:
    if not lines:
        return "- none"
    shown = lines[:limit]
    if len(lines) > limit:
        shown.append(f"- ... and {len(lines) - limit} more")
    return "\n".join(shown)


# Build the text placeholders the repair issue, the repair flow and the options purge show for one report.
# All three screens describe the same report, so they share one builder instead of three copies.
def report_placeholders(report: OrphanReport) -> dict[str, str]:
    return {
        "count": str(len(report.orphans)),
        "entities": preview_text(report.orphans),
        "dormant_count": str(len(report.dormant)),
        "dormant": preview_text(report.dormant),
        "device_count": str(len(report.empty_devices)),
        "devices": _preview_lines([f"- {device.label}" for device in report.empty_devices]),
        "kept": str(len(report.kept_customized)),
    }
