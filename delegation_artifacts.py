"""Private snapshots for files produced by remote delegated Hermes tasks.

The browser never receives a remote identifier, digest, path, or Hermes URL.
Mentat downloads through its fixed server-side adapter, revalidates the file,
and publishes only an opaque local attachment identifier.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from agent_console_attachments import (
    AttachmentError,
    bind_run_attachment,
    create_attachment,
    list_run_attachments,
    resolve_blob_path,
    unbind_run_attachments,
)
from mentat_db import connect, transaction


MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
MAX_ARTIFACT_COUNT = 10
MAX_TASK_BYTES = 250 * 1024 * 1024
_IMPORT_LOCK = threading.RLock()


def _serialized(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with _IMPORT_LOCK:
            return function(*args, **kwargs)

    return guarded


@contextmanager
def artifact_operation_lock():
    """Serialize task deletion and multi-step artifact imports."""
    with _IMPORT_LOCK:
        yield


def _binding_id(
    mentat_task_id: str,
    connection_binding_id: str,
    board: str,
    remote_task_id: str,
) -> str:
    material = (
        f"{mentat_task_id}\0{connection_binding_id}\0{board}\0{remote_task_id}"
    ).encode("utf-8")
    return "delegation_" + hashlib.sha256(material).hexdigest()


def binding_ids(data_dir: Path) -> tuple[str, ...]:
    connection = connect(data_dir)
    try:
        rows = connection.execute(
            "SELECT DISTINCT binding_id FROM task_artifacts ORDER BY binding_id"
        ).fetchall()
        return tuple(str(row["binding_id"]) for row in rows)
    finally:
        connection.close()


@_serialized
def reconcile_task_artifact_bindings(
    data_dir: Path,
    tasks: list[dict[str, Any]],
) -> tuple[str, ...]:
    """Drop private mappings that no longer match a live delegated task."""
    if not isinstance(tasks, list):
        raise ValueError("tasks must be a list")
    live = {
        (
            str(task.get("id") or ""),
            str(delegation.get("connection_binding_id") or ""),
            str(delegation.get("board_id") or "default"),
            str(delegation.get("kanban_task_id") or ""),
        )
        for task in tasks
        if isinstance(task, dict)
        and isinstance((delegation := task.get("delegation")), dict)
        and task.get("id")
        and delegation.get("connection_binding_id")
        and delegation.get("kanban_task_id")
    }
    connection = connect(data_dir)
    try:
        rows = connection.execute(
            "SELECT mentat_task_id, connection_binding_id, board_id, "
            "remote_task_id, attachment_id, binding_id FROM task_artifacts"
        ).fetchall()
        stale = [
            row
            for row in rows
            if (
                str(row["mentat_task_id"]),
                str(row["connection_binding_id"]),
                str(row["board_id"]),
                str(row["remote_task_id"]),
            )
            not in live
        ]
        if stale:
            with transaction(connection, immediate=True):
                connection.executemany(
                    "DELETE FROM task_artifacts WHERE mentat_task_id = ? "
                    "AND connection_binding_id = ? AND board_id = ? "
                    "AND remote_task_id = ? AND attachment_id = ?",
                    [
                        (
                            str(row["mentat_task_id"]),
                            str(row["connection_binding_id"]),
                            str(row["board_id"]),
                            str(row["remote_task_id"]),
                            str(row["attachment_id"]),
                        )
                        for row in stale
                    ],
                )
    finally:
        connection.close()
    stale_bindings = {str(row["binding_id"]) for row in stale}
    for binding in stale_bindings:
        try:
            unbind_run_attachments(data_dir, binding)
        except AttachmentError:
            pass
    return binding_ids(data_dir)


def list_task_artifacts(
    data_dir: Path,
    mentat_task_id: str,
    *,
    connection_binding_id: str | None = None,
    board: str | None = None,
    remote_task_id: str | None = None,
) -> list[dict[str, Any]]:
    connection = connect(data_dir)
    try:
        clauses = ["mentat_task_id = ?"]
        parameters: list[str] = [str(mentat_task_id)]
        if connection_binding_id is not None:
            clauses.append("connection_binding_id = ?")
            parameters.append(str(connection_binding_id))
        if board is not None:
            clauses.append("board_id = ?")
            parameters.append(str(board))
        if remote_task_id is not None:
            clauses.append("remote_task_id = ?")
            parameters.append(str(remote_task_id))
        rows = connection.execute(
            "SELECT attachment_id, binding_id, ordinal "
            "FROM task_artifacts WHERE "
            + " AND ".join(clauses)
            + " "
            "ORDER BY ordinal, created_at, attachment_id",
            tuple(parameters),
        ).fetchall()
    finally:
        connection.close()
    artifacts: list[dict[str, Any]] = []
    by_binding: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        binding = str(row["binding_id"])
        if binding not in by_binding:
            try:
                by_binding[binding] = {
                    item["id"]: item
                    for item in list_run_attachments(
                        data_dir,
                        binding,
                        direction="output",
                    )
                }
            except AttachmentError:
                by_binding[binding] = {}
        metadata = by_binding[binding].get(str(row["attachment_id"]))
        if metadata:
            artifacts.append(metadata)
    return artifacts


def _reconcile_mappings(
    data_dir: Path,
    *,
    mentat_task_id: str,
    connection_binding_id: str,
    board: str,
    remote_task_id: str,
    keep_remote_artifact_ids: set[str],
) -> None:
    """Remove snapshots no longer present in the authoritative manifest."""
    connection = connect(data_dir)
    try:
        rows = connection.execute(
            "SELECT remote_artifact_id, attachment_id, binding_id "
            "FROM task_artifacts WHERE mentat_task_id = ? "
            "AND connection_binding_id = ? AND board_id = ? "
            "AND remote_task_id = ?",
            (
                str(mentat_task_id),
                str(connection_binding_id),
                str(board),
                str(remote_task_id),
            ),
        ).fetchall()
        stale = [
            row
            for row in rows
            if str(row["binding_id"])
            != _binding_id(
                mentat_task_id,
                connection_binding_id,
                board,
                remote_task_id,
            )
            or str(row["remote_artifact_id"]) not in keep_remote_artifact_ids
        ]
        if not stale:
            return
        with transaction(connection, immediate=True):
            connection.executemany(
                "DELETE FROM task_artifacts "
                "WHERE mentat_task_id = ? AND connection_binding_id = ? "
                "AND board_id = ? AND remote_task_id = ? "
                "AND remote_artifact_id = ?",
                [
                    (
                        str(mentat_task_id),
                        str(connection_binding_id),
                        str(board),
                        str(remote_task_id),
                        str(row["remote_artifact_id"]),
                    )
                    for row in stale
                ],
            )
    finally:
        connection.close()
    by_binding: dict[str, list[str]] = {}
    for row in stale:
        by_binding.setdefault(str(row["binding_id"]), []).append(
            str(row["attachment_id"])
        )
    for binding, attachment_ids in by_binding.items():
        try:
            unbind_run_attachments(
                data_dir,
                binding,
                attachment_ids=attachment_ids,
            )
        except AttachmentError:
            # Startup reconciliation removes an unreferenced binding later.
            pass


@_serialized
def import_remote_task_artifacts(
    data_dir: Path,
    *,
    mentat_task_id: str,
    connection_binding_id: str,
    board: str,
    remote_task_id: str,
    adapter: Any,
) -> dict[str, Any]:
    """Import all safe files from one verified remote manifest.

    A failed file is never published. Other independently verified files may
    remain available, with a partial status returned to the caller.
    """
    manifest = adapter.list_artifacts(board, remote_task_id)
    if not manifest.get("ok"):
        return {
            "state": "unsupported"
            if (manifest.get("error") or {}).get("code")
            == "remote_run_capability_unavailable"
            else "error",
            "accepted_count": len(
                list_task_artifacts(
                    data_dir,
                    mentat_task_id,
                    connection_binding_id=connection_binding_id,
                    board=board,
                    remote_task_id=remote_task_id,
                )
            ),
            "rejected_count": 0,
        }
    candidates = manifest.get("artifacts")
    if (
        not isinstance(candidates, list)
        or len(candidates) > MAX_ARTIFACT_COUNT
        or sum(int(item.get("byte_size") or 0) for item in candidates)
        > MAX_TASK_BYTES
    ):
        return {
            "state": "error",
            "accepted_count": len(
                list_task_artifacts(
                    data_dir,
                    mentat_task_id,
                    connection_binding_id=connection_binding_id,
                    board=board,
                    remote_task_id=remote_task_id,
                )
            ),
            "rejected_count": max(1, len(candidates) if isinstance(candidates, list) else 1),
        }

    binding = _binding_id(
        str(mentat_task_id),
        str(connection_binding_id),
        str(board),
        str(remote_task_id),
    )
    manifest_ids = {
        str(artifact.get("id") or "")
        for artifact in candidates
    }
    failed = 0
    for ordinal, artifact in enumerate(candidates):
        remote_artifact_id = str(artifact.get("id") or "")
        connection = connect(data_dir)
        try:
            existing = connection.execute(
                "SELECT attachment_id, binding_id FROM task_artifacts "
                "WHERE mentat_task_id = ? AND connection_binding_id = ? "
                "AND board_id = ? AND remote_task_id = ? "
                "AND remote_artifact_id = ?",
                (
                    str(mentat_task_id),
                    str(connection_binding_id),
                    str(board),
                    str(remote_task_id),
                    remote_artifact_id,
                ),
            ).fetchone()
        finally:
            connection.close()
        if existing is not None:
            try:
                resolve_blob_path(data_dir, str(existing["attachment_id"]))
                continue
            except (AttachmentError, OSError):
                connection = connect(data_dir)
                try:
                    with transaction(connection, immediate=True):
                        connection.execute(
                            "DELETE FROM task_artifacts "
                            "WHERE mentat_task_id = ? "
                            "AND connection_binding_id = ? AND board_id = ? "
                            "AND remote_task_id = ? AND remote_artifact_id = ? "
                            "AND attachment_id = ?",
                            (
                                str(mentat_task_id),
                                str(connection_binding_id),
                                str(board),
                                str(remote_task_id),
                                remote_artifact_id,
                                str(existing["attachment_id"]),
                            ),
                        )
                finally:
                    connection.close()
                try:
                    unbind_run_attachments(
                        data_dir,
                        str(existing["binding_id"]),
                        attachment_ids=[str(existing["attachment_id"])],
                    )
                except AttachmentError:
                    pass
        result = adapter.download_artifact(board, remote_task_id, artifact)
        if not result.get("ok"):
            failed += 1
            continue
        stream = result.get("stream")
        content = result.get("content")
        if stream is None and not isinstance(content, bytes):
            failed += 1
            continue
        if isinstance(content, bytes) and (
            len(content) != int(artifact.get("byte_size") or -1)
            or len(content) > MAX_ARTIFACT_BYTES
        ):
            failed += 1
            continue
        attachment_id = ""
        try:
            stored = create_attachment(
                data_dir,
                original_name=str(artifact.get("name") or ""),
                content=content if isinstance(content, bytes) else None,
                stream=stream if content is None else None,
                content_type=str(artifact.get("mime_type") or ""),
                image_max_bytes=MAX_ARTIFACT_BYTES,
                text_max_bytes=MAX_ARTIFACT_BYTES,
            )
            attachment_id = str(stored["id"])
            bind_run_attachment(
                data_dir,
                attachment_id,
                binding,
                direction="output",
                ordinal=ordinal,
            )
            connection = connect(data_dir)
            try:
                with transaction(connection, immediate=True):
                    connection.execute(
                        "INSERT INTO task_artifacts "
                        "(mentat_task_id, connection_binding_id, board_id, "
                        "remote_task_id, remote_artifact_id, attachment_id, "
                        "binding_id, ordinal, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(mentat_task_id),
                            str(connection_binding_id),
                            str(board),
                            str(remote_task_id),
                            remote_artifact_id,
                            attachment_id,
                            binding,
                            ordinal,
                            time.time(),
                        ),
                    )
            finally:
                connection.close()
        except (AttachmentError, KeyError, TypeError, ValueError, sqlite3.Error):
            failed += 1
            if attachment_id:
                try:
                    unbind_run_attachments(
                        data_dir,
                        binding,
                        attachment_ids=[attachment_id],
                    )
                except AttachmentError:
                    pass
        finally:
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    _reconcile_mappings(
        data_dir,
        mentat_task_id=str(mentat_task_id),
        connection_binding_id=str(connection_binding_id),
        board=str(board),
        remote_task_id=str(remote_task_id),
        keep_remote_artifact_ids=manifest_ids,
    )
    accepted = len(
        list_task_artifacts(
            data_dir,
            mentat_task_id,
            connection_binding_id=connection_binding_id,
            board=board,
            remote_task_id=remote_task_id,
        )
    )
    rejected = int(manifest.get("rejected_count") or 0) + failed
    return {
        "state": "partial" if rejected else "synced",
        "accepted_count": accepted,
        "rejected_count": rejected,
    }


@_serialized
def remove_task_artifacts(data_dir: Path, mentat_task_id: str) -> int:
    connection = connect(data_dir)
    try:
        rows = connection.execute(
            "SELECT DISTINCT binding_id FROM task_artifacts "
            "WHERE mentat_task_id = ?",
            (str(mentat_task_id),),
        ).fetchall()
        with transaction(connection, immediate=True):
            cursor = connection.execute(
                "DELETE FROM task_artifacts WHERE mentat_task_id = ?",
                (str(mentat_task_id),),
            )
            removed = max(0, int(cursor.rowcount))
    finally:
        connection.close()
    for row in rows:
        try:
            unbind_run_attachments(data_dir, str(row["binding_id"]))
        except AttachmentError:
            pass
    return removed
