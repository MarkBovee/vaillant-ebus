#!/usr/bin/env python3
"""Emit compact, derived views of a complete discovery dump."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _ROOT / "custom_components" / "vaillant_ebus" / "backend"


def _load_normalizer() -> Any:
    """Load the HA-independent normalizer without importing Home Assistant."""
    package = types.ModuleType("vaillant_ebus")
    package.__path__ = [str(_BACKEND.parent)]
    backend = types.ModuleType("vaillant_ebus.backend")
    backend.__path__ = [str(_BACKEND)]
    sys.modules.setdefault("vaillant_ebus", package)
    sys.modules.setdefault("vaillant_ebus.backend", backend)
    parser_name = "vaillant_ebus.backend.grab_parser"
    parser_spec = importlib.util.spec_from_file_location(parser_name, _BACKEND / "grab_parser.py")
    if parser_spec is None or parser_spec.loader is None:
        raise RuntimeError("Unable to load grab parser")
    parser = importlib.util.module_from_spec(parser_spec)
    sys.modules[parser_name] = parser
    parser_spec.loader.exec_module(parser)
    module_name = "vaillant_ebus.backend.dump_analysis"
    module_spec = importlib.util.spec_from_file_location(module_name, _BACKEND / "dump_analysis.py")
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError("Unable to load dump analysis")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    return module


def _matches(entry: dict[str, Any], circuits: list[str], names: list[re.Pattern[str]]) -> bool:
    circuit = str(entry.get("circuit", ""))
    name = str(entry.get("name", ""))
    return (not circuits or circuit in circuits) and (not names or any(pattern.search(name) for pattern in names))


def project_dump(
    dump: dict[str, Any], source: str, sections: set[str], circuits: list[str], names: list[str]
) -> dict[str, Any]:
    """Build a compact projection without mutating the normalized source data."""
    module = _load_normalizer()
    normalized = module.normalize_dump(dump)
    patterns = [re.compile(name) for name in names]
    selected: dict[str, Any] = {
        "source": source,
        "dump_version": normalized["dump_version"],
        "sections": sorted(sections),
        "complete_evidence": False,
        "raw_available": bool(
            normalized["raw"]["raw_find_lines"]
            or normalized["raw"]["raw_find_lines_after"]
            or normalized["raw"]["grab"]
        ),
    }
    if "summary" in sections:
        selected["summary"] = {
            "metadata": normalized["metadata"],
            "register_counts": {key: len(value) for key, value in normalized["registers"].items() if key != "entries"},
            "change_counts": {key: len(value) for key, value in normalized["changes"].items()},
            "traffic_counts": {
                "summary": len(normalized["traffic"]["summary"]),
                "unknown": len(normalized["traffic"]["unknown"]),
            },
        }
    if "registers" in sections:
        selected["registers"] = [
            entry for entry in normalized["registers"]["entries"] if _matches(entry, circuits, patterns)
        ]
    if "changes" in sections:
        selected["changes"] = normalized["changes"]
    if "unknown-telegrams" in sections:
        selected["unknown_telegrams"] = normalized["traffic"]["unknown"]
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument(
        "--section",
        action="append",
        choices=("summary", "registers", "changes", "unknown-telegrams"),
        dest="sections",
        default=None,
    )
    parser.add_argument("--circuit", action="append", default=[])
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        dump = yaml.safe_load(args.dump.read_text())
        if not isinstance(dump, dict):
            raise ValueError("dump root must be a mapping")
        result = project_dump(dump, str(args.dump), set(args.sections or ["summary"]), args.circuit, args.name)
        output = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(output)
        else:
            sys.stdout.write(output)
    except (OSError, ValueError, re.error, yaml.YAMLError) as exc:
        print(f"dump projection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
