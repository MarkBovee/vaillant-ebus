"""Parsers for raw ebusd grab output — pure functions, no HA dependencies.

Unknown telegrams (no register label) are candidates for runtime `define -r`
registers that are absent from the installed ebusd CSV files.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TypedDict, cast


class GrabTelegram(TypedDict):
    master: str
    slave: str
    msgid: str
    sub: str
    request: str
    resp: str | None
    count: str
    label: str | None


# Parse ebusd telegrams from grab output into structured records.
# Known telegrams carry a register label after the count (`= N: hmu SetMode`);
# unknown ones do not.
# Return typed telegram records while preserving the historical dictionary schema.
def iter_grab_telegrams(grab_lines: Iterable[str]) -> Iterator[GrabTelegram]:
    """Yield parsed telegrams without retaining the input or output lists."""
    for line in grab_lines:
        line = line.strip()
        if not line or not line.startswith(("10", "11", "30", "31", "50", "51", "70", "71", "f0", "f1", "f3", "f5")):
            continue
        if " = " not in line:
            continue
        payload, _, suffix = line.partition(" = ")
        count_and_label = suffix.strip()
        count, _, label_part = count_and_label.partition(": ")
        count = count.strip()
        label_value: str | None = label_part.strip() or None
        req, _, resp_part = payload.partition(" / ")
        req = req.strip()
        resp_value: str | None = resp_part.strip() if resp_part else None
        if len(req) < 8:
            continue
        yield {
            "msgid": req[4:8],
            "master": req[0:2],
            "slave": req[2:4],
            "request": req,
            "sub": req[8:],
            "resp": resp_value,
            "count": count,
            "label": label_value,
        }


def parse_grab_lines(grab_lines: list[str]) -> list[GrabTelegram]:
    """Parse grab lines while preserving the historical list-based API."""
    return list(iter_grab_telegrams(grab_lines))


# Return only telegrams ebusd could not map to a known register label.
def unknown_telegrams(telegrams: Iterable[GrabTelegram] | list[str]) -> list[GrabTelegram]:
    """Return parsed telegrams without an ebusd register label."""
    values = list(telegrams)
    parsed: list[GrabTelegram]
    if values and isinstance(values[0], str):
        raw_lines = [value for value in values if isinstance(value, str)]
        parsed = parse_grab_lines(raw_lines)
    else:
        parsed = cast(list[GrabTelegram], values)
    return [telegram for telegram in parsed if telegram["label"] is None]
