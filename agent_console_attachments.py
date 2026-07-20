"""Private attachment storage for Mentat's Agent Console.

The browser-facing contract uses opaque attachment identifiers.  Local blob
paths are available only through :func:`resolve_blob_path` for trusted server
adapters such as the fixed Hermes image argument.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Collection

from mentat_db import (
    connect,
    ensure_private_console_dir,
    ensure_private_runtime_dir,
    transaction,
)
from private_state import synchronized_private_state


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
DEFAULT_STAGED_TTL = 2 * 60 * 60
DEFAULT_ORPHAN_GRACE = 60 * 60
UPLOAD_MAX_AGE = 15 * 60
FILESYSTEM_ORPHAN_MIN_AGE = 24 * 60 * 60
DEFAULT_GC_BATCH = 100
DELETE_RETRY_BASE = 30
DELETE_RETRY_MAX = 60 * 60

ATTACHMENT_STATES = frozenset({
    "uploading",
    "staged",
    "attached",
    "orphaned",
    "pending_delete",
    "deleting",
    "missing",
})
AVAILABLE_STATES = frozenset({"staged", "attached"})

_ID_PATTERN = re.compile(r"attachment_[0-9a-f]{32}\Z")
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_NAME_PATTERN = re.compile(
    r"(?i)(^|[._-])(\.env|id_rsa|id_ed25519|credentials?|secrets?|tokens?|auth)([._-]|$)"
)
_SECRET_EXTENSIONS = frozenset({".key", ".pem", ".p12", ".pfx", ".jks", ".keystore"})
_BLOCKED_EXTENSIONS = frozenset({
    ".7z", ".apk", ".app", ".bat", ".bin", ".bz2", ".cmd", ".com",
    ".dll", ".dmg", ".exe", ".gz", ".iso", ".jar", ".msi", ".rar",
    ".sh", ".so", ".svg", ".tar", ".tgz", ".vbs", ".xz", ".zip",
})

_IMAGE_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_TEXT_EXTENSIONS = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".py": "text/x-python",
    ".pyi": "text/x-python",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".cjs": "text/javascript",
    ".ts": "text/typescript",
    ".tsx": "text/typescript",
    ".jsx": "text/javascript",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".css": "text/css",
    ".html": "text/html",
    ".htm": "text/html",
    ".xml": "application/xml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".toml": "application/toml",
    ".ini": "text/plain",
    ".cfg": "text/plain",
    ".conf": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".sql": "application/sql",
    ".c": "text/x-c",
    ".h": "text/x-c",
    ".cc": "text/x-c++",
    ".cpp": "text/x-c++",
    ".hpp": "text/x-c++",
    ".java": "text/x-java-source",
    ".go": "text/x-go",
    ".rs": "text/x-rust",
    ".rb": "text/x-ruby",
    ".php": "text/x-php",
    ".swift": "text/x-swift",
    ".kt": "text/x-kotlin",
    ".kts": "text/x-kotlin",
    ".cs": "text/x-csharp",
    ".vue": "text/plain",
    ".svelte": "text/plain",
    ".graphql": "text/plain",
    ".gql": "text/plain",
    ".log": "text/plain",
    ".diff": "text/x-diff",
    ".patch": "text/x-diff",
}

_TEXT_CONTENT_TYPES = frozenset(_TEXT_EXTENSIONS.values()) | {
    "text/plain",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-javascript",
    "application/yaml",
    "application/toml",
    "application/sql",
    "application/x-ndjson",
}

_PRIVATE_KEY_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
)
_TOKEN_PATTERN = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    rb"(?im)^\s*(?:api[_-]?key|access[_-]?token|password|secret|credential|authorization)"
    rb"\s*[:=]\s*['\"]?([A-Za-z0-9_./+=-]{16,})"
)


class AttachmentError(RuntimeError):
    """Base error for safe attachment operations."""


class AttachmentValidationError(AttachmentError):
    """The supplied attachment is unsupported or unsafe."""


class AttachmentNotFound(AttachmentError):
    """The opaque attachment identifier does not exist."""


class AttachmentUnavailable(AttachmentError):
    """The attachment exists but is expired, deleting, or missing."""


class AttachmentStorageError(AttachmentError):
    """The private storage boundary is unsafe or unavailable."""


def _timestamp(value: float | None = None) -> float:
    return float(time.time() if value is None else value)


def _iso(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_attachment_id(value: str) -> str:
    text = str(value or "")
    if not _ID_PATTERN.fullmatch(text):
        raise AttachmentNotFound("Attachment not found")
    return text


def _validate_run_id(value: str) -> str:
    text = str(value or "")
    if not _RUN_ID_PATTERN.fullmatch(text):
        raise AttachmentValidationError("Invalid Agent Console run identifier")
    return text


def _normalize_name(value: str) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 255 or _CONTROL_PATTERN.search(name):
        raise AttachmentValidationError("Attachment filename is invalid")
    if name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
        raise AttachmentValidationError("Attachment filename must not contain a path")
    lower = name.lower()
    extension = Path(lower).suffix
    if extension in _SECRET_EXTENSIONS or _SECRET_NAME_PATTERN.search(lower):
        raise AttachmentValidationError("Credential and secret files cannot be attached")
    if extension in _BLOCKED_EXTENSIONS:
        raise AttachmentValidationError("Executable, archive, and SVG files cannot be attached")
    return name


def _normalized_content_type(value: str | None) -> str | None:
    if value is None:
        return None
    content_type = str(value).split(";", 1)[0].strip().lower()
    if not content_type or len(content_type) > 100:
        return None
    return content_type


def _expected_kind(name: str, content_type: str | None) -> str:
    extension = Path(name.lower()).suffix
    if extension in _IMAGE_EXTENSIONS or (content_type or "").startswith("image/"):
        return "image"
    return "text"


def _detect_image(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _has_blocked_magic(data: bytes) -> bool:
    signatures = (
        b"MZ", b"\x7fELF", b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08",
        b"\x1f\x8b", b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c", b"BZh",
        b"\xfd7zXZ\x00", b"%PDF-",
    )
    if any(data.startswith(signature) for signature in signatures):
        return True
    if len(data) >= 4 and data[:4] in {
        b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
    }:
        return True
    return False


def _looks_like_svg(data: bytes) -> bool:
    prefix = data[:4096].lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    return prefix.startswith(b"<svg") or (prefix.startswith(b"<?xml") and b"<svg" in prefix)


def _validate_content(name: str, data: bytes, supplied_type: str | None) -> tuple[str, str]:
    if not data:
        raise AttachmentValidationError("Empty files cannot be attached")
    extension = Path(name.lower()).suffix
    if _looks_like_svg(data) or supplied_type == "image/svg+xml":
        raise AttachmentValidationError("SVG files cannot be attached")
    if _has_blocked_magic(data):
        raise AttachmentValidationError("Executable, archive, and unsupported binary files cannot be attached")

    image_type = _detect_image(data)
    if image_type:
        expected = _IMAGE_EXTENSIONS.get(extension)
        if expected is None or expected != image_type:
            raise AttachmentValidationError("Image content does not match its filename")
        if supplied_type and supplied_type not in {image_type, "application/octet-stream"}:
            raise AttachmentValidationError("Image content does not match its declared type")
        if len(data) > MAX_IMAGE_BYTES:
            raise AttachmentValidationError("Image exceeds the 10 MB limit")
        return "image", image_type

    if extension not in _TEXT_EXTENSIONS:
        raise AttachmentValidationError("This text or code file type is not supported")
    if supplied_type and not (
        supplied_type in _TEXT_CONTENT_TYPES
        or supplied_type.startswith("text/")
        or supplied_type == "application/octet-stream"
    ):
        raise AttachmentValidationError("File content does not match its declared type")
    if len(data) > MAX_TEXT_BYTES:
        raise AttachmentValidationError("Text and code files are limited to 2 MB")
    if b"\x00" in data:
        raise AttachmentValidationError("Binary files cannot be attached as text")
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AttachmentValidationError("Text and code files must use UTF-8") from exc
    if (
        any(marker in data for marker in _PRIVATE_KEY_MARKERS)
        or _TOKEN_PATTERN.search(data)
        or _SECRET_ASSIGNMENT_PATTERN.search(data)
    ):
        raise AttachmentValidationError("Files containing recognizable credentials cannot be attached")
    return "text", _TEXT_EXTENSIONS[extension]


def _blobs_root(data_dir: Path) -> Path:
    private = ensure_private_console_dir(data_dir)
    root = private / "blobs" / "sha256"
    cursor = private
    for part in ("blobs", "sha256"):
        cursor = cursor / part
        if cursor.is_symlink():
            raise AttachmentStorageError("Attachment blob directory must not be a symlink")
        cursor.mkdir(mode=0o700, exist_ok=True)
        if cursor.resolve(strict=True).parent != cursor.parent.resolve(strict=True):
            raise AttachmentStorageError("Attachment blob directory escapes durable private storage")
        if os.name != "nt":
            cursor.chmod(0o700, follow_symlinks=False)
    return root.resolve(strict=True)


def _uploads_root(data_dir: Path) -> Path:
    runtime = ensure_private_runtime_dir(data_dir)
    root = runtime / "uploads"
    if root.is_symlink():
        raise AttachmentStorageError("Attachment upload directory must not be a symlink")
    root.mkdir(mode=0o700, exist_ok=True)
    if root.resolve(strict=True).parent != runtime:
        raise AttachmentStorageError("Attachment upload directory escapes private runtime storage")
    if os.name != "nt":
        root.chmod(0o700, follow_symlinks=False)
    return root.resolve(strict=True)


def _safe_blob_path(root: Path, storage_key: str, *, require_exists: bool) -> Path:
    parts = Path(str(storage_key)).parts
    if len(parts) != 2 or parts[0] in {"", ".", ".."} or not _SHA256_PATTERN.fullmatch(parts[1]):
        raise AttachmentStorageError("Attachment storage key is invalid")
    if parts[0] != parts[1][:2]:
        raise AttachmentStorageError("Attachment storage key is invalid")
    parent = root / parts[0]
    if parent.is_symlink():
        raise AttachmentStorageError("Attachment blob path is unsafe")
    if not parent.exists() and not require_exists:
        parent.mkdir(mode=0o700, exist_ok=True)
        if parent.is_symlink() or not parent.is_dir() or parent.resolve(strict=True).parent != root:
            raise AttachmentStorageError("Attachment blob path is unsafe")
        if os.name != "nt":
            parent.chmod(0o700, follow_symlinks=False)
    path = parent / parts[1]
    if path.is_symlink():
        raise AttachmentStorageError("Attachment blob path is unsafe")
    if require_exists:
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode):
            raise AttachmentStorageError("Attachment blob is not a regular file")
        if path.resolve(strict=True).parent != parent.resolve(strict=True):
            raise AttachmentStorageError("Attachment blob escapes private storage")
    return path


def _verify_blob_bytes(path: Path, *, expected_sha256: str, expected_size: int) -> None:
    if path.is_symlink():
        raise AttachmentStorageError("Attachment blob path is unsafe")
    try:
        details = path.lstat()
    except FileNotFoundError as exc:
        raise AttachmentStorageError("Attachment blob promotion did not complete") from exc
    if not stat.S_ISREG(details.st_mode) or details.st_size != expected_size:
        raise AttachmentStorageError("Existing attachment blob does not match uploaded content")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise AttachmentStorageError("Existing attachment blob does not match uploaded content")


def _promote_blob(upload_path: Path, blob_path: Path, *, sha256: str, byte_size: int) -> None:
    """Publish a blob without ever replacing pre-existing path content."""
    if blob_path.exists():
        _verify_blob_bytes(blob_path, expected_sha256=sha256, expected_size=byte_size)
        upload_path.unlink(missing_ok=True)
        return
    try:
        os.link(upload_path, blob_path)
    except FileExistsError:
        _verify_blob_bytes(blob_path, expected_sha256=sha256, expected_size=byte_size)
    except OSError:
        # Some Windows/filesystem combinations cannot hard-link. O_EXCL keeps
        # this fallback from replacing a concurrently created or unrelated file.
        descriptor = None
        created = False
        try:
            descriptor = os.open(blob_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(descriptor, "wb") as destination, upload_path.open("rb") as source:
                descriptor = None
                for chunk in iter(lambda: source.read(64 * 1024), b""):
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
        except FileExistsError:
            _verify_blob_bytes(blob_path, expected_sha256=sha256, expected_size=byte_size)
        except Exception:
            if created:
                blob_path.unlink(missing_ok=True)
            raise
        finally:
            if descriptor is not None:
                os.close(descriptor)
    _verify_blob_bytes(blob_path, expected_sha256=sha256, expected_size=byte_size)
    upload_path.unlink(missing_ok=True)
    if os.name != "nt":
        blob_path.chmod(0o600, follow_symlinks=False)


def _public_metadata(row: sqlite3.Row) -> dict:
    return {
        "id": str(row["id"]),
        "name": str(row["original_name"]),
        "mime_type": str(row["mime_type"]),
        "kind": str(row["kind"]),
        "byte_size": int(row["byte_size"]),
        "state": str(row["state"]),
        "created_at": _iso(row["created_at"]),
        "expires_at": _iso(row["expires_at"]),
    }


@synchronized_private_state
def create_attachment(
    data_dir: Path,
    *,
    original_name: str,
    content: bytes | None = None,
    stream: BinaryIO | None = None,
    content_type: str | None = None,
    now: float | None = None,
    staged_ttl: float = DEFAULT_STAGED_TTL,
) -> dict:
    """Validate, stage, and return safe metadata for an uploaded file."""
    if (content is None) == (stream is None):
        raise AttachmentValidationError("Provide exactly one attachment content source")
    if content is not None and not isinstance(content, bytes):
        raise AttachmentValidationError("Attachment content must be bytes")
    name = _normalize_name(original_name)
    supplied_type = _normalized_content_type(content_type)
    if staged_ttl <= 0:
        raise AttachmentValidationError("Attachment staging lifetime must be positive")

    created_at = _timestamp(now)
    attachment_id = f"attachment_{uuid.uuid4().hex}"
    expected_kind = _expected_kind(name, supplied_type)
    provisional_type = supplied_type or (
        _IMAGE_EXTENSIONS.get(Path(name.lower()).suffix)
        or _TEXT_EXTENSIONS.get(Path(name.lower()).suffix)
        or "application/octet-stream"
    )
    connection = connect(data_dir)
    upload_path = _uploads_root(data_dir) / f"{attachment_id}.upload"
    try:
        connection.execute(
            "INSERT INTO attachments "
            "(id, blob_id, original_name, mime_type, kind, state, byte_size, created_at, updated_at, expires_at) "
            "VALUES (?, NULL, ?, ?, ?, 'uploading', 0, ?, ?, ?)",
            (attachment_id, name, provisional_type, expected_kind, created_at, created_at, created_at + staged_ttl),
        )
        maximum = MAX_IMAGE_BYTES if expected_kind == "image" else MAX_TEXT_BYTES
        digest = hashlib.sha256()
        collected = bytearray()
        source = stream
        with upload_path.open("xb") as destination:
            if os.name != "nt":
                os.fchmod(destination.fileno(), 0o600)
            if content is not None:
                chunks = (content,)
            else:
                chunks = iter(lambda: source.read(64 * 1024), b"")  # type: ignore[union-attr]
            for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise AttachmentValidationError("Attachment stream must return bytes")
                if not chunk:
                    continue
                if len(collected) + len(chunk) > maximum:
                    label = "Image" if expected_kind == "image" else "Text and code file"
                    raise AttachmentValidationError(f"{label} exceeds its size limit")
                collected.extend(chunk)
                digest.update(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())

        payload = bytes(collected)
        kind, mime_type = _validate_content(name, payload, supplied_type)
        sha256 = digest.hexdigest()
        storage_key = f"{sha256[:2]}/{sha256}"
        blob_root = _blobs_root(data_dir)
        blob_path = _safe_blob_path(blob_root, storage_key, require_exists=False)
        _promote_blob(upload_path, blob_path, sha256=sha256, byte_size=len(payload))

        with transaction(connection, immediate=True):
            blob = connection.execute("SELECT id FROM blobs WHERE sha256 = ?", (sha256,)).fetchone()
            if blob is None:
                blob_id = f"blob_{uuid.uuid4().hex}"
                connection.execute(
                    "INSERT INTO blobs "
                    "(id, sha256, storage_key, byte_size, state, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'ready', ?, ?)",
                    (blob_id, sha256, storage_key, len(payload), created_at, created_at),
                )
            else:
                blob_id = str(blob["id"])
                connection.execute(
                    "UPDATE blobs SET state = 'ready', updated_at = ? WHERE id = ?",
                    (created_at, blob_id),
                )
            connection.execute(
                "UPDATE attachments SET blob_id = ?, mime_type = ?, kind = ?, state = 'staged', "
                "byte_size = ?, updated_at = ?, expires_at = ? WHERE id = ? AND state = 'uploading'",
                (blob_id, mime_type, kind, len(payload), created_at, created_at + staged_ttl, attachment_id),
            )
        row = connection.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
        return _public_metadata(row)
    except Exception:
        upload_path.unlink(missing_ok=True)
        connection.execute("DELETE FROM attachments WHERE id = ? AND state = 'uploading'", (attachment_id,))
        raise
    finally:
        connection.close()


@synchronized_private_state
def get_attachment(data_dir: Path, attachment_id: str) -> dict | None:
    """Return browser-safe metadata without a filesystem path or storage key."""
    identifier = _validate_attachment_id(attachment_id)
    connection = connect(data_dir)
    try:
        row = connection.execute("SELECT * FROM attachments WHERE id = ?", (identifier,)).fetchone()
        return _public_metadata(row) if row is not None else None
    finally:
        connection.close()


@synchronized_private_state
def resolve_blob_path(
    data_dir: Path,
    attachment_id: str,
    *,
    allowed_states: Collection[str] | None = None,
) -> Path:
    """Resolve a trusted local blob path after state and containment checks."""
    identifier = _validate_attachment_id(attachment_id)
    states = frozenset(allowed_states or AVAILABLE_STATES)
    if not states or not states <= ATTACHMENT_STATES:
        raise AttachmentValidationError("Invalid attachment state allowlist")
    connection = connect(data_dir)
    try:
        row = connection.execute(
            "SELECT a.state AS attachment_state, b.state AS blob_state, b.storage_key "
            "FROM attachments a LEFT JOIN blobs b ON b.id = a.blob_id WHERE a.id = ?",
            (identifier,),
        ).fetchone()
        if row is None:
            raise AttachmentNotFound("Attachment not found")
        if row["attachment_state"] not in states or row["blob_state"] != "ready":
            raise AttachmentUnavailable("Attachment is not available")
        try:
            return _safe_blob_path(_blobs_root(data_dir), str(row["storage_key"]), require_exists=True)
        except FileNotFoundError as exc:
            connection.execute("UPDATE blobs SET state = 'missing', updated_at = ? WHERE storage_key = ?", (_timestamp(), row["storage_key"]))
            connection.execute("UPDATE attachments SET state = 'missing', updated_at = ? WHERE id = ?", (_timestamp(), identifier))
            raise AttachmentUnavailable("Attachment content is missing") from exc
    finally:
        connection.close()


@synchronized_private_state
def read_attachment_text(
    data_dir: Path,
    attachment_id: str,
    *,
    allowed_states: Collection[str] | None = None,
) -> tuple[dict, str]:
    """Read one exact UTF-8 text blob after state, type, size, and digest checks."""

    identifier = _validate_attachment_id(attachment_id)
    states = frozenset(allowed_states or AVAILABLE_STATES)
    if not states or not states <= ATTACHMENT_STATES:
        raise AttachmentValidationError("Invalid attachment state allowlist")
    connection = connect(data_dir)
    try:
        row = connection.execute(
            "SELECT a.*, b.state AS blob_state, b.storage_key, b.sha256 AS blob_sha256, "
            "b.byte_size AS blob_byte_size FROM attachments a "
            "LEFT JOIN blobs b ON b.id = a.blob_id WHERE a.id = ?",
            (identifier,),
        ).fetchone()
        if row is None:
            raise AttachmentNotFound("Attachment not found")
        if row["state"] not in states or row["blob_state"] != "ready":
            raise AttachmentUnavailable("Attachment is not available")
        if row["kind"] != "text":
            raise AttachmentValidationError("Attachment is not text")
        expected_size = int(row["byte_size"])
        expected_sha256 = str(row["blob_sha256"] or "")
        if int(row["blob_byte_size"] or -1) != expected_size or not _SHA256_PATTERN.fullmatch(expected_sha256):
            raise AttachmentStorageError("Attachment blob metadata is invalid")
        path = _safe_blob_path(
            _blobs_root(data_dir),
            str(row["storage_key"]),
            require_exists=True,
        )
        flags = os.O_RDONLY
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_size != expected_size:
                raise AttachmentStorageError("Attachment blob content changed")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                payload = handle.read(expected_size + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(payload) != expected_size or hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise AttachmentStorageError("Attachment blob content changed")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AttachmentValidationError("Attachment text is not UTF-8") from exc
        if "\x00" in text:
            raise AttachmentValidationError("Attachment text contains unsupported content")
        return _public_metadata(row), text
    finally:
        connection.close()


@synchronized_private_state
def bind_run_attachment(
    data_dir: Path,
    attachment_id: str,
    run_id: str,
    *,
    direction: str = "input",
    ordinal: int = 0,
    now: float | None = None,
) -> dict:
    """Bind a staged attachment to retained run history."""
    identifier = _validate_attachment_id(attachment_id)
    normalized_run_id = _validate_run_id(run_id)
    if direction not in {"input", "output"}:
        raise AttachmentValidationError("Attachment direction must be input or output")
    if not isinstance(ordinal, int) or ordinal < 0:
        raise AttachmentValidationError("Attachment order is invalid")
    updated_at = _timestamp(now)
    connection = connect(data_dir)
    try:
        with transaction(connection, immediate=True):
            row = connection.execute(
                "SELECT a.*, b.state AS blob_state, b.storage_key FROM attachments a "
                "LEFT JOIN blobs b ON b.id = a.blob_id WHERE a.id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise AttachmentNotFound("Attachment not found")
            if row["state"] not in {"staged", "attached", "orphaned"}:
                raise AttachmentUnavailable("Attachment is not available for a run")
            if row["state"] == "staged" and row["expires_at"] is not None and row["expires_at"] <= updated_at:
                raise AttachmentUnavailable("Attachment staging period has expired")
            if row["blob_state"] != "ready":
                raise AttachmentUnavailable("Attachment content is not available")
            try:
                _safe_blob_path(_blobs_root(data_dir), str(row["storage_key"]), require_exists=True)
            except (FileNotFoundError, AttachmentError, OSError) as exc:
                raise AttachmentUnavailable("Attachment content is not available") from exc
            connection.execute(
                "INSERT INTO run_attachments(run_id, attachment_id, direction, ordinal, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id, attachment_id, direction) DO UPDATE SET ordinal = excluded.ordinal",
                (normalized_run_id, identifier, direction, ordinal, updated_at),
            )
            connection.execute(
                "UPDATE attachments SET state = 'attached', updated_at = ?, expires_at = NULL, delete_after = NULL "
                "WHERE id = ?",
                (updated_at, identifier),
            )
        row = connection.execute("SELECT * FROM attachments WHERE id = ?", (identifier,)).fetchone()
        return _public_metadata(row)
    finally:
        connection.close()


@synchronized_private_state
def list_run_attachments(
    data_dir: Path,
    run_id: str,
    *,
    direction: str | None = None,
) -> list[dict]:
    """Return ordered safe attachment metadata for retained run rendering."""
    normalized_run_id = _validate_run_id(run_id)
    if direction is not None and direction not in {"input", "output"}:
        raise AttachmentValidationError("Attachment direction must be input or output")
    connection = connect(data_dir)
    try:
        parameters: tuple = (normalized_run_id,)
        direction_clause = ""
        if direction is not None:
            direction_clause = " AND r.direction = ?"
            parameters = (normalized_run_id, direction)
        rows = connection.execute(
            "SELECT a.*, r.direction, r.ordinal FROM run_attachments r "
            "JOIN attachments a ON a.id = r.attachment_id WHERE r.run_id = ?"
            + direction_clause
            + " ORDER BY r.direction, r.ordinal, a.created_at, a.id",
            parameters,
        ).fetchall()
        return [
            {**_public_metadata(row), "direction": str(row["direction"]), "ordinal": int(row["ordinal"])}
            for row in rows
        ]
    finally:
        connection.close()


@synchronized_private_state
def release_attachment(
    data_dir: Path,
    attachment_id: str,
    *,
    grace_seconds: float = DEFAULT_ORPHAN_GRACE,
    now: float | None = None,
) -> dict:
    """Release an unused composer upload into the deletion grace period."""
    identifier = _validate_attachment_id(attachment_id)
    current = _timestamp(now)
    connection = connect(data_dir)
    try:
        with transaction(connection, immediate=True):
            row = connection.execute("SELECT * FROM attachments WHERE id = ?", (identifier,)).fetchone()
            if row is None:
                raise AttachmentNotFound("Attachment not found")
            reference = connection.execute(
                "SELECT 1 FROM run_attachments WHERE attachment_id = ? LIMIT 1", (identifier,)
            ).fetchone()
            if reference is not None:
                raise AttachmentUnavailable("Attachment is retained by Agent Console history")
            if row["state"] not in {"staged", "orphaned"}:
                raise AttachmentUnavailable("Attachment cannot be released")
            connection.execute(
                "UPDATE attachments SET state = 'orphaned', updated_at = ?, expires_at = NULL, delete_after = ? "
                "WHERE id = ?",
                (current, current + max(0.0, grace_seconds), identifier),
            )
        row = connection.execute("SELECT * FROM attachments WHERE id = ?", (identifier,)).fetchone()
        return _public_metadata(row)
    finally:
        connection.close()


@synchronized_private_state
def unbind_run_attachments(
    data_dir: Path,
    run_id: str,
    *,
    attachment_ids: Collection[str] | None = None,
    active_run_ids: Collection[str] = (),
    grace_seconds: float = DEFAULT_ORPHAN_GRACE,
    now: float | None = None,
) -> int:
    """Remove retained-run references and place newly unreferenced items in grace."""
    normalized_run_id = _validate_run_id(run_id)
    active = {_validate_run_id(item) for item in active_run_ids}
    if normalized_run_id in active:
        raise AttachmentUnavailable("Attachments for an active Agent Console run are protected")
    identifiers = None
    if attachment_ids is not None:
        identifiers = [_validate_attachment_id(item) for item in attachment_ids]
        if not identifiers:
            return 0
    current = _timestamp(now)
    connection = connect(data_dir)
    try:
        with transaction(connection, immediate=True):
            if identifiers is None:
                rows = connection.execute(
                    "SELECT attachment_id FROM run_attachments WHERE run_id = ?", (normalized_run_id,)
                ).fetchall()
            else:
                placeholders = ",".join("?" for _ in identifiers)
                rows = connection.execute(
                    f"SELECT attachment_id FROM run_attachments WHERE run_id = ? AND attachment_id IN ({placeholders})",
                    (normalized_run_id, *identifiers),
                ).fetchall()
            affected = [str(row[0]) for row in rows]
            if identifiers is None:
                connection.execute("DELETE FROM run_attachments WHERE run_id = ?", (normalized_run_id,))
            else:
                placeholders = ",".join("?" for _ in identifiers)
                connection.execute(
                    f"DELETE FROM run_attachments WHERE run_id = ? AND attachment_id IN ({placeholders})",
                    (normalized_run_id, *identifiers),
                )
            for identifier in affected:
                reference = connection.execute(
                    "SELECT 1 FROM run_attachments WHERE attachment_id = ? LIMIT 1", (identifier,)
                ).fetchone()
                if reference is None:
                    connection.execute(
                        "UPDATE attachments SET state = 'orphaned', updated_at = ?, expires_at = NULL, delete_after = ? "
                        "WHERE id = ? AND state != 'missing'",
                        (current, current + max(0.0, grace_seconds), identifier),
                    )
        return len(affected)
    finally:
        connection.close()


@synchronized_private_state
def garbage_collect(
    data_dir: Path,
    *,
    active_run_ids: Collection[str] = (),
    now: float | None = None,
    orphan_grace: float = DEFAULT_ORPHAN_GRACE,
    batch_size: int = DEFAULT_GC_BATCH,
) -> dict:
    """Perform a bounded, reference-aware attachment cleanup pass."""
    current = _timestamp(now)
    active = {_validate_run_id(item) for item in active_run_ids}
    if not isinstance(batch_size, int) or batch_size < 1 or batch_size > 1000:
        raise AttachmentValidationError("Attachment cleanup batch size is invalid")
    report = {"expired": 0, "orphaned": 0, "pending_delete": 0, "deleted": 0, "failed": 0}
    connection = connect(data_dir)
    blob_root = _blobs_root(data_dir)
    try:
        with transaction(connection, immediate=True):
            expired = connection.execute(
                "SELECT id FROM attachments a WHERE a.state = 'staged' AND a.expires_at <= ? "
                "AND NOT EXISTS (SELECT 1 FROM run_attachments r WHERE r.attachment_id = a.id) LIMIT ?",
                (current, batch_size),
            ).fetchall()
            for row in expired:
                connection.execute(
                    "UPDATE attachments SET state = 'orphaned', updated_at = ?, delete_after = ? WHERE id = ?",
                    (current, current + max(0.0, orphan_grace), row["id"]),
                )
            report["expired"] = len(expired)

            remaining = max(0, batch_size - len(expired))
            if remaining:
                attached_orphans = connection.execute(
                    "SELECT id FROM attachments a WHERE a.state = 'attached' "
                    "AND NOT EXISTS (SELECT 1 FROM run_attachments r WHERE r.attachment_id = a.id) LIMIT ?",
                    (remaining,),
                ).fetchall()
                for row in attached_orphans:
                    connection.execute(
                        "UPDATE attachments SET state = 'orphaned', updated_at = ?, delete_after = ? WHERE id = ?",
                        (current, current + max(0.0, orphan_grace), row["id"]),
                    )
                report["orphaned"] = len(attached_orphans)

            active_placeholders = ",".join("?" for _ in active)
            active_clause = (
                f"AND NOT EXISTS (SELECT 1 FROM run_attachments ar WHERE ar.attachment_id = a.id "
                f"AND ar.run_id IN ({active_placeholders})) " if active else ""
            )
            due = connection.execute(
                "SELECT id FROM attachments a WHERE a.state IN ('orphaned', 'pending_delete', 'deleting') "
                "AND (a.delete_after IS NULL OR a.delete_after <= ?) "
                "AND NOT EXISTS (SELECT 1 FROM run_attachments r WHERE r.attachment_id = a.id) "
                + active_clause + "LIMIT ?",
                (current, *sorted(active), batch_size),
            ).fetchall()
            for row in due:
                connection.execute(
                    "UPDATE attachments SET state = 'pending_delete', updated_at = ? WHERE id = ?",
                    (current, row["id"]),
                )
            report["pending_delete"] = len(due)

        for row in due:
            identifier = str(row["id"])
            blob = None
            try:
                with transaction(connection, immediate=True):
                    claimed = connection.execute(
                        "UPDATE attachments SET state = 'deleting', updated_at = ? WHERE id = ? "
                        "AND state = 'pending_delete' "
                        "AND NOT EXISTS (SELECT 1 FROM run_attachments WHERE attachment_id = ?)",
                        (current, identifier, identifier),
                    )
                    if not claimed.rowcount:
                        continue
                    blob = connection.execute(
                        "SELECT b.* FROM blobs b JOIN attachments a ON a.blob_id = b.id WHERE a.id = ?",
                        (identifier,),
                    ).fetchone()
                if blob is not None:
                    references = connection.execute(
                        "SELECT 1 FROM attachments WHERE blob_id = ? AND id != ? LIMIT 1",
                        (blob["id"], identifier),
                    ).fetchone()
                    if references is None:
                        path = _safe_blob_path(blob_root, str(blob["storage_key"]), require_exists=False)
                        if path.exists():
                            if path.is_symlink() or not path.is_file():
                                raise AttachmentStorageError("Attachment blob path is unsafe")
                            path.unlink()
                with transaction(connection, immediate=True):
                    still_unreferenced = connection.execute(
                        "SELECT 1 FROM run_attachments WHERE attachment_id = ? LIMIT 1", (identifier,)
                    ).fetchone()
                    if still_unreferenced is not None:
                        connection.execute(
                            "UPDATE attachments SET state = 'attached', updated_at = ?, delete_after = NULL WHERE id = ?",
                            (current, identifier),
                        )
                        continue
                    connection.execute("DELETE FROM attachments WHERE id = ?", (identifier,))
                    if blob is not None:
                        references = connection.execute(
                            "SELECT 1 FROM attachments WHERE blob_id = ? LIMIT 1", (blob["id"],)
                        ).fetchone()
                        if references is None:
                            connection.execute("DELETE FROM blobs WHERE id = ?", (blob["id"],))
                report["deleted"] += 1
            except (OSError, AttachmentError, sqlite3.Error):
                report["failed"] += 1
                attempts = int(blob["delete_attempts"]) + 1 if blob is not None else 1
                retry_at = current + min(DELETE_RETRY_MAX, DELETE_RETRY_BASE * (2 ** min(attempts - 1, 10)))
                connection.execute(
                    "UPDATE attachments SET delete_after = ?, updated_at = ? WHERE id = ? AND state = 'deleting'",
                    (retry_at, current, identifier),
                )
                if blob is not None:
                    connection.execute(
                        "UPDATE blobs SET delete_attempts = delete_attempts + 1, updated_at = ? WHERE id = ?",
                        (current, blob["id"]),
                    )
        return report
    finally:
        connection.close()


@synchronized_private_state
def reconcile_startup(
    data_dir: Path,
    *,
    active_run_ids: Collection[str] = (),
    retained_run_ids: Collection[str] | None = None,
    now: float | None = None,
) -> dict:
    """Repair crash leftovers, flag missing content, and run bounded GC."""
    current = _timestamp(now)
    report = {
        "temporary_deleted": 0,
        "uploading_records_deleted": 0,
        "filesystem_orphans_deleted": 0,
        "deletions_finalized": 0,
        "missing": 0,
        "run_references_released": 0,
        "gc": {},
    }
    uploads = _uploads_root(data_dir)
    for candidate in uploads.iterdir():
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if current - candidate.stat().st_mtime >= UPLOAD_MAX_AGE:
                candidate.unlink()
                report["temporary_deleted"] += 1
        except OSError:
            continue

    connection = connect(data_dir)
    root = _blobs_root(data_dir)
    known_keys: set[str] = set()
    try:
        if retained_run_ids is not None:
            retained = {_validate_run_id(item) for item in retained_run_ids}
            with transaction(connection, immediate=True):
                if retained:
                    placeholders = ",".join("?" for _ in retained)
                    stale = connection.execute(
                        f"SELECT DISTINCT run_id FROM run_attachments WHERE run_id NOT IN ({placeholders})",
                        tuple(sorted(retained)),
                    ).fetchall()
                else:
                    stale = connection.execute(
                        "SELECT DISTINCT run_id FROM run_attachments"
                    ).fetchall()
                for row in stale:
                    released = connection.execute(
                        "SELECT attachment_id FROM run_attachments WHERE run_id = ?",
                        (row["run_id"],),
                    ).fetchall()
                    connection.execute(
                        "DELETE FROM run_attachments WHERE run_id = ?", (row["run_id"],)
                    )
                    report["run_references_released"] += len(released)
                    for item in released:
                        remaining = connection.execute(
                            "SELECT 1 FROM run_attachments WHERE attachment_id = ? LIMIT 1",
                            (item["attachment_id"],),
                        ).fetchone()
                        if remaining is None:
                            connection.execute(
                                "UPDATE attachments SET state = 'orphaned', updated_at = ?, "
                                "expires_at = NULL, delete_after = ? WHERE id = ? AND state != 'missing'",
                                (
                                    current,
                                    current + DEFAULT_ORPHAN_GRACE,
                                    item["attachment_id"],
                                ),
                            )
        with transaction(connection, immediate=True):
            removed = connection.execute(
                "DELETE FROM attachments WHERE state = 'uploading' AND created_at <= ?",
                (current - UPLOAD_MAX_AGE,),
            )
        report["uploading_records_deleted"] = max(0, removed.rowcount)
        rows = connection.execute("SELECT id, storage_key FROM blobs").fetchall()
        for row in rows:
            storage_key = str(row["storage_key"])
            known_keys.add(storage_key)
            try:
                _safe_blob_path(root, storage_key, require_exists=True)
            except (FileNotFoundError, AttachmentError, OSError):
                with transaction(connection, immediate=True):
                    linked = connection.execute(
                        "SELECT id, state FROM attachments WHERE blob_id = ?", (row["id"],)
                    ).fetchall()
                    if linked and all(item["state"] in {"pending_delete", "deleting"} for item in linked):
                        connection.execute("DELETE FROM attachments WHERE blob_id = ?", (row["id"],))
                        connection.execute("DELETE FROM blobs WHERE id = ?", (row["id"],))
                        report["deletions_finalized"] += len(linked)
                    else:
                        connection.execute(
                            "UPDATE blobs SET state = 'missing', updated_at = ? WHERE id = ?",
                            (current, row["id"]),
                        )
                        changed = connection.execute(
                            "UPDATE attachments SET state = 'missing', updated_at = ? WHERE blob_id = ? "
                            "AND state != 'missing'",
                            (current, row["id"]),
                        )
                        report["missing"] += max(0, changed.rowcount)

        for prefix in root.iterdir():
            if prefix.is_symlink() or not prefix.is_dir():
                continue
            for candidate in prefix.iterdir():
                try:
                    relative = f"{prefix.name}/{candidate.name}"
                    if relative in known_keys or candidate.is_symlink() or not candidate.is_file():
                        continue
                    if current - candidate.stat().st_mtime >= FILESYSTEM_ORPHAN_MIN_AGE:
                        candidate.unlink()
                        report["filesystem_orphans_deleted"] += 1
                except OSError:
                    continue
    finally:
        connection.close()
    report["gc"] = garbage_collect(data_dir, active_run_ids=active_run_ids, now=current)
    return report
