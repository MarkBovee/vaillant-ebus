"""Guard: no blocking file or sleep calls directly inside an async function of the integration."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "vaillant_ebus"

# Blocking names, by receiver. Home Assistant (and the HACS reviewers) reject these on the event loop.
BLOCKING_OS_CALLS = {
    "replace", "unlink", "remove", "makedirs", "mkdir", "rename", "listdir", "scandir", "stat", "rmdir", "walk",
    "fsync", "fdopen", "open", "close",
}  # fmt: skip
BLOCKING_OS_PATH_CALLS = {"exists", "isfile", "isdir", "getsize", "getmtime"}
BLOCKING_PATH_METHODS = {"read_text", "write_text", "read_bytes", "write_bytes", "iterdir", "rglob", "mkdir", "unlink"}


# Intent: name the blocking call a node makes, or return None for a harmless call.
# Why: one classifier keeps the scan and its self-check on identical rules.
def _blocking_call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return "open()" if func.id == "open" else None
    if not isinstance(func, ast.Attribute):
        return None
    receiver = func.value
    if isinstance(receiver, ast.Name) and receiver.id == "os" and func.attr in BLOCKING_OS_CALLS:
        return f"os.{func.attr}()"
    if isinstance(receiver, ast.Name) and receiver.id == "time" and func.attr == "sleep":
        return "time.sleep()"
    if isinstance(receiver, ast.Attribute) and receiver.attr == "path" and func.attr in BLOCKING_OS_PATH_CALLS:
        return f"os.path.{func.attr}()"
    if func.attr in BLOCKING_PATH_METHODS:
        return f".{func.attr}()"
    return None


# Intent: collect blocking calls made directly in async functions, ignoring nested sync helpers.
# Why: a sync helper handed to async_add_executor_job is the sanctioned place for this I/O.
def find_blocking_calls(source: str) -> list[tuple[int, str, str]]:
    findings: list[tuple[int, str, str]] = []
    for function in ast.walk(ast.parse(source)):
        if not isinstance(function, ast.AsyncFunctionDef):
            continue
        pending: list[ast.AST] = list(function.body)
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            pending.extend(ast.iter_child_nodes(node))
            if isinstance(node, ast.Call) and (name := _blocking_call_name(node)) is not None:
                findings.append((node.lineno, function.name, name))
    return sorted(findings)


# Intent: the integration has no blocking file or sleep call directly inside an async function.
# Why: blocking the Home Assistant event loop stalls every integration on slow storage (HACS review of 1.12.2).
@pytest.mark.parametrize("path", sorted(INTEGRATION_DIR.rglob("*.py")), ids=lambda p: p.name)
def test_no_blocking_io_directly_in_async_functions(path: Path) -> None:
    findings = find_blocking_calls(path.read_text(encoding="utf-8"))
    assert findings == [], f"{path.name}: move these into a sync helper run with async_add_executor_job: {findings}"


# Intent: prove the scanner flags the exact patterns the HACS review found and accepts the executor pattern.
# Why: a guard that never fires would give false confidence.
def test_scanner_flags_blocking_calls_and_accepts_executor_helpers() -> None:
    blocking = (
        "async def save(self):\n"
        "    os.makedirs(d, exist_ok=True)\n"
        "    os.replace(a, b)\n"
        "    if os.path.exists(a):\n"
        "        os.unlink(a)\n"
        "    open(a).read()\n"
        "    time.sleep(1)\n"
        "    path.read_text()\n"
    )
    names = [name for _, _, name in find_blocking_calls(blocking)]
    assert sorted(names) == sorted(
        ["os.makedirs()", "os.replace()", "os.path.exists()", "os.unlink()", "open()", "time.sleep()", ".read_text()"]
    )
    sanctioned = (
        "async def save(self):\n"
        "    def _write():\n"
        "        os.replace(a, b)\n"
        "    await hass.async_add_executor_job(_write)\n"
    )
    assert find_blocking_calls(sanctioned) == []
