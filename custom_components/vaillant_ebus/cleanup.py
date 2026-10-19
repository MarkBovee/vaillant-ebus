"""Find and remove Vaillant eBUS registry entries that no entity provides any more.

The helpers take the Home Assistant registries and the state machine as arguments, so they hold no Home Assistant
imports and the options flow and the repairs flow can share them.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Any

# Registry rows of internal helper entities that earlier releases created and no release provides any more.
LEGACY_HELPER_SUFFIXES = ("_tmpb516montheven",)
PREVIEW_LIMIT = 15


@dataclass(frozen=True)
class OrphanEntity:
    """One registry entry that no entity provides any more."""

    entity_id: str
    unique_id: str
    label: str


@dataclass(frozen=True)
class OrphanReport:
    """Orphans that may be removed, rows that are kept because the user customised them, and dormant rows."""

    orphans: tuple[OrphanEntity, ...]
    kept_customized: tuple[OrphanEntity, ...]
    dormant: tuple[OrphanEntity, ...] = ()


@dataclass(frozen=True)
class RemovalResult:
    """How many registry entities and empty devices a removal took out."""

    entities: int
    devices: int


# Intent: read a registry "disabled by"/"hidden by" marker as a plain lower-case string.
# Why: Home Assistant stores these as enum members; tests and older versions may hand in plain strings.
def _marker(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value)).casefold()


# Intent: report whether one alias is text the user typed.
# Why: Home Assistant 2026.10 gives every registry row a default alias, the sentinel "use the entity name" (null on
# disk, a truthy enum member in memory). Treating it as user data made every row look customised, so nothing was
# ever offered for removal. Only a non-blank string is a customisation.
def _is_user_alias(alias: Any) -> bool:
    return isinstance(alias, str) and bool(alias.strip())


# Intent: report whether the user changed an entity registry entry by hand.
# Why: a renamed, re-iconed, relabelled or area-assigned entity carries user data that cleanup must not delete.
def _is_customized(entry: Any) -> bool:
    aliases = getattr(entry, "aliases", None) or ()
    return bool(
        getattr(entry, "name", None)
        or getattr(entry, "icon", None)
        or getattr(entry, "area_id", None)
        or getattr(entry, "labels", None)
        or any(_is_user_alias(alias) for alias in aliases)
        or _marker(getattr(entry, "hidden_by", None)) == "user"
    )


# Intent: report whether the state machine holds only the placeholder state of a registry entry without an entity.
# Why: Home Assistant marks such a state `restored: true`; a live entity that is merely unavailable (ebusd down) or
# unknown (no holiday set) has no such marker and must never count as an orphan.
def _is_restored_placeholder(state: Any) -> bool:
    if state is None or state.state != "unavailable":
        return False
    return state.attributes.get("restored") is True


# Intent: report whether a unique id has the shape of a generated entity description: entry, `ebusd`, circuit, name.
# Why: hand-built entities (quick veto end, online, climate) also register as disabled by the integration but have no
# description, so only generated ids can be judged against the set of generated unique ids.
def _is_generated_id(unique_id: str, entry_id: str) -> bool:
    prefix = f"{entry_id}_ebusd_"
    return unique_id.startswith(prefix) and "_" in unique_id[len(prefix) :]


# Intent: list the registry entries of this config entry that no entity provides any more.
# Why: removed zones, replaced register layouts and earlier releases leave entries behind; the old purge looked at the
# state `unknown` instead, which deleted live entities and missed these (issue #186 follow-up).
# Enabled entries are orphans when only a restored placeholder state exists. Entries disabled by the integration are
# orphans when the current discovery generates no entity with that unique id. Entries disabled by the user stay.
def find_orphans(
    registry: Any,
    states: Any,
    entry_id: str,
    domain: str,
    generated_unique_ids: Collection[str],
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
            is_orphan = _is_restored_placeholder(state)
        else:
            is_orphan = _is_generated_id(entry.unique_id, entry_id) and entry.unique_id not in generated_unique_ids
        if not is_orphan:
            continue
        label = (state.attributes.get("friendly_name") if state is not None else None) or entry.entity_id
        item = OrphanEntity(entity_id=entry.entity_id, unique_id=entry.unique_id, label=str(label))
        (kept if _is_customized(entry) else orphans).append(item)
    return OrphanReport(orphans=tuple(orphans), kept_customized=tuple(kept))


# Intent: list enabled registry entries whose live entity has no value and that the current discovery switches off.
# Why: older releases created sensors for hardware that is not there (storage temperatures) and for service registers as
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
        (kept if _is_customized(entry) else dormant).append(item)
    return tuple(dormant), tuple(kept)


# Intent: build the cleanup report for one config entry, or refuse when the report would not be trustworthy.
# Why: before ebusd is connected and entities are generated, every registry row looks orphaned; removing rows then
# would delete live entities. The generated unique ids carry the config entry prefix Home Assistant puts on them.
# `discovery_ready` also excludes the window where entities come from the cache and no live discovery has run yet, in
# which a cached `unknown` state would look like a register without data. Registers the integration defined itself
# (passive definitions) are never offered as dormant: they have no value until the gateway sends the frame, a user may
# have switched them on on purpose, and the coordinator leaves them alone for the same reason.
def stale_report(
    registry: Any,
    states: Any,
    entry_id: str,
    domain: str,
    coordinator: Any,
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
        if getattr(entity, "enabled_by_default", True) is False
        and f"{getattr(entity, 'circuit', '')}.{getattr(entity, 'name', '')}".casefold() not in runtime_defined
    }
    report = find_orphans(registry, states, entry_id, domain, generated)
    dormant, kept = find_dormant(registry, states, entry_id, domain, switched_off)
    return OrphanReport(orphans=report.orphans, kept_customized=(*report.kept_customized, *kept), dormant=dormant)


# Intent: switch the given entity registry rows off as disabled by the integration and return how many were changed.
# Why: only a row the integration disabled is switched on again by the analysis when its register returns a value; the
# caller passes the Home Assistant disabler so this module needs no Home Assistant import. Each row is read again, so a
# row that was removed, switched off or customised after the report was built is left as it is.
def disable_dormant(registry: Any, entity_ids: Iterable[str], disabler: Any) -> int:
    switched = 0
    for entity_id in entity_ids:
        entry = registry.async_get(entity_id)
        # The report was built a moment ago; skip a row that was removed, switched off or customised since then.
        if entry is None or _marker(getattr(entry, "disabled_by", None)) is not None or _is_customized(entry):
            continue
        registry.async_update_entity(entity_id, disabled_by=disabler)
        switched += 1
    return switched


# Intent: remove the given registry entities, then those devices of this config entry that have no entity left.
# Why: an empty zone or solar device would otherwise stay in the device list after its entities are gone. A device the
# user renamed or labelled stays, because that is user data like a renamed entity. The caller passes the device entries
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
    devices_with_entities = {entry.device_id for entry in registry.entities.values() if entry.device_id}
    removed_devices = 0
    for device in list(devices):
        if (
            any(identifier[0] == domain for identifier in device.identifiers)
            and device.id not in devices_with_entities
            and not getattr(device, "name_by_user", None)
            and not getattr(device, "labels", None)
        ):
            device_registry.async_remove_device(device.id)
            removed_devices += 1
    return RemovalResult(entities=removed, devices=removed_devices)


# Intent: describe a few orphans in one text block for the confirmation step.
# Why: the user confirms a removal only when the names are visible; a long list is cut with a count of the rest.
def preview_text(orphans: Collection[OrphanEntity], limit: int = PREVIEW_LIMIT) -> str:
    if not orphans:
        return "- none"
    shown = [f"- {item.label} ({item.entity_id})" for item in list(orphans)[:limit]]
    if len(orphans) > limit:
        shown.append(f"- ... and {len(orphans) - limit} more")
    return "\n".join(shown)
