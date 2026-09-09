"""Backward-compatible discovery dump normalization and analysis."""

from __future__ import annotations

from typing import Any

from .grab_parser import parse_grab_lines

CURRENT_DUMP_VERSION = 4
_SENTINELS = ("", "-", "empty", "unknown", "unavailable", "no data stored")


def _meaningful(value: Any) -> bool:
    """Return whether a register value carries usable data."""
    if value is None:
        return False
    text = str(value).strip().lower()
    return not any(text == sentinel or text.startswith(f"{sentinel} ") for sentinel in _SENTINELS)


def _registers_by_key(registers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index serialized register entries by stable circuit/name key."""
    return {
        f"{entry.get('circuit', '')}.{entry.get('name', '')}": entry
        for entry in registers
        if entry.get("circuit") and entry.get("name")
    }


def _register_categories(registers: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Classify discovered, mapped, unavailable, and disabled registers."""
    categories: dict[str, list[str]] = {
        "discovered": [],
        "mapped": [],
        "unavailable": [],
        "disabled": [],
    }
    for entry in registers:
        key = f"{entry.get('circuit', '')}.{entry.get('name', '')}"
        if not key.startswith("."):
            if entry.get("from_map"):
                categories["mapped"].append(key)
            else:
                categories["discovered"].append(key)
            if not entry.get("has_data", False):
                categories["unavailable"].append(key)
            if entry.get("disabled", False):
                categories["disabled"].append(key)
    for values in categories.values():
        values.sort()
    return categories


def _register_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """Compare register snapshots while ignoring sentinel-only transitions."""
    old = _registers_by_key(before)
    new = _registers_by_key(after)
    changes: dict[str, list[Any]] = {
        "new_registers": sorted(set(new) - set(old)),
        "changed_registers": [],
        "disappeared_registers": sorted(set(old) - set(new)),
    }
    for key in sorted(set(old) & set(new)):
        old_values = old[key].get("values", [])
        new_values = new[key].get("values", [])
        if old_values == new_values:
            continue
        if not any(_meaningful(value) for value in old_values + new_values):
            continue
        changes["changed_registers"].append({"key": key, "before": old_values, "after": new_values})
    return changes


def group_telegrams(telegrams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate telegrams by bus identity, preserving changing responses."""
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for telegram in telegrams:
        key = tuple(telegram.get(field) for field in ("master", "slave", "msgid", "sub", "label"))
        group = groups.setdefault(
            key,
            {
                "master": telegram.get("master"),
                "slave": telegram.get("slave"),
                "msgid": telegram.get("msgid"),
                "sub": telegram.get("sub"),
                "label": telegram.get("label"),
                "known": bool(telegram.get("label")),
                "occurrence_count": 0,
                "unique_requests": [],
                "unique_responses": [],
            },
        )
        group["occurrence_count"] += int(telegram.get("count") or 1)
        request = telegram.get("request") or telegram.get("req")
        response = telegram.get("resp")
        if request and request not in group["unique_requests"]:
            group["unique_requests"].append(request)
        if response and response not in group["unique_responses"]:
            group["unique_responses"].append(response)
    return sorted(
        groups.values(),
        key=lambda item: (
            item["msgid"] or "",
            item["master"] or "",
            item["slave"] or "",
            item["sub"] or "",
        ),
    )


def normalize_dump(dump: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy/current/future dump data without mutating input."""
    metadata = dict(dump.get("metadata") or {})
    version = metadata.get("dump_version", 1)
    known_version = isinstance(version, int) and version <= CURRENT_DUMP_VERSION
    before = list(dump.get("before_registers") or [])
    after = list(dump.get("after_registers") or [])
    current = after or before
    raw_grab = list(dump.get("grab") or [])
    parsed = parse_grab_lines(raw_grab) if raw_grab else list(dump.get("labeled_telegrams") or [])
    unknown = [telegram for telegram in parsed if not telegram.get("label")]
    return {
        "dump_version": version,
        "version_supported": known_version,
        "metadata": metadata,
        "registers": {
            **_register_categories(current),
            "entries": current,
        },
        "changes": (
            _register_changes(before, after)
            if after
            else {"new_registers": [], "changed_registers": [], "disappeared_registers": []}
        ),
        "traffic": {
            "summary": group_telegrams(parsed),
            "unknown": group_telegrams(unknown),
        },
        "raw": {
            "raw_find_lines": list(dump.get("raw_find_lines") or []),
            "before_registers": before,
            "after_registers": after,
            "grab": raw_grab,
        },
    }
