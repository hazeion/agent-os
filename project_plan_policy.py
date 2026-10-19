"""Bounded immutable Project-plan intent; never an execution grant."""

from __future__ import annotations

import re


MAX_POLICY_CONTENT_BYTES = 24 * 1024
OPERATIONS = frozenset({
    "ask_owner", "read_public_web", "read_selected_inputs", "write_registered_artifacts",
})
USES = frozenset({"read_registered_input", "cite_public_source"})
SLOT_TYPES = frozenset({"diagram", "document", "checklist", "research"})
FINAL_TYPES = {"layout": "diagram", "products": "document", "steps": "checklist"}
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_INTERMEDIATE = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class PlanPolicyError(ValueError):
    pass


def _reject() -> None:
    raise PlanPolicyError("project_plan.invalid")


def _integer(value: object, lower: int, upper: int) -> int:
    if type(value) is not int or not lower <= value <= upper:
        _reject()
    return value


def normalize_policy(value: object, nodes: list[dict], *, stored: bool) -> dict:
    """Check exact shape and static cross-fields against one ordered plan graph.

    Stored policy includes server-frozen public-brief digests. The public
    request cannot choose or overwrite those digests.
    """
    expected = {"operations", "outputs", "transfers", "ceilings"}
    if stored:
        expected.add("public_briefs")
    if not isinstance(value, dict) or set(value) != expected:
        _reject()
    raw_operations = value["operations"]
    if not isinstance(raw_operations, list) or len(raw_operations) != len(nodes):
        _reject()
    operations: list[list[str]] = []
    for raw in raw_operations:
        if (not isinstance(raw, list) or not raw or len(raw) > len(OPERATIONS)
                or any(not isinstance(item, str) or item not in OPERATIONS for item in raw)
                or raw != sorted(set(raw))
                or "read_public_web" in raw and ("read_selected_inputs" in raw or "ask_owner" in raw)):
            _reject()
        operations.append(list(raw))

    raw_outputs = value["outputs"]
    if not isinstance(raw_outputs, list) or len(raw_outputs) > 11:
        _reject()
    outputs: list[dict] = []
    slots: dict[str, dict] = {}
    total_output_bytes = 0
    final_count = intermediate_count = 0
    for raw in raw_outputs:
        if not isinstance(raw, dict) or set(raw) != {"slot", "kind", "type", "producer", "max_bytes", "owner_review"}:
            _reject()
        slot, kind, artifact_type = raw["slot"], raw["kind"], raw["type"]
        if (not isinstance(slot, str) or slot in slots or not isinstance(kind, str)
                or kind not in {"final", "intermediate"} or not isinstance(artifact_type, str)):
            _reject()
        if kind == "final":
            if slot not in FINAL_TYPES or artifact_type != FINAL_TYPES[slot]:
                _reject()
            final_count += 1
        else:
            if _INTERMEDIATE.fullmatch(slot) is None or slot in FINAL_TYPES or artifact_type not in SLOT_TYPES:
                _reject()
            intermediate_count += 1
        producer = _integer(raw["producer"], 0, len(nodes) - 1)
        byte_limit = _integer(raw["max_bytes"], 1, 2 * 1024 * 1024)
        if (type(raw["owner_review"]) is not bool
                or "write_registered_artifacts" not in operations[producer]
                or "read_public_web" in operations[producer] and not raw["owner_review"]):
            _reject()
        total_output_bytes += byte_limit
        output = {"slot": slot, "kind": kind, "type": artifact_type, "producer": producer,
                  "max_bytes": byte_limit, "owner_review": raw["owner_review"]}
        outputs.append(output)
        slots[slot] = output
    if final_count > 3 or intermediate_count > 8 or total_output_bytes > MAX_OUTPUT_BYTES:
        _reject()

    raw_transfers = value["transfers"]
    if not isinstance(raw_transfers, list) or len(raw_transfers) > 64:
        _reject()
    transfers: list[dict] = []
    seen_transfers: set[tuple[int, int, tuple[str, ...]]] = set()
    for raw in raw_transfers:
        if not isinstance(raw, dict) or set(raw) != {"producer", "consumer", "slots", "use", "max_files", "max_bytes", "segment"}:
            _reject()
        producer = _integer(raw["producer"], 0, len(nodes) - 1)
        consumer = _integer(raw["consumer"], producer + 1, len(nodes) - 1)
        names = raw["slots"]
        if (not isinstance(names, list) or not names or len(names) > 11
                or any(not isinstance(name, str) or name not in slots for name in names)
                or names != sorted(set(names))
                or any(slots[name]["producer"] != producer for name in names)
                or nodes[producer]["task_id"] not in nodes[consumer]["after"]
                or "read_public_web" in operations[producer]
                   and nodes[producer]["segment"] >= nodes[consumer]["segment"]
                or "read_public_web" in operations[consumer]
                or "read_selected_inputs" not in operations[consumer]
                or not isinstance(raw["use"], str) or raw["use"] not in USES):
            _reject()
        if raw["use"] == "cite_public_source" and (
                "read_public_web" not in operations[producer]
                or any(slots[name]["type"] != "research" for name in names)):
            _reject()
        max_files = _integer(raw["max_files"], 1, 8)
        max_bytes = _integer(raw["max_bytes"], 1, MAX_OUTPUT_BYTES)
        segment = _integer(raw["segment"], 0, len(nodes) - 1)
        if (segment != nodes[consumer]["segment"] or max_files < len(names)
                or max_bytes > sum(slots[name]["max_bytes"] for name in names)):
            _reject()
        key = (producer, consumer, tuple(names))
        if key in seen_transfers:
            _reject()
        seen_transfers.add(key)
        transfers.append({"producer": producer, "consumer": consumer, "slots": list(names),
                          "use": raw["use"], "max_files": max_files,
                          "max_bytes": max_bytes, "segment": segment})

    ceilings = value["ceilings"]
    if not isinstance(ceilings, dict) or set(ceilings) != {"max_attempts", "max_wall_seconds", "max_work_units"}:
        _reject()
    attempts = _integer(ceilings["max_attempts"], 1, 96)
    wall = _integer(ceilings["max_wall_seconds"], 60, 604800)
    work = _integer(ceilings["max_work_units"], 1, 32000)
    if (sum(node["max_attempts"] for node in nodes) > attempts
            or sum(node["max_attempts"] * node["max_wall_seconds"] for node in nodes) > wall
            or sum(node["max_attempts"] * node["max_work_units"] for node in nodes) > work):
        _reject()

    result = {"operations": operations, "outputs": outputs, "transfers": transfers,
              "ceilings": {"max_attempts": attempts, "max_wall_seconds": wall, "max_work_units": work}}
    if stored:
        raw_briefs = value["public_briefs"]
        if not isinstance(raw_briefs, list):
            _reject()
        briefs: list[dict] = []
        seen_briefs: set[int] = set()
        for raw in raw_briefs:
            if not isinstance(raw, dict) or set(raw) != {"node", "digest"}:
                _reject()
            index = _integer(raw["node"], 0, len(nodes) - 1)
            digest = raw["digest"]
            if (index in seen_briefs or "read_public_web" not in operations[index]
                    or not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None):
                _reject()
            seen_briefs.add(index)
            briefs.append({"node": index, "digest": digest})
        if (seen_briefs != {index for index, declared in enumerate(operations) if "read_public_web" in declared}
                or briefs != sorted(briefs, key=lambda item: item["node"])):
            _reject()
        result["public_briefs"] = briefs
    return result
