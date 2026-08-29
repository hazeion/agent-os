"""Owner-private disposable cache and durable preference for link previews.

This module stores only sanitized derived values. Raw URLs are accepted only as
already-normalized in-process inputs for HMAC identity and are never persisted,
returned, or included in exception text.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
import time
from typing import Callable

from json_store import NO_WRITE, read_json_guarded, update_json
from link_preview_webp import valid_transformed_webp


CACHE_SCHEMA_VERSION = 1
POLICY_VERSION = "policy-v1"
PARSER_VERSION = "parser-v1"
REQUEST_PROFILE_VERSION = "request-v1"
IMAGE_TRANSFORM_VERSION = "image-transform-v1"
MAXIMUM_METADATA_ENTRIES = 512
MAXIMUM_IMAGE_BYTES = 64 * 1024 * 1024
MAXIMUM_READY_SECONDS = 24 * 60 * 60
UNAVAILABLE_SECONDS = 5 * 60
BLOCKED_SECONDS = 60 * 60
MAXIMUM_PREFERENCE_BYTES = 4 * 1024
_IMAGE_ID = re.compile(r"[0-9a-f]{32}")
_IMAGE_TEMP = re.compile(r"\.[0-9a-f]{32}\.[0-9a-f]{16}\.tmp")
_CACHE_KEY = re.compile(r"[0-9a-f]{64}")
_STATUSES = {"ready", "unavailable", "blocked"}
_UNSAFE_TEXT = re.compile("[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_CACHE_META_SCHEMA = (
    ("singleton", "INTEGER", 0, 1),
    ("schema_version", "INTEGER", 1, 0),
    ("secret_check", "TEXT", 1, 0),
    ("policy_version", "TEXT", 1, 0),
    ("parser_version", "TEXT", 1, 0),
    ("request_profile_version", "TEXT", 1, 0),
    ("image_transform_version", "TEXT", 1, 0),
)
_PREVIEW_SCHEMA = (
    ("cache_key", "TEXT", 0, 1), ("final_key", "TEXT", 1, 0),
    ("status", "TEXT", 1, 0), ("title", "TEXT", 0, 0),
    ("description", "TEXT", 0, 0), ("site_name", "TEXT", 0, 0),
    ("display_host", "TEXT", 0, 0), ("image_alt", "TEXT", 0, 0),
    ("image_key", "TEXT", 0, 0), ("image_final_key", "TEXT", 0, 0),
    ("image_id", "TEXT", 0, 0), ("image_bytes", "INTEGER", 1, 0),
    ("created_at", "REAL", 1, 0), ("expires_at", "REAL", 1, 0),
    ("last_accessed", "REAL", 1, 0),
)


class LinkPreviewCacheError(RuntimeError):
    code = "link_preview.cache_error"


class LinkPreviewPreferenceConflict(LinkPreviewCacheError):
    code = "link_preview.preference_conflict"


@dataclass(frozen=True)
class LinkPreviewPreference:
    enabled: bool
    revision: int

    def public_projection(self) -> dict[str, object]:
        return {"enabled": self.enabled, "revision": self.revision}


def _owned_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    metadata = os.lstat(path)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise LinkPreviewCacheError("link preview storage unavailable")
    if os.name == "posix":
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise LinkPreviewCacheError("link preview storage unavailable")
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            raise LinkPreviewCacheError("link preview storage unavailable")


def _owned_file(path: Path, *, maximum_bytes: int | None = None) -> os.stat_result:
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_nlink not in ({0, 1} if os.name == "nt" else {1})
        or maximum_bytes is not None
        and metadata.st_size > maximum_bytes
    ):
        raise LinkPreviewCacheError("link preview storage unavailable")
    if os.name == "posix":
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise LinkPreviewCacheError("link preview storage unavailable")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise LinkPreviewCacheError("link preview storage unavailable")
    return metadata


def _read_owned_bytes(path: Path, *, maximum_bytes: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        state = os.fstat(descriptor)
        named = _owned_file(path, maximum_bytes=maximum_bytes)
        if state.st_dev != named.st_dev or state.st_ino != named.st_ino or state.st_size > maximum_bytes:
            raise LinkPreviewCacheError("link preview storage unavailable")
        data = os.read(descriptor, maximum_bytes + 1)
        if len(data) > maximum_bytes:
            raise LinkPreviewCacheError("link preview storage unavailable")
        after = os.fstat(descriptor)
        current = _owned_file(path, maximum_bytes=maximum_bytes)
        if after.st_dev != current.st_dev or after.st_ino != current.st_ino or after.st_size != len(data):
            raise LinkPreviewCacheError("link preview storage unavailable")
        return data
    finally:
        os.close(descriptor)


def _bounded_text(value: object, maximum: int, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or value.strip() != value or not value or len(value) > maximum:
        raise LinkPreviewCacheError("link preview value invalid")
    if _UNSAFE_TEXT.search(value):
        raise LinkPreviewCacheError("link preview value invalid")
    return value


class LinkPreviewPreferenceStore:
    """Persist the privacy choice independently from disposable preview data."""

    def __init__(self, data_root: Path):
        self._root = Path(data_root) / "config"
        self._path = self._root / "link-previews-v1.json"

    @staticmethod
    def _validate(value: object) -> LinkPreviewPreference:
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "enabled", "revision"}
            or value.get("schema_version") != 1
            or type(value.get("enabled")) is not bool
            or type(value.get("revision")) is not int
            or not 1 <= value["revision"] <= 2_147_483_647
        ):
            raise LinkPreviewCacheError("link preview preference unavailable")
        return LinkPreviewPreference(value["enabled"], value["revision"])

    def read(self) -> LinkPreviewPreference:
        _owned_directory(self._root)
        value = read_json_guarded(
            self._path,
            {"schema_version": 1, "enabled": True, "revision": 1},
            maximum_bytes=MAXIMUM_PREFERENCE_BYTES,
            required_mode=0o600,
            expected_type=dict,
        )
        return self._validate(value)

    def update(self, *, enabled: bool, expected_revision: int) -> LinkPreviewPreference:
        if type(enabled) is not bool or type(expected_revision) is not int:
            raise LinkPreviewCacheError("link preview preference invalid")
        _owned_directory(self._root)

        def mutate(current: object):
            preference = self._validate(current)
            if preference.revision != expected_revision:
                raise LinkPreviewPreferenceConflict("link preview preference changed")
            if preference.enabled == enabled:
                return NO_WRITE, preference
            if preference.revision == 2_147_483_647:
                raise LinkPreviewCacheError("link preview preference unavailable")
            updated = LinkPreviewPreference(enabled, preference.revision + 1)
            return {
                "schema_version": 1,
                "enabled": updated.enabled,
                "revision": updated.revision,
            }, updated

        return update_json(
            self._path,
            {"schema_version": 1, "enabled": True, "revision": 1},
            mutate,
            maximum_bytes=MAXIMUM_PREFERENCE_BYTES,
            expected_type=dict,
            required_mode=0o600,
        )


class LinkPreviewCache:
    """Bounded cache keyed by HMAC identities over normalized URLs."""

    def __init__(self, data_root: Path, *, clock: Callable[[], float] = time.time):
        self._root = Path(data_root) / "cache" / "link-previews-v1"
        self._images = self._root / "images"
        self._secret_path = self._root / "secret"
        self._database_path = self._root / "metadata.sqlite3"
        self._clock = clock
        self._lock = threading.RLock()
        self._secret = self._initialize_storage()

    def _initialize_storage(self) -> bytes:
        _owned_directory(self._root.parent)
        _owned_directory(self._root)
        _owned_directory(self._images)
        secret_missing = not self._secret_path.exists()
        if secret_missing:
            self._discard_derived_files()
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self._secret_path, flags, 0o600)
            secret = secrets.token_bytes(32)
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(descriptor, 0o600)
                if os.write(descriptor, secret) != len(secret):
                    raise OSError("secret write incomplete")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        _owned_file(self._secret_path, maximum_bytes=32)
        secret = _read_owned_bytes(self._secret_path, maximum_bytes=32)
        if len(secret) != 32:
            raise LinkPreviewCacheError("link preview storage unavailable")
        self._initialize_database(secret)
        return secret

    def _discard_derived_files(self) -> None:
        for name in ("metadata.sqlite3", "metadata.sqlite3-journal", "metadata.sqlite3-wal", "metadata.sqlite3-shm"):
            path = self._root / name
            try:
                if path.exists():
                    _owned_file(path)
                    path.unlink()
            except FileNotFoundError:
                pass
        if self._images.exists():
            for path in self._images.iterdir():
                if _IMAGE_TEMP.fullmatch(path.name):
                    _owned_file(path)
                    path.unlink()
                    continue
                if not _IMAGE_ID.fullmatch(path.stem) or path.suffix != ".webp":
                    raise LinkPreviewCacheError("link preview storage unavailable")
                _owned_file(path, maximum_bytes=512 * 1024)
                path.unlink()

    def _connect(self) -> sqlite3.Connection:
        if self._database_path.exists():
            expected = _owned_file(self._database_path)
        else:
            descriptor = os.open(
                self._database_path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            expected = os.fstat(descriptor)
            os.close(descriptor)
        connection = sqlite3.connect(self._database_path, timeout=2.0)
        current = _owned_file(self._database_path)
        if current.st_dev != expected.st_dev or current.st_ino != expected.st_ino:
            connection.close()
            raise LinkPreviewCacheError("link preview storage unavailable")
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA foreign_keys=ON")
        except Exception:
            connection.close()
            raise
        return connection

    def _initialize_database(self, secret: bytes) -> None:
        check = hmac.new(secret, b"link-preview-cache-check-v1", hashlib.sha256).hexdigest()
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache_meta (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version INTEGER NOT NULL,
                    secret_check TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    request_profile_version TEXT NOT NULL,
                    image_transform_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS previews (
                    cache_key TEXT PRIMARY KEY,
                    final_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT,
                    description TEXT,
                    site_name TEXT,
                    display_host TEXT,
                    image_alt TEXT,
                    image_key TEXT,
                    image_final_key TEXT,
                    image_id TEXT UNIQUE,
                    image_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    last_accessed REAL NOT NULL
                );
                """
            )
            row = connection.execute("SELECT * FROM cache_meta WHERE singleton = 1").fetchone()
            cache_meta_schema = tuple((item[1], item[2].upper(), item[3], item[5]) for item in connection.execute("PRAGMA table_info(cache_meta)"))
            preview_schema = tuple((item[1], item[2].upper(), item[3], item[5]) for item in connection.execute("PRAGMA table_info(previews)"))
            if cache_meta_schema != _CACHE_META_SCHEMA or preview_schema != _PREVIEW_SCHEMA:
                raise sqlite3.DatabaseError("cache schema invalid")
            if row is None:
                connection.execute("INSERT INTO cache_meta VALUES (1, ?, ?, ?, ?, ?, ?)", (CACHE_SCHEMA_VERSION, check, POLICY_VERSION, PARSER_VERSION, REQUEST_PROFILE_VERSION, IMAGE_TRANSFORM_VERSION))
            elif (
                row["schema_version"] != CACHE_SCHEMA_VERSION
                or not hmac.compare_digest(row["secret_check"], check)
                or row["policy_version"] != POLICY_VERSION
                or row["parser_version"] != PARSER_VERSION
                or row["request_profile_version"] != REQUEST_PROFILE_VERSION
                or row["image_transform_version"] != IMAGE_TRANSFORM_VERSION
            ):
                connection.close()
                self._discard_derived_files()
                self._initialize_database(secret)
                return
            self._reconcile_images(connection)
            connection.commit()
        except sqlite3.DatabaseError:
            try:
                if connection is not None:
                    connection.close()
            finally:
                self._discard_derived_files()
            self._initialize_database(secret)
            return
        except OSError as exc:
            raise LinkPreviewCacheError("link preview storage unavailable") from exc
        finally:
            try:
                if connection is not None:
                    connection.close()
            except Exception:
                pass
        _owned_file(self._database_path)

    def _reconcile_images(self, connection: sqlite3.Connection) -> None:
        referenced: dict[str, int] = {}
        for row in connection.execute("SELECT * FROM previews"):
            self._validate_row(row)
            if row["image_id"] is not None:
                referenced[row["image_id"]] = row["image_bytes"]
        observed: set[str] = set()
        for path in self._images.iterdir():
            if _IMAGE_TEMP.fullmatch(path.name):
                _owned_file(path)
                path.unlink()
                continue
            if path.suffix != ".webp" or _IMAGE_ID.fullmatch(path.stem) is None:
                raise LinkPreviewCacheError("link preview storage unavailable")
            state = _owned_file(path)
            expected = referenced.get(path.stem)
            if expected is None or state.st_size != expected or state.st_size > 512 * 1024:
                path.unlink()
                if expected is not None:
                    connection.execute("UPDATE previews SET image_id = NULL, image_key = NULL, image_final_key = NULL, image_bytes = 0 WHERE image_id = ?", (path.stem,))
                continue
            observed.add(path.stem)
        for image_id in set(referenced) - observed:
            connection.execute("UPDATE previews SET image_id = NULL, image_key = NULL, image_final_key = NULL, image_bytes = 0 WHERE image_id = ?", (image_id,))
        for evicted in self._evict(connection):
            self._unlink_image(evicted)

    def _identity(self, namespace: str, normalized_url: str) -> str:
        if not isinstance(normalized_url, str) or not normalized_url or len(normalized_url.encode("ascii")) > 2_048:
            raise LinkPreviewCacheError("link preview identity invalid")
        content_version = IMAGE_TRANSFORM_VERSION if namespace.startswith("link-image") else PARSER_VERSION
        payload = "\0".join((namespace, POLICY_VERSION, content_version, REQUEST_PROFILE_VERSION, normalized_url)).encode("ascii")
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def lookup(self, normalized_url: str) -> dict[str, object] | None:
        cache_key = self._identity("link-metadata", normalized_url)
        now = self._clock()
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute("SELECT * FROM previews WHERE cache_key = ?", (cache_key,)).fetchone()
                if row is None:
                    return None
                if row["expires_at"] <= now:
                    image_id = row["image_id"]
                    connection.execute("DELETE FROM previews WHERE cache_key = ?", (cache_key,))
                    connection.commit()
                    self._unlink_image(image_id)
                    return None
                connection.execute("UPDATE previews SET last_accessed = ? WHERE cache_key = ?", (now, cache_key))
                connection.commit()
                return self._projection(row)
            finally:
                connection.close()

    def store(
        self,
        normalized_url: str,
        *,
        final_normalized_url: str,
        status: str,
        ttl_seconds: int,
        title: str | None = None,
        description: str | None = None,
        site_name: str | None = None,
        display_host: str | None = None,
        image_alt: str | None = None,
        image_webp: bytes | None = None,
        image_normalized_url: str | None = None,
        image_final_normalized_url: str | None = None,
    ) -> dict[str, object]:
        if status not in _STATUSES or type(ttl_seconds) is not int or ttl_seconds < 0:
            raise LinkPreviewCacheError("link preview value invalid")
        maximum_ttl = MAXIMUM_READY_SECONDS if status == "ready" else UNAVAILABLE_SECONDS if status == "unavailable" else BLOCKED_SECONDS
        if ttl_seconds > maximum_ttl:
            raise LinkPreviewCacheError("link preview value invalid")
        safe_title = _bounded_text(title, 200)
        safe_description = _bounded_text(description, 500)
        safe_site = _bounded_text(site_name, 120)
        safe_host = _bounded_text(display_host, 253, required=status == "ready")
        safe_alt = _bounded_text(image_alt, 200)
        if status == "ready" and safe_title is None and safe_description is None:
            raise LinkPreviewCacheError("link preview value invalid")
        if status != "ready" and any(value is not None for value in (title, description, site_name, display_host, image_alt, image_webp)):
            raise LinkPreviewCacheError("link preview value invalid")
        if image_webp is not None and not valid_transformed_webp(image_webp):
            raise LinkPreviewCacheError("link preview value invalid")
        if (image_webp is None) != (image_normalized_url is None) or (image_webp is None) != (image_final_normalized_url is None):
            raise LinkPreviewCacheError("link preview value invalid")
        cache_key = self._identity("link-metadata", normalized_url)
        final_key = self._identity("link-final", final_normalized_url)
        image_key = self._identity("link-image", image_normalized_url) if image_normalized_url is not None else None
        image_final_key = self._identity("link-image-final", image_final_normalized_url) if image_final_normalized_url is not None else None
        now = self._clock()
        expires = now + ttl_seconds
        image_id = secrets.token_hex(16) if image_webp is not None else None
        if image_id is not None:
            self._write_image(image_id, image_webp)
        with self._lock:
            connection = self._connect()
            old_image_id: str | None = None
            try:
                old = connection.execute("SELECT image_id FROM previews WHERE cache_key = ?", (cache_key,)).fetchone()
                old_image_id = old["image_id"] if old is not None else None
                connection.execute(
                    """INSERT OR REPLACE INTO previews (
                    cache_key, final_key, status, title, description, site_name,
                    display_host, image_alt, image_key, image_final_key, image_id,
                    image_bytes, created_at, expires_at, last_accessed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cache_key, final_key, status, safe_title, safe_description,
                        safe_site, safe_host, safe_alt, image_key, image_final_key, image_id,
                        len(image_webp) if image_webp is not None else 0,
                        now, expires, now,
                    ),
                )
                evicted = self._evict(connection)
                row = connection.execute("SELECT * FROM previews WHERE cache_key = ?", (cache_key,)).fetchone()
                connection.commit()
            except Exception:
                connection.rollback()
                if image_id is not None:
                    self._unlink_image(image_id)
                raise
            finally:
                connection.close()
            if old_image_id and old_image_id != image_id:
                self._unlink_image(old_image_id)
            for evicted_image in evicted:
                self._unlink_image(evicted_image)
            if row is None:
                raise LinkPreviewCacheError("link preview cache capacity unavailable")
            return self._projection(row)

    def _evict(self, connection: sqlite3.Connection) -> list[str]:
        evicted: list[str] = []
        while True:
            count, image_bytes = connection.execute("SELECT COUNT(*), COALESCE(SUM(image_bytes), 0) FROM previews").fetchone()
            if count <= MAXIMUM_METADATA_ENTRIES and image_bytes <= MAXIMUM_IMAGE_BYTES:
                return evicted
            row = connection.execute("SELECT cache_key, image_id FROM previews ORDER BY last_accessed, created_at, cache_key LIMIT 1").fetchone()
            if row is None:
                return evicted
            connection.execute("DELETE FROM previews WHERE cache_key = ?", (row["cache_key"],))
            if row["image_id"]:
                evicted.append(row["image_id"])

    @staticmethod
    def _projection(row: sqlite3.Row) -> dict[str, object]:
        LinkPreviewCache._validate_row(row)
        result: dict[str, object] = {"status": row["status"]}
        if row["status"] == "ready":
            for field in ("title", "description", "site_name", "display_host", "image_alt", "image_id"):
                if row[field] is not None:
                    result[field] = row[field]
        return result

    @staticmethod
    def _validate_row(row: sqlite3.Row) -> None:
        if (
            not isinstance(row["cache_key"], str)
            or _CACHE_KEY.fullmatch(row["cache_key"]) is None
            or not isinstance(row["final_key"], str)
            or _CACHE_KEY.fullmatch(row["final_key"]) is None
            or row["status"] not in _STATUSES
            or type(row["image_bytes"]) is not int
            or not 0 <= row["image_bytes"] <= 512 * 1024
            or any(type(row[name]) not in {int, float} or not math.isfinite(float(row[name])) for name in ("created_at", "expires_at", "last_accessed"))
            or row["expires_at"] < row["created_at"]
        ):
            raise LinkPreviewCacheError("link preview storage unavailable")
        title = _bounded_text(row["title"], 200)
        description = _bounded_text(row["description"], 500)
        site = _bounded_text(row["site_name"], 120)
        host = _bounded_text(row["display_host"], 253)
        alt = _bounded_text(row["image_alt"], 200)
        image_id = row["image_id"]
        image_key = row["image_key"]
        image_final_key = row["image_final_key"]
        if row["status"] != "ready":
            if any(value is not None for value in (title, description, site, host, alt, image_id, image_key, image_final_key)) or row["image_bytes"] != 0:
                raise LinkPreviewCacheError("link preview storage unavailable")
            return
        if (title is None and description is None) or host is None:
            raise LinkPreviewCacheError("link preview storage unavailable")
        if image_id is None:
            if image_key is not None or image_final_key is not None or row["image_bytes"] != 0:
                raise LinkPreviewCacheError("link preview storage unavailable")
        elif (
            not isinstance(image_id, str)
            or _IMAGE_ID.fullmatch(image_id) is None
            or not isinstance(image_key, str)
            or _CACHE_KEY.fullmatch(image_key) is None
            or not isinstance(image_final_key, str)
            or _CACHE_KEY.fullmatch(image_final_key) is None
            or row["image_bytes"] < 1
        ):
            raise LinkPreviewCacheError("link preview storage unavailable")

    def image(self, image_id: str) -> tuple[bytes, int] | None:
        if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
            return None
        now = self._clock()
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute("SELECT * FROM previews WHERE image_id = ?", (image_id,)).fetchone()
            finally:
                connection.close()
            if row is None or row["expires_at"] <= now:
                return None
            self._validate_row(row)
            path = self._images / f"{image_id}.webp"
            try:
                metadata = _owned_file(path, maximum_bytes=512 * 1024)
                if metadata.st_size != row["image_bytes"]:
                    return None
                data = _read_owned_bytes(path, maximum_bytes=512 * 1024)
            except (FileNotFoundError, OSError, LinkPreviewCacheError):
                return None
            if not valid_transformed_webp(data):
                return None
            return data, max(0, min(300, int(row["expires_at"] - now)))

    def clear(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                image_ids = [row[0] for row in connection.execute("SELECT image_id FROM previews WHERE image_id IS NOT NULL")]
                connection.execute("DELETE FROM previews")
                self._reconcile_images(connection)
                connection.commit()
            finally:
                connection.close()
            for image_id in image_ids:
                self._unlink_image(image_id)

    def _write_image(self, image_id: str, data: bytes) -> None:
        target = self._images / f"{image_id}.webp"
        temporary = self._images / f".{image_id}.{secrets.token_hex(8)}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        committed = False
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            if os.write(descriptor, data) != len(data):
                raise OSError("image write incomplete")
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            temporary.replace(target)
            committed = True
            _owned_file(target, maximum_bytes=512 * 1024)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if not committed:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def _unlink_image(self, image_id: object) -> None:
        if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
            return
        path = self._images / f"{image_id}.webp"
        try:
            _owned_file(path, maximum_bytes=512 * 1024)
            path.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "BLOCKED_SECONDS",
    "LinkPreviewCache",
    "LinkPreviewCacheError",
    "LinkPreviewPreference",
    "LinkPreviewPreferenceConflict",
    "LinkPreviewPreferenceStore",
    "MAXIMUM_IMAGE_BYTES",
    "MAXIMUM_METADATA_ENTRIES",
    "MAXIMUM_READY_SECONDS",
    "UNAVAILABLE_SECONDS",
]
