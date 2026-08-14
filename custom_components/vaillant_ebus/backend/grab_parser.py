"""Parsers for raw ebusd grab output — pure functions, no HA dependencies.

Unknown telegrams (no register label) are candidates for runtime `define -r`
registers that are absent from the installed ebusd CSV files.
"""

from __future__ import annotations


# Parse ebusd telegrams from grab output into structured records.
# Known telegrams carry a register label after the count (`= N: hmu SetMode`);
# unknown ones do not.
def parse_grab_lines(grab_lines: list[str]) -> list[dict]:
    telegrams: list[dict] = []
    for line in grab_lines:
        line = line.strip()
        if not line or not line.startswith(("10", "11", "30", "31", "50", "51", "70", "71", "f0", "f1", "f3", "f5")):
            continue
        if " = " not in line:
            continue
        payload, _, suffix = line.partition(" = ")
        count_and_label = suffix.strip()
        count, _, label = count_and_label.partition(": ")
        count = count.strip()
        label = label.strip() or None
        req, _, resp = payload.partition(" / ")
        req = req.strip()
        resp = resp.strip() if resp else None
        if len(req) < 8:
            continue
        telegrams.append(
            {
                "msgid": req[4:8],
                "master": req[0:2],
                "slave": req[2:4],
                "sub": req[8:],
                "resp": resp,
                "count": count,
                "label": label,
            }
        )
    return telegrams


# Only telegrams ebusd could not map to a known register label
def unknown_telegrams(grab_lines: list[str]) -> list[dict]:
    return [t for t in parse_grab_lines(grab_lines) if t["label"] is None]
