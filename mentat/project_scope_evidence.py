"""Private in-process scope witnesses, never a browser or execution capability.

Only the held Linux scope issues these values. Persisted metadata is historical
evidence and cannot reconstruct a witness or prove a live kernel generation.
"""

from dataclasses import dataclass, field
import re
from types import MappingProxyType

_ISSUER = object()
_UNIT = re.compile(r"mentat-project-worker-[0-9a-f]{32}\.scope\Z")
_HEX = re.compile(r"[0-9a-f]{32}\Z")
_PLAN_KEYS = frozenset({"unit", "boot_id", "uid", "memory_bytes", "processes", "cpu_percent", "wall_seconds"})
_IDENTITY_KEYS = frozenset({"invocation", "device", "inode", "pid", "start_ticks"})


@dataclass(frozen=True, repr=False)
class ScopeWitness:
    kind: str
    _data: object = field(repr=False)
    _origin: object = field(repr=False)
    _issuer: object = field(repr=False)

    def __post_init__(self):
        if self._issuer is not _ISSUER or self.kind not in {"planned", "owned", "closed"}:
            raise ValueError("scope_witness.invalid")
        values = dict(self._data)
        expected = _PLAN_KEYS if self.kind == "planned" else _PLAN_KEYS | _IDENTITY_KEYS
        if (set(values) != expected or not isinstance(values["unit"], str)
                or _UNIT.fullmatch(values["unit"]) is None
                or not isinstance(values["boot_id"], str)
                or _HEX.fullmatch(values["boot_id"]) is None or values["boot_id"] == "0" * 32):
            raise ValueError("scope_witness.invalid")
        ceilings = {"uid": 2**31-1, "memory_bytes": 512*1024*1024,
                    "processes": 32, "cpu_percent": 100, "wall_seconds": 3600}
        for name, ceiling in ceilings.items():
            if type(values[name]) is not int or not 0 < values[name] <= ceiling:
                raise ValueError("scope_witness.invalid")
        if self.kind != "planned":
            if not isinstance(values["invocation"], str) or _HEX.fullmatch(values["invocation"]) is None:
                raise ValueError("scope_witness.invalid")
            for name in ("device", "inode", "pid", "start_ticks"):
                if type(values[name]) is not int or not 0 < values[name] < 2**63:
                    raise ValueError("scope_witness.invalid")
        object.__setattr__(self, "_data", MappingProxyType(values))

    def private_metadata(self) -> dict:
        """Copy for the private journal only; never serialize the issuer marker."""
        return dict(self._data)


def _issue(kind: str, origin: object, values: dict) -> ScopeWitness:
    return ScopeWitness(kind, values, origin, _ISSUER)


def witness_metadata(value: object, kind: str) -> dict:
    """Reject raw metadata/Booleans and witnesses for another lifecycle phase."""
    if type(value) is not ScopeWitness or value._issuer is not _ISSUER or value.kind != kind:
        raise ValueError("scope_witness.invalid")
    from mentat.project_worker_scope import LinuxWorkerScope
    if type(value._origin) is not LinuxWorkerScope:
        raise ValueError("scope_witness.invalid")
    if kind == "planned" and value._origin.journal_plan().private_metadata() != value.private_metadata():
        raise ValueError("scope_witness.invalid")
    if kind == "owned" and value._origin.journal_owned_identity().private_metadata() != value.private_metadata():
        raise ValueError("scope_witness.invalid")
    if kind == "closed" and (not value._origin._closed or value._origin._closed_witness is not value):
        raise ValueError("scope_witness.invalid")
    return value.private_metadata()
