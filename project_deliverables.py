"""Typed, bounded Project deliverables. Owner edits are separate from Agent provenance."""

from __future__ import annotations

from io import BytesIO
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit, urlunsplit
import uuid

from PIL import Image, ImageDraw, ImageFont


MAX_VERSIONS = 256
MAX_SLOT_VERSIONS = 32
MAX_CONTENT_BYTES = 64 * 1024
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
_ITEM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SLOT_ID = re.compile(r"deliverable_[0-9a-f]{32}\Z")
_VERSION_ID = re.compile(r"deliverable_version_[0-9a-f]{32}\Z")


class DeliverableError(RuntimeError):
    pass


def _fail(code: str) -> None:
    raise DeliverableError(f"deliverable.{code}")


def _text(value: object, *, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value or any(ord(char) < 32 and char not in "\n\t" for char in value):
        _fail("content_invalid")
    normalized = value.strip()
    try:
        size = len(normalized.encode("utf-8"))
    except UnicodeError:
        _fail("content_invalid")
    if size > maximum or required and not normalized:
        _fail("content_invalid")
    return normalized


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("content_invalid")
    return value


def _identifier(value: object) -> str:
    if not isinstance(value, str) or _ITEM_ID.fullmatch(value) is None:
        _fail("content_invalid")
    return value


def safe_product_url(value: object) -> str:
    """Validate an inert public HTTPS link; this function never fetches it."""
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048
            or any(ord(char) <= 32 or char in "\\<>()[]\"'" for char in value)):
        _fail("link_invalid")
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError:
        _fail("link_invalid")
    if (parts.scheme != "https" or not host or parts.username is not None or parts.password is not None
            or port not in (None, 443) or parts.fragment or host.endswith(".")):
        _fail("link_invalid")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        labels = host.lower().split(".")
        if (len(labels) < 2 or len(labels[-1]) < 2
                or labels[-1].isdigit() or labels[-1].startswith("0x")
                or any(_HOST_LABEL.fullmatch(label) is None for label in labels)):
            _fail("link_invalid")
    else:
        _fail("link_invalid")
    if host.lower().endswith((".local", ".localhost", ".localdomain", ".internal", ".test", ".invalid")):
        _fail("link_invalid")
    return urlunsplit(("https", parts.netloc.lower(), parts.path or "/", parts.query, ""))


def _record(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        _fail("content_invalid")
    return value


def _sequence(value: object, *, maximum: int) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        _fail("content_invalid")
    return value


def normalize_content(slot: str, value: object) -> dict:
    """Canonical typed content for the three garage result slots."""
    if slot == "layout":
        item = _record(value, {"width_mm", "depth_mm", "openings", "placements", "notes"})
        width = _integer(item["width_mm"], 1000, 30000)
        depth = _integer(item["depth_mm"], 1000, 30000)
        openings = []
        for raw in _sequence(item["openings"], maximum=16):
            entry = _record(raw, {"edge", "offset_mm", "width_mm", "kind"})
            edge, kind = entry["edge"], entry["kind"]
            if (not isinstance(edge, str) or edge not in {"north", "south", "east", "west"}
                    or not isinstance(kind, str) or kind not in {"door", "garage_door", "window"}):
                _fail("content_invalid")
            length = width if edge in {"north", "south"} else depth
            offset = _integer(entry["offset_mm"], 0, length)
            span = _integer(entry["width_mm"], 300, length)
            if offset + span > length:
                _fail("content_invalid")
            openings.append({"edge": edge, "offset_mm": offset, "width_mm": span, "kind": kind})
        placements = []
        ids = set()
        for raw in _sequence(item["placements"], maximum=64):
            entry = _record(raw, {"id", "kind", "label", "x_mm", "y_mm", "width_mm", "depth_mm"})
            identifier = _identifier(entry["id"])
            if (identifier in ids or not isinstance(entry["kind"], str)
                    or entry["kind"] not in {"storage", "workbench", "vehicle", "bike", "clearance", "other"}):
                _fail("content_invalid")
            ids.add(identifier)
            x = _integer(entry["x_mm"], 0, width)
            y = _integer(entry["y_mm"], 0, depth)
            item_width = _integer(entry["width_mm"], 100, width)
            item_depth = _integer(entry["depth_mm"], 100, depth)
            if x + item_width > width or y + item_depth > depth:
                _fail("content_invalid")
            placements.append({"id": identifier, "kind": entry["kind"], "label": _text(entry["label"], maximum=80, required=True),
                               "x_mm": x, "y_mm": y, "width_mm": item_width, "depth_mm": item_depth})
        normalized = {"width_mm": width, "depth_mm": depth, "openings": openings,
                      "placements": placements, "notes": _text(item["notes"], maximum=4000)}
    elif slot == "products":
        item = _record(value, {"items", "notes"})
        ids = set(); products = []
        for raw in _sequence(item["items"], maximum=50):
            entry = _record(raw, {"id", "name", "quantity", "url", "notes"})
            identifier = _identifier(entry["id"])
            if identifier in ids:
                _fail("content_invalid")
            ids.add(identifier)
            products.append({"id": identifier, "name": _text(entry["name"], maximum=120, required=True),
                             "quantity": _integer(entry["quantity"], 1, 1000),
                             "url": safe_product_url(entry["url"]),
                             "notes": _text(entry["notes"], maximum=500)})
        normalized = {"items": products, "notes": _text(item["notes"], maximum=4000)}
    elif slot == "steps":
        item = _record(value, {"steps", "notes"})
        ids = set(); steps = []
        for raw in _sequence(item["steps"], maximum=50):
            entry = _record(raw, {"id", "title", "details", "after"})
            identifier = _identifier(entry["id"])
            if identifier in ids:
                _fail("content_invalid")
            dependencies = _sequence(entry["after"], maximum=8)
            if (any(not isinstance(dependency, str) or _ITEM_ID.fullmatch(dependency) is None for dependency in dependencies)
                    or len(set(dependencies)) != len(dependencies)
                    or any(dependency not in ids for dependency in dependencies)):
                _fail("content_invalid")
            ids.add(identifier)
            steps.append({"id": identifier, "title": _text(entry["title"], maximum=120, required=True),
                          "details": _text(entry["details"], maximum=1000), "after": list(dependencies)})
        normalized = {"steps": steps, "notes": _text(item["notes"], maximum=4000)}
    else:
        _fail("slot_invalid")
    if len(canonical_content(normalized)) > MAX_CONTENT_BYTES:
        _fail("content_capacity")
    return normalized


def canonical_content(value: dict) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _fail("content_invalid")


def content_digest(value: dict) -> str:
    return hashlib.sha256(canonical_content(value)).hexdigest()


def _markdown_text(value: str) -> str:
    return "".join("\\" + character if character in "\\`*_{}[]()#+-.!|<>" else character for character in value)


def render_document(slot: str, content: dict) -> str:
    """Export owner-editable structured products/steps as inert Markdown text."""
    normalized = normalize_content(slot, content)
    if slot == "products":
        lines = ["# Garage products and sources", ""]
        for item in normalized["items"]:
            lines.append(f"- {_markdown_text(item['name'])} × {item['quantity']} — [Source]({item['url']})")
            if item["notes"]:
                lines.append(f"  {_markdown_text(item['notes'])}")
    elif slot == "steps":
        lines = ["# Garage implementation order", ""]
        for index, item in enumerate(normalized["steps"], 1):
            lines.append(f"{index}. {_markdown_text(item['title'])}")
            if item["details"]:
                lines.append(f"   {_markdown_text(item['details'])}")
            if item["after"]:
                lines.append(f"   After: {', '.join(_markdown_text(value) for value in item['after'])}")
    else:
        _fail("slot_invalid")
    if normalized["notes"]:
        lines.extend(["", "## Notes", "", _markdown_text(normalized["notes"])])
    return "\n".join(lines).rstrip() + "\n"


def render_layout_png(content: dict) -> bytes:
    """Render a bounded top-down dimension diagram from validated coordinates."""
    layout = normalize_content("layout", content)
    image = Image.new("RGB", (1200, 900), "#f6faf8")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    width = layout["width_mm"]; depth = layout["depth_mm"]
    scale = min(1000 / width, 680 / depth)
    left = round((1200 - width * scale) / 2)
    top = round((840 - depth * scale) / 2) + 30
    right = round(left + width * scale)
    bottom = round(top + depth * scale)
    draw.rectangle((left, top, right, bottom), fill="#ffffff", outline="#164e3d", width=5)
    palette = {"storage": "#a7d9c2", "workbench": "#d6bd84", "vehicle": "#a5b8c6",
               "bike": "#c9b5dd", "clearance": "#e5eee9", "other": "#cbd7d2"}
    for item in layout["placements"]:
        x0 = round(left + item["x_mm"] * scale); y0 = round(top + item["y_mm"] * scale)
        x1 = round(x0 + item["width_mm"] * scale); y1 = round(y0 + item["depth_mm"] * scale)
        draw.rectangle((x0, y0, x1, y1), fill=palette[item["kind"]], outline="#164e3d", width=2)
        draw.text((x0 + 5, y0 + 5), item["label"][:32], font=font, fill="#102a21")
    for opening in layout["openings"]:
        offset = opening["offset_mm"] * scale; span = opening["width_mm"] * scale
        if opening["edge"] == "north": points = (left + offset, top, left + offset + span, top)
        elif opening["edge"] == "south": points = (left + offset, bottom, left + offset + span, bottom)
        elif opening["edge"] == "west": points = (left, top + offset, left, top + offset + span)
        else: points = (right, top + offset, right, top + offset + span)
        draw.line(points, fill="#f6faf8", width=8)
        draw.line(points, fill="#0f766e", width=3)
    draw.text((left, max(5, top - 25)), f"Width: {width / 1000:.2f} m", font=font, fill="#164e3d")
    draw.text((left, min(875, bottom + 12)), f"Depth: {depth / 1000:.2f} m", font=font, fill="#164e3d")
    output = BytesIO(); image.save(output, format="PNG", optimize=True)
    result = output.getvalue()
    if len(result) > MAX_PREVIEW_BYTES:
        _fail("preview_capacity")
    return result


def validate_deliverable_connection(connection: sqlite3.Connection, *, require_available: bool = True) -> list[list]:
    """Validate the bounded immutable Project-owned graph in live and backup DBs."""
    projects = connection.execute(
        "SELECT id,deliverable_incarnation FROM mentat_projects",
    ).fetchmany(257)
    if len(projects) > 256:
        _fail("capacity")
    current = {}
    for identifier, incarnation in projects:
        if not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None:
            _fail("identity_invalid")
        current[identifier] = incarnation
    slots = connection.execute(
        "SELECT id,project_id,project_incarnation,slot,head_revision,created_at,retired_at "
        "FROM mentat_deliverable_slots ORDER BY id",
    ).fetchmany(MAX_VERSIONS + 1)
    versions = connection.execute(
        "SELECT id,slot_id,revision,origin,source_version_id,associated_task_id,"
        "associated_task_incarnation,content_json,content_digest,source_run_id,"
        "source_receipt_digest,source_task_id,source_task_incarnation,created_at "
        "FROM mentat_deliverable_versions ORDER BY slot_id,revision",
    ).fetchmany(MAX_VERSIONS + 1)
    files = connection.execute(
        "SELECT version_id,attachment_id,role,blob_sha256 FROM mentat_deliverable_files ORDER BY version_id,role",
    ).fetchmany(MAX_VERSIONS + 1)
    if max(len(slots), len(versions), len(files)) > MAX_VERSIONS:
        _fail("capacity")
    slot_map = {}
    for row in slots:
        identifier, project_id, incarnation, slot, head, created, retired = tuple(row)
        if (not isinstance(identifier, str) or _SLOT_ID.fullmatch(identifier) is None
                or not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None
                or slot not in {"layout", "products", "steps"}
                or type(head) is not int or not 1 <= head <= MAX_SLOT_VERSIONS
                or type(created) not in (int, float) or not math.isfinite(created) or created <= 0
                or retired is not None and (type(retired) not in (int, float) or not math.isfinite(retired) or retired < created)
                or retired is None and current.get(project_id) != incarnation
                or retired is not None and current.get(project_id) == incarnation):
            _fail("invalid")
        slot_map[identifier] = (slot, head)
    version_map = {}
    revisions = {identifier: [] for identifier in slot_map}
    for row in versions:
        (identifier, slot_id, revision, origin, source_version_id, associated_task_id,
         associated_incarnation, content_json, digest, source_run_id, source_receipt_digest,
         source_task_id, source_task_incarnation, created) = tuple(row)
        if (not isinstance(identifier, str) or _VERSION_ID.fullmatch(identifier) is None
                or slot_id not in slot_map or type(revision) is not int or not 1 <= revision <= MAX_SLOT_VERSIONS
                or origin != "owner_edit" or source_run_id is not None or source_receipt_digest is not None or source_task_id is not None
                or source_task_incarnation is not None
                or (associated_task_id is None) != (associated_incarnation is None)
                or associated_task_id is not None and (not isinstance(associated_task_id, str) or _TASK_ID.fullmatch(associated_task_id) is None)
                or associated_incarnation is not None and (not isinstance(associated_incarnation, str) or _HEX32.fullmatch(associated_incarnation) is None)
                or not isinstance(digest, str) or _HEX64.fullmatch(digest) is None
                or type(created) not in (int, float) or not math.isfinite(created) or created <= 0):
            _fail("invalid")
        if not isinstance(content_json, str):
            _fail("content_invalid")
        try:
            content = json.loads(content_json)
        except (ValueError, TypeError):
            _fail("content_invalid")
        normalized = normalize_content(slot_map[slot_id][0], content)
        if canonical_content(normalized).decode("utf-8") != content_json or content_digest(normalized) != digest:
            _fail("content_invalid")
        if source_version_id is not None:
            source = version_map.get(source_version_id)
            if source is None or source[0] != slot_id or source[1] >= revision:
                _fail("provenance_invalid")
        elif revision != 1:
            _fail("provenance_invalid")
        revisions[slot_id].append(revision)
        version_map[identifier] = (slot_id, revision, slot_map[slot_id][0])
    for slot_id, values in revisions.items():
        if not values or values != list(range(1, slot_map[slot_id][1] + 1)):
            _fail("invalid")
    file_map = {}
    for version_id, attachment_id, role, blob_sha in files:
        if (version_id not in version_map or role != "preview" or version_id in file_map
                or not isinstance(blob_sha, str) or _HEX64.fullmatch(blob_sha) is None):
            _fail("file_invalid")
        row = connection.execute(
            "SELECT a.kind,a.mime_type,a.byte_size,a.state,b.sha256,b.byte_size,b.state "
            "FROM attachments a JOIN blobs b ON b.id=a.blob_id WHERE a.id=?", (attachment_id,),
        ).fetchone()
        if (row is None or row[0] != "image" or row[1] != "image/png" or row[2] != row[5]
                or row[2] > MAX_PREVIEW_BYTES or row[4] != blob_sha
                or require_available and (row[3] != "attached" or row[6] != "ready")):
            _fail("file_invalid")
        file_map[version_id] = attachment_id
    for identifier, (_slot_id, _revision, slot) in version_map.items():
        if (slot == "layout") != (identifier in file_map):
            _fail("file_invalid")
    return [[list(row) for row in slots], [list(row) for row in versions], [list(row) for row in files],
            [[identifier, "0" * 32] for identifier in current]]


def publish_owner_edit(
    data_dir: Path, project_id: str, slot: str, content: object, *,
    expected_project_revision: int, expected_slot_revision: int,
    source_version_id: str | None = None,
    associated_task_id: str | None = None, expected_task_revision: int | None = None,
) -> dict:
    """Create one owner-authored version; no Run or Agent authority is granted."""
    from agent_console_attachments import AttachmentError, create_attachment, read_attachment_bytes, release_attachment
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from project_repository import ProjectRepository
    from task_repository import TaskRepository, _guarded_transaction, _open_repository_database

    if (type(expected_project_revision) is not int or expected_project_revision < 1
            or type(expected_slot_revision) is not int or not 0 <= expected_slot_revision < MAX_SLOT_VERSIONS
            or associated_task_id is None and expected_task_revision is not None
            or associated_task_id is not None and (type(expected_task_revision) is not int or expected_task_revision < 1)):
        _fail("revision_invalid")
    normalized = normalize_content(slot, content)
    encoded = canonical_content(normalized).decode("utf-8")
    digest = content_digest(normalized)
    preview_bytes = render_layout_png(normalized) if slot == "layout" else None
    root = Path(data_dir)
    with private_state_lock(root):
        # A stale request must not consume a staged image/blob allocation.
        # Recheck again in the write transaction after materialization.
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                project = ProjectRepository(connection).get(project_id)
                if project.revision != expected_project_revision or project.document["status"] != "active":
                    _fail("project_changed")
                current = connection.execute(
                    "SELECT s.id,s.head_revision FROM mentat_deliverable_slots s "
                    "JOIN mentat_projects p ON p.id=s.project_id AND p.deliverable_incarnation=s.project_incarnation "
                    "WHERE s.project_id=? AND s.slot=? AND s.retired_at IS NULL",
                    (project_id, slot),
                ).fetchone()
                if (current[1] if current else 0) != expected_slot_revision:
                    _fail("revision_conflict")
                if current:
                    head = connection.execute(
                        "SELECT id FROM mentat_deliverable_versions WHERE slot_id=? AND revision=?",
                        (current[0], current[1]),
                    ).fetchone()
                    if head is None or source_version_id != head[0]:
                        _fail("source_changed")
                elif source_version_id is not None:
                    _fail("source_changed")
                if associated_task_id is not None:
                    task = TaskRepository(connection).get(associated_task_id)
                    if task.revision != expected_task_revision or task.document.get("project_id") != project_id:
                        _fail("task_changed")
                if connection.execute("SELECT COUNT(*) FROM mentat_deliverable_versions").fetchone()[0] >= MAX_VERSIONS:
                    _fail("capacity")
                validate_project_context_connection(connection, require_available=False)
        staged = create_attachment(root, original_name="garage-layout.png", content=preview_bytes,
                                   content_type="image/png", image_max_bytes=MAX_PREVIEW_BYTES) if preview_bytes is not None else None
        try:
            with _open_repository_database(root) as (connection, guard):
                with _guarded_transaction(connection, guard, immediate=True):
                    projects = ProjectRepository(connection)
                    projects.authority_receipt(required=True)
                    project = projects.get(project_id)
                    if project.revision != expected_project_revision or project.document["status"] != "active":
                        _fail("project_changed")
                    incarnation_row = connection.execute(
                        "SELECT deliverable_incarnation FROM mentat_projects WHERE id=?", (project_id,),
                    ).fetchone()
                    incarnation = incarnation_row[0] if incarnation_row else None
                    if not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None:
                        _fail("project_unavailable")
                    task_incarnation = None
                    if associated_task_id is not None:
                        task = TaskRepository(connection).get(associated_task_id)
                        if task.revision != expected_task_revision or task.document.get("project_id") != project_id:
                            _fail("task_changed")
                        row = connection.execute("SELECT input_incarnation FROM mentat_tasks WHERE id=?", (associated_task_id,)).fetchone()
                        task_incarnation = row[0] if row else None
                        if not isinstance(task_incarnation, str) or _HEX32.fullmatch(task_incarnation) is None:
                            _fail("task_changed")
                    validate_project_context_connection(connection, require_available=False)
                    current = connection.execute(
                        "SELECT id,head_revision FROM mentat_deliverable_slots "
                        "WHERE project_id=? AND project_incarnation=? AND slot=? AND retired_at IS NULL",
                        (project_id, incarnation, slot),
                    ).fetchone()
                    if (current[1] if current else 0) != expected_slot_revision:
                        _fail("revision_conflict")
                    if current:
                        head = connection.execute(
                            "SELECT id FROM mentat_deliverable_versions WHERE slot_id=? AND revision=?",
                            (current[0], current[1]),
                        ).fetchone()
                        if head is None or source_version_id != head[0]:
                            _fail("source_changed")
                    elif source_version_id is not None:
                        _fail("source_changed")
                    if connection.execute("SELECT COUNT(*) FROM mentat_deliverable_versions").fetchone()[0] >= MAX_VERSIONS:
                        _fail("capacity")
                    now = time.time()
                    slot_id = current[0] if current else f"deliverable_{uuid.uuid4().hex}"
                    revision = expected_slot_revision + 1
                    if current:
                        connection.execute("UPDATE mentat_deliverable_slots SET head_revision=? WHERE id=?", (revision, slot_id))
                    else:
                        connection.execute(
                            "INSERT INTO mentat_deliverable_slots VALUES(?,?,?,?,?,?,NULL)",
                            (slot_id, project_id, incarnation, slot, revision, now),
                        )
                    version_id = f"deliverable_version_{uuid.uuid4().hex}"
                    connection.execute(
                    "INSERT INTO mentat_deliverable_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (version_id, slot_id, revision, "owner_edit", source_version_id,
                     associated_task_id, task_incarnation, encoded, digest, None, None, None, None, now),
                    )
                    if staged is not None:
                        identifier = staged["id"]
                        metadata, actual = read_attachment_bytes(root, identifier)
                        if (actual != preview_bytes or metadata["kind"] != "image" or metadata["mime_type"] != "image/png"):
                            _fail("preview_unavailable")
                        blob = connection.execute(
                            "SELECT b.sha256 FROM attachments a JOIN blobs b ON b.id=a.blob_id "
                            "WHERE a.id=? AND a.state='staged' AND b.state='ready' AND a.expires_at>?",
                            (identifier, now),
                        ).fetchone()
                        if blob is None:
                            _fail("preview_unavailable")
                        connection.execute(
                            "INSERT INTO mentat_deliverable_files VALUES(?,?,?,?)",
                            (version_id, identifier, "preview", blob[0]),
                        )
                        connection.execute(
                            "UPDATE attachments SET state='attached',expires_at=NULL,delete_after=NULL,updated_at=? WHERE id=?",
                            (now, identifier),
                        )
                    validate_project_context_connection(connection, require_available=False)
                    return {"slot": slot, "slot_id": slot_id, "version_id": version_id, "revision": revision,
                            "origin": "owner_edit", "content_digest": digest,
                            "preview_attachment_id": staged["id"] if staged else None}
        except Exception:
            if staged is not None:
                try:
                    release_attachment(root, staged["id"], grace_seconds=0)
                except (AttachmentError, OSError, sqlite3.Error):
                    pass
            raise


def read_project_deliverables(data_dir: Path, project_id: str) -> dict:
    """Return only owner-safe typed versions and opaque preview IDs."""
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from project_repository import ProjectRepository
    from task_repository import _guarded_transaction, _open_repository_database

    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                project = ProjectRepository(connection).get(project_id)
                validate_project_context_connection(connection, require_available=False)
                row = connection.execute(
                    "SELECT deliverable_incarnation FROM mentat_projects WHERE id=?", (project_id,),
                ).fetchone()
                incarnation = row[0] if row else None
                slots = []
                for slot_id, kind, head in connection.execute(
                    "SELECT id,slot,head_revision FROM mentat_deliverable_slots "
                    "WHERE project_id=? AND project_incarnation=? AND retired_at IS NULL ORDER BY slot",
                    (project_id, incarnation),
                ):
                    versions = []
                    for version_id, revision, origin, source_id, content_json, created in connection.execute(
                        "SELECT id,revision,origin,source_version_id,content_json,created_at "
                        "FROM mentat_deliverable_versions WHERE slot_id=? ORDER BY revision DESC LIMIT ?",
                        (slot_id, MAX_SLOT_VERSIONS),
                    ):
                        preview = connection.execute(
                            "SELECT attachment_id FROM mentat_deliverable_files WHERE version_id=? AND role='preview'",
                            (version_id,),
                        ).fetchone()
                        versions.append({"id": version_id, "revision": revision, "origin": origin,
                                         "source_version_id": source_id,
                                         "content": json.loads(content_json) if revision == head else None,
                                         "created_at": created,
                                         "preview_attachment_id": preview[0] if preview else None})
                    slots.append({"id": slot_id, "slot": kind, "head_revision": head, "versions": versions})
                return {"project": {"id": project_id, "name": project.document["name"],
                                    "revision": project.revision, "status": project.document["status"]},
                        "slots": slots}


def read_deliverable_version(data_dir: Path, project_id: str, version_id: str) -> dict:
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from project_repository import ProjectRepository
    from task_repository import _guarded_transaction, _open_repository_database

    if not isinstance(version_id, str) or _VERSION_ID.fullmatch(version_id) is None:
        _fail("version_unavailable")
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                ProjectRepository(connection).get(project_id)
                validate_project_context_connection(connection, require_available=False)
                row = connection.execute(
                    "SELECT s.slot,v.revision,v.origin,v.source_version_id,v.content_json,v.created_at "
                    "FROM mentat_deliverable_versions v JOIN mentat_deliverable_slots s ON s.id=v.slot_id "
                    "JOIN mentat_projects p ON p.id=s.project_id AND p.deliverable_incarnation=s.project_incarnation "
                    "WHERE v.id=? AND s.project_id=? AND s.retired_at IS NULL", (version_id, project_id),
                ).fetchone()
                if row is None:
                    _fail("version_unavailable")
                preview = connection.execute(
                    "SELECT attachment_id FROM mentat_deliverable_files WHERE version_id=? AND role='preview'",
                    (version_id,),
                ).fetchone()
                return {"id": version_id, "project_id": project_id, "slot": row[0], "revision": row[1],
                        "origin": row[2], "source_version_id": row[3], "content": json.loads(row[4]),
                        "created_at": row[5], "preview_attachment_id": preview[0] if preview else None}


def read_retired_deliverable_history(data_dir: Path) -> list[dict]:
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from task_repository import _guarded_transaction, _open_repository_database

    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                validate_project_context_connection(connection, require_available=False)
                return [{"id": row[0], "project_id": row[1], "slot": row[2],
                         "revision": row[3], "origin": row[4], "created_at": row[5]}
                        for row in connection.execute(
                            "SELECT v.id,s.project_id,s.slot,v.revision,v.origin,v.created_at "
                            "FROM mentat_deliverable_slots s JOIN mentat_deliverable_versions v ON v.slot_id=s.id "
                            "WHERE s.retired_at IS NOT NULL ORDER BY s.retired_at DESC,v.created_at DESC LIMIT 50"
                        )]


def read_retired_deliverable_version(data_dir: Path, version_id: str) -> dict:
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from task_repository import _guarded_transaction, _open_repository_database

    if not isinstance(version_id, str) or _VERSION_ID.fullmatch(version_id) is None:
        _fail("version_unavailable")
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                validate_project_context_connection(connection, require_available=False)
                row = connection.execute(
                    "SELECT s.project_id,s.slot,v.revision,v.origin,v.source_version_id,v.content_json,v.created_at "
                    "FROM mentat_deliverable_versions v JOIN mentat_deliverable_slots s ON s.id=v.slot_id "
                    "WHERE v.id=? AND s.retired_at IS NOT NULL", (version_id,),
                ).fetchone()
                if row is None:
                    _fail("version_unavailable")
                preview = connection.execute(
                    "SELECT attachment_id FROM mentat_deliverable_files WHERE version_id=? AND role='preview'",
                    (version_id,),
                ).fetchone()
                return {"id": version_id, "project_id": row[0], "slot": row[1], "revision": row[2],
                        "origin": row[3], "source_version_id": row[4], "content": json.loads(row[5]),
                        "created_at": row[6], "preview_attachment_id": preview[0] if preview else None}


def read_deliverable_preview(data_dir: Path, version_id: str) -> bytes:
    """Read only the PNG bound to an exact current or retired layout version."""
    from agent_console_attachments import read_attachment_bytes
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from task_repository import _guarded_transaction, _open_repository_database

    if not isinstance(version_id, str) or _VERSION_ID.fullmatch(version_id) is None:
        _fail("version_unavailable")
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                validate_project_context_connection(connection, require_available=False)
                row = connection.execute(
                    "SELECT f.attachment_id,f.blob_sha256 FROM mentat_deliverable_files f "
                    "JOIN mentat_deliverable_versions v ON v.id=f.version_id "
                    "JOIN mentat_deliverable_slots s ON s.id=v.slot_id "
                    "WHERE f.version_id=? AND f.role='preview' AND s.slot='layout'", (version_id,),
                ).fetchone()
                if row is None:
                    _fail("version_unavailable")
                metadata, content = read_attachment_bytes(root, row[0])
                if (metadata["kind"] != "image" or metadata["mime_type"] != "image/png"
                        or hashlib.sha256(content).hexdigest() != row[1]
                        or len(content) > MAX_PREVIEW_BYTES):
                    _fail("preview_unavailable")
                return content
