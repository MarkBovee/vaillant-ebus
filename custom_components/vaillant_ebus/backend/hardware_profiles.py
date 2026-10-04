"""Hardware/firmware profiles that gate hardware-specific definitions and reads.

Each profile names one scan identity (device ID, firmware, hardware revision) and carries the
evidence that justifies it. Gates elsewhere ask a profile instead of repeating literal
``scan_sw == "0407"`` conditions. Adding a revision means adding one row here, with a capture,
a plausibility check and a gate test (see docs/register-discovery.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import DeviceGraph, DeviceNode, ScanIdentity


@dataclass(frozen=True)
class HardwareProfile:
    """One scan identity a hardware-specific definition or read is allowed for."""

    name: str
    scan_type: str
    device_type: str = ""
    sw: frozenset[str] = frozenset()
    hw: frozenset[str] = frozenset()
    scan_address: str = ""
    prefix_match: bool = False
    evidence: str = ""

    def matches_scan(self, scan_type: str, scan_sw: str, scan_hw: str) -> bool:
        """Return whether a scan identity (type, firmware, hardware) is covered by this profile."""
        kind = scan_type.casefold()
        if self.prefix_match:
            if not kind.startswith(self.scan_type):
                return False
        elif kind != self.scan_type:
            return False
        if self.sw and scan_sw not in self.sw:
            return False
        return not self.hw or scan_hw in self.hw


# Intent: the single table of firmware/hardware gates; evidence names the capture or upstream thread.
# Why: gates were scattered literals; one table makes the supported matrix reviewable and testable.
HMUX0_SW0407 = HardwareProfile(
    name="hmux0_sw0407",
    scan_type="hmux0",
    device_type="HEAT_PUMP",
    sw=frozenset({"0407"}),
    hw=frozenset({"0504"}),
    evidence="community captures (5 fixtures); map probes unavailable, passive B509/B51A/B516/B511 set",
)
# SW0303 needs the runtime define for RunDataFlowTemp/RunDataReturnTemp (issue #171, live-confirmed).
HMUX0_SW0303 = HardwareProfile(
    name="hmux0_sw0303", scan_type="hmux0", sw=frozenset({"0303"}), hw=frozenset({"0504"}), evidence="issue #171"
)
# SW0303 and SW0406 decode precise (1/16 degC) flow/return temperatures; other revisions returned absurd values (#99).
HMUX0_PRECISE_TEMPERATURE = HardwareProfile(
    name="hmux0_precise_temperature",
    scan_type="hmux0",
    sw=frozenset({"0303", "0406"}),
    hw=frozenset({"0504"}),
    evidence="issue #171 (SW0303 live, SW0406 27.3125 read); issue #99 for the excluded revisions",
)
# B509 monitoring block (compressor speed, building pump power, electrical power): evidence for 0302 and 0303.
HMUX0_B509_MONITORING = HardwareProfile(
    name="hmux0_b509_monitoring",
    scan_type="hmux0",
    sw=frozenset({"0302", "0303"}),
    hw=frozenset({"0504"}),
    evidence="upstream issue #522; community captures",
)
VWZIO_SW0500 = HardwareProfile(
    name="vwzio_sw0500",
    scan_type="vwzio",
    device_type="PASSIVE_COOLING",
    sw=frozenset({"0500"}),
    hw=frozenset({"0504"}),
    scan_address="scan.76",
    evidence="issue #161 capture; passive B516/14 and B511/1802 frames, active Status01 only documented for HW5103",
)
# Any VWZ-family station at slave 0x76: generic Status01 definitions embed that address.
VWZ_STATION_76 = HardwareProfile(
    name="vwz_station_76",
    scan_type="vwz",
    device_type="PASSIVE_COOLING",
    scan_address="scan.76",
    prefix_match=True,
    evidence="upstream PR #598",
)
# HW5103 heat pumps answer b511/07 with the Status07 layout (upstream ebusd-configuration PR #614).
HMU00_HW5103 = HardwareProfile(
    name="hmu00_hw5103", scan_type="hmu00", hw=frozenset({"5103"}), evidence="upstream PR #614"
)


# Intent: return a node's identity check against a profile, including node type and scan address.
# Why: a name or firmware match alone must not authorise a definition on the wrong device role.
def node_matches(profile: HardwareProfile, node: DeviceNode) -> bool:
    if profile.device_type and node.device_type.name != profile.device_type:
        return False
    if profile.scan_address and node.scan_address.casefold() != profile.scan_address:
        return False
    return profile.matches_scan(node.scan_type, node.scan_sw, node.scan_hw)


# Intent: return the one circuit that matches a profile with a current, unique scan identity.
# Why: ambiguous or stale scan evidence must fail closed instead of picking a circuit.
def profile_owner(graph: DeviceGraph | None, profile: HardwareProfile) -> str | None:
    if graph is None:
        return None
    matches = [
        node
        for node in graph.nodes.values()
        if node_matches(profile, node) and has_current_unique_scan_identity(graph, node)
    ]
    return matches[0].circuit if len(matches) == 1 else None


# Intent: whether a complete scan row is covered by a profile (used where the owner comes from scan rows).
# Why: HMUX0 ownership is resolved from scan rows, so the firmware check must share the profile table.
def scan_matches(profile: HardwareProfile, scan: ScanIdentity) -> bool:
    return scan.complete and profile.matches_scan(scan.scan_type, scan.scan_sw, scan.scan_hw)


# Intent: verify that a device node still matches exactly one current scan identity.
# Why: cached node metadata cannot authorize bus traffic after scans conflict or disappear.
def has_current_unique_scan_identity(graph: DeviceGraph, node: DeviceNode) -> bool:
    address = node.scan_address.casefold()
    scan_type = node.scan_type.casefold()
    if not address or not scan_type:
        return False
    if any(
        not row.complete and (row.address.casefold() == address or row.scan_type.casefold() == scan_type)
        for row in graph.scan_identities
    ):
        return False

    grouped: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for row in graph.scan_identities:
        grouped.setdefault((row.address.casefold(), row.scan_type.casefold()), []).append(
            (row.scan_sw.casefold(), row.scan_hw.casefold())
        )

    normalized: list[tuple[str, str, str, str]] = []
    conflicting_addresses: set[str] = set()
    conflicting_types: set[str] = set()
    for (row_address, row_type), identities in grouped.items():
        software = {sw for sw, _ in identities if sw}
        hardware = {hw for _, hw in identities if hw}
        if len(software) > 1 or len(hardware) > 1:
            conflicting_addresses.add(row_address)
            conflicting_types.add(row_type)
            continue
        normalized.append((row_address, row_type, next(iter(software), ""), next(iter(hardware), "")))

    if address in conflicting_addresses or scan_type in conflicting_types:
        return False
    matching = [row for row in normalized if row[:2] == (address, scan_type)]
    if len(matching) != 1:
        return False
    if sum(row[1] == scan_type for row in normalized) != 1:
        return False
    if sum(row[0] == address for row in normalized) != 1:
        return False
    _, _, scan_sw, scan_hw = matching[0]
    return scan_sw == node.scan_sw.casefold() and scan_hw == node.scan_hw.casefold()
