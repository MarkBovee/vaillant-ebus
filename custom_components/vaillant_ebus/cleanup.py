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
    """Orphans that may be removed, and orphans that are kept because the user customised them."""

    orphans: tuple[OrphanEntity, ...]
    kept_customized: tuple[OrphanEntity, ...]


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


# Intent: report whether the user changed an entity registry entry by hand.
# Why: a renamed, re-iconed, relabelled or area-assigned entity carries user data that cleanup must not delete.
def _is_customized(entry: Any) -> bool:
    aliases = getattr(entry, "aliases", None) or ()
    return bool(
        getattr(entry, "name", None)
        or getattr(entry, "icon", None)
        or getattr(entry, "area_id", None)
        or getattr(entry, "labels", None)
        or any(alias for alias in aliases)
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


# Intent: build the orphan report for one config entry, or refuse when the report would not be trustworthy.
# Why: before ebusd is connected and entities are generated, every registry row looks orphaned; removing rows then
# would delete live entities. The generated unique ids carry the config entry prefix Home Assistant puts on them.
def stale_report(
    registry: Any,
    states: Any,
    entry_id: str,
    domain: str,
    coordinator: Any,
) -> OrphanReport | None:
    if coordinator is None or coordinator.ebus is None or not coordinator.ebus.is_connected:
        return None
    if not coordinator.entities:
        return None
    generated = {f"{entry_id}_{entity.unique_id}" for entity in coordinator.entities}
    return find_orphans(registry, states, entry_id, domain, generated)


# Intent: remove the given registry entities, then the devices of this config entry that have no entity left.
# Why: an empty zone or solar device would otherwise stay in the device list after its entities are gone.
def remove_orphans(
    registry: Any,
    device_registry: Any,
    entry_id: str,
    domain: str,
    entity_ids: Iterable[str],
) -> RemovalResult:
    removed = 0
    for entity_id in entity_ids:
        registry.async_remove(entity_id)
        removed += 1
    devices_with_entities = {entry.device_id for entry in registry.entities.values() if entry.device_id}
    removed_devices = 0
    for device_id, device in list(device_registry.devices.items()):
        if (
            entry_id in device.config_entries
            and any(identifier[0] == domain for identifier in device.identifiers)
            and device_id not in devices_with_entities
        ):
            device_registry.async_remove_device(device_id)
            removed_devices += 1
    return RemovalResult(entities=removed, devices=removed_devices)


# Intent: describe a few orphans in one text block for the confirmation step.
# Why: the user confirms a removal only when the names are visible; a long list is cut with a count of the rest.
def preview_text(orphans: Collection[OrphanEntity], limit: int = PREVIEW_LIMIT) -> str:
    shown = [f"- {item.label} ({item.entity_id})" for item in list(orphans)[:limit]]
    if len(orphans) > limit:
        shown.append(f"- ... and {len(orphans) - limit} more")
    return "\n".join(shown)
