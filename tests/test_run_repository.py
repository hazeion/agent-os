from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from agent_console_attachments import bind_run_attachment, create_attachment
from agent_run_history import save_run_summaries
from agent_runtime import (
    AgentEvent,
    AgentEventType,
    AgentRun,
    RunStatus,
    SubmissionDisposition,
    SubmissionOutcome,
)
from mentat_db import SCHEMA_VERSION, connect
from private_state import history_path
from private_console_unit import PrivateConsoleUnitError, capture_private_console_unit
import run_repository
import server
from run_repository import (
    RunRepository,
    RunRepositoryConflict,
    RunRepositoryError,
    RunRepositoryValidationError,
    load_authoritative_run_summaries,
    save_authoritative_run_summaries,
    runtime_binding_digest,
)
from tests.sqlite_authority_support import ensure_run_sqlite_authority


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def timestamp(offset: int = 0) -> str:
    return (NOW + timedelta(seconds=offset)).isoformat()


def run_fixture(
    run_id: str,
    *,
    status: str = "completed",
    offset: int = 0,
    bound: bool = True,
) -> dict:
    run = {
        "id": run_id,
        "runtime_type": "hermes",
        "agent_id": "profile-main",
        "agent_name": "Hermes",
        "model": "provider/model",
        "transport_mode": "local",
        "connection_binding_id": "local-default",
        "status": status,
        "prompt": "Do the work",
        "response": "Finished" if status == "completed" else "",
        "error": "",
        "events": [],
        "created_at": timestamp(offset),
        "updated_at": timestamp(offset + 1),
        "started_at": timestamp(offset),
        "completed_at": timestamp(offset + 1) if status == "completed" else None,
        "attachments": [],
        "artifacts": [],
    }
    if bound:
        run.update({"mentat_agent_id": "agent-main", "task_id": "task-main"})
    return run


def task_fixture() -> dict:
    return {
        "id": "task-dispatch",
        "title": "Dispatch task",
        "description": "Perform bounded work.",
        "project": "Mentat",
        "status": "todo",
        "priority": "medium",
        "assignee": None,
        "assigned_agent_id": "agent-main",
        "due_date": None,
        "source": "test",
        "tags": ["dispatch"],
        "review_required": False,
        "needs_attention": False,
        "created_at": timestamp(),
        "updated_at": timestamp(),
        "completed_at": None,
    }


class RunRepositoryTests(unittest.TestCase):
    def prepare_dispatch_root(self, root: Path) -> tuple[dict, str]:
        task = task_fixture()
        source = root / "tasks.json"
        source.write_text(json.dumps([task], sort_keys=True) + "\n", encoding="utf-8")
        source.chmod(0o600)
        ensure_run_sqlite_authority(root, history_path(root))
        digest = runtime_binding_digest(
            agent_id="agent-main",
            runtime_type="hermes",
            runtime_config_id="config-main",
            runtime_agent_ref="profile-main",
            capabilities=("run.start",),
        )
        return task, digest

    def test_current_schema_keeps_exact_run_event_and_dispatch_tables(self):
        with TemporaryDirectory() as tmpdir:
            connection = connect(Path(tmpdir))
            try:
                version = int(
                    connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                )
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                connection.close()

        self.assertEqual(SCHEMA_VERSION, 18)
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertTrue(
            {
                "mentat_run_store_state",
                "mentat_runs",
                "mentat_agent_events",
                "mentat_dispatch_reservations",
                "mentat_conversation_submission_results",
                "mentat_conversation_run_attempts",
                "mentat_conversation_run_contexts",
            }.issubset(tables)
        )

    def test_projection_omits_unbound_legacy_media_but_keeps_bound_media(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_id = "run_legacy_media_projection"
            retained_input = create_attachment(
                root,
                original_name="input.txt",
                content=b"retained input",
            )
            retained_input = bind_run_attachment(
                root,
                retained_input["id"],
                run_id,
                direction="input",
            )
            retained_output = create_attachment(
                root,
                original_name="report.txt",
                content=b"retained output",
            )
            retained_output = bind_run_attachment(
                root,
                retained_output["id"],
                run_id,
                direction="output",
            )
            stale_input = {
                **retained_input,
                "id": "attachment_" + ("a" * 32),
                "content_url": "/api/agent-console/attachments/attachment_"
                + ("a" * 32)
                + "/content",
            }
            stale_output = {
                **retained_output,
                "id": "attachment_" + ("b" * 32),
                "content_url": "/api/agent-console/attachments/attachment_"
                + ("b" * 32)
                + "/content",
            }
            run = run_fixture(run_id)
            run["attachments"] = [retained_input, stale_input]
            run["artifacts"] = [
                {**retained_output, "kind": "code"},
                {**stale_output, "kind": "code"},
            ]
            save_run_summaries(history_path(root), [run])

            ensure_run_sqlite_authority(root, history_path(root))
            loaded = load_authoritative_run_summaries(root)
            unit = capture_private_console_unit(root)
            projected = json.loads(unit.history_raw)["runs"]

        self.assertEqual(
            [item["id"] for item in loaded[0]["attachments"]],
            [retained_input["id"]],
        )
        self.assertEqual(
            [item["id"] for item in loaded[0]["artifacts"]],
            [retained_output["id"]],
        )
        self.assertEqual(loaded[0]["artifacts"][0]["kind"], "code")
        self.assertEqual(
            [item["id"] for item in projected[0]["attachments"]],
            [retained_input["id"]],
        )
        self.assertEqual(
            [item["id"] for item in projected[0]["artifacts"]],
            [retained_output["id"]],
        )
        self.assertEqual(len(unit.blobs), 2)

    def test_exact_schema_fingerprint_rejects_missing_active_run_index(self):
        with TemporaryDirectory() as tmpdir:
            connection = connect(Path(tmpdir))
            try:
                connection.execute("DROP INDEX idx_mentat_runs_one_active_task")
                with self.assertRaisesRegex(
                    RunRepositoryError, "run_repository.schema_unsupported"
                ):
                    RunRepository(connection)
            finally:
                connection.close()

    def test_absent_history_claims_empty_authority_once(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            receipt = ensure_run_sqlite_authority(root, history_path(root))
            repeated = ensure_run_sqlite_authority(root, history_path(root))
            connection = connect(root)
            try:
                counts = RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(receipt.source_run_count, 0)
        self.assertEqual(repeated, receipt)
        self.assertEqual(counts, (0, 0, 0))

    def test_valid_legacy_history_imports_once_and_stale_json_is_ignored(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = history_path(root)
            run = run_fixture("run_imported")
            run["events"] = [
                {
                    "id": "event_imported_1",
                    "run_id": "run_imported",
                    "sequence": 1,
                    "cursor": 1,
                    "type": "complete",
                    "kind": "complete",
                    "timestamp": timestamp(1),
                    "display_text": "Response complete",
                    "message": "Response complete",
                    "data": {},
                }
            ]
            save_run_summaries(path, [run])

            receipt = ensure_run_sqlite_authority(root, path)
            path.write_text(
                json.dumps({"schema_version": 3, "runs": [run_fixture("run_stale")]}),
                encoding="utf-8",
            )
            repeated = ensure_run_sqlite_authority(root, path)
            loaded = load_authoritative_run_summaries(root)

        self.assertEqual(receipt, repeated)
        self.assertEqual(receipt.source_run_count, 1)
        self.assertEqual([item["id"] for item in loaded], ["run_imported"])
        self.assertEqual(loaded[0]["events"][0]["type"], "complete")

    def test_valid_retained_schema_three_suffix_migrates_without_inventing_events(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = history_path(root)
            run = run_fixture("run_retained_suffix")
            run["events"] = [
                {
                    "id": f"event_suffix_{sequence}",
                    "run_id": "run_retained_suffix",
                    "sequence": sequence,
                    "cursor": sequence,
                    "type": "status",
                    "kind": "status",
                    "timestamp": timestamp(sequence),
                    "display_text": f"Update {sequence}",
                    "message": f"Update {sequence}",
                    "data": {},
                }
                for sequence in range(1, 101)
            ]
            save_run_summaries(path, [run])

            ensure_run_sqlite_authority(root, path)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                stored = repository.get_run("run_retained_suffix")
                events, reset, cursor = repository.list_events(
                    stored.id, after_sequence=0
                )
            finally:
                connection.close()

        self.assertEqual([event.sequence for event in events], list(range(61, 101)))
        self.assertTrue(stored.timeline_truncated)
        self.assertEqual(stored.first_retained_sequence, 61)
        self.assertEqual(stored.last_removed_sequence, 60)
        self.assertTrue(reset)
        self.assertEqual(cursor, 100)

    def test_schema_three_migrates_every_canonical_event_type_exactly(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = history_path(root)
            run = run_fixture("run_canonical_types")
            expected_types = list(AgentEventType)
            run["events"] = [
                {
                    "id": f"event_canonical_{sequence}",
                    "run_id": run["id"],
                    "sequence": sequence,
                    "cursor": sequence,
                    "type": event_type.value,
                    "kind": event_type.value,
                    "timestamp": timestamp(sequence),
                    "display_text": f"Canonical {event_type.value}",
                    "message": f"Canonical {event_type.value}",
                    "data": {},
                }
                for sequence, event_type in enumerate(expected_types, start=1)
            ]
            save_run_summaries(path, [run])

            ensure_run_sqlite_authority(root, path)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                events, _reset, _cursor = repository.list_events(run["id"])
                repository.validate()
            finally:
                connection.close()
            unit = capture_private_console_unit(root)

        self.assertEqual([event.type for event in events], expected_types)
        self.assertEqual(unit.run_count, 1)

    def test_pinned_binding_event_before_retained_suffix_migrates_exact_suffix(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = history_path(root)
            run = run_fixture("run_pinned_suffix")
            run["events"] = [
                {
                    "id": f"event_pinned_{sequence}",
                    "run_id": "run_pinned_suffix",
                    "sequence": sequence,
                    "cursor": sequence,
                    "type": "runtime.bound" if sequence == 1 else "status",
                    "kind": "runtime.bound" if sequence == 1 else "status",
                    "timestamp": timestamp(sequence),
                    "display_text": "Mentat task bound" if sequence == 1 else f"Update {sequence}",
                    "message": "Mentat task bound" if sequence == 1 else f"Update {sequence}",
                    "data": (
                        {"mentat_agent_id": "agent-main", "task_id": "task-main"}
                        if sequence == 1
                        else {}
                    ),
                }
                for sequence in range(1, 101)
            ]
            save_run_summaries(path, [run])

            ensure_run_sqlite_authority(root, path)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                stored = repository.get_run("run_pinned_suffix")
                events, reset, cursor = repository.list_events(stored.id)
                repository.validate()
            finally:
                connection.close()
        self.assertEqual([event.sequence for event in events], list(range(62, 101)))
        self.assertEqual(stored.agent_id, "agent-main")
        self.assertEqual(stored.task_id, "task-main")
        self.assertTrue(stored.timeline_truncated)
        self.assertEqual(stored.first_retained_sequence, 62)
        self.assertEqual(stored.last_removed_sequence, 61)
        self.assertTrue(reset)
        self.assertEqual(cursor, 100)

    def test_duplicate_legacy_run_ids_fail_before_authority_claim(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = history_path(root)
            duplicate = run_fixture("run_duplicate")
            save_run_summaries(path, [duplicate, duplicate])

            with self.assertRaises(RunRepositoryValidationError):
                ensure_run_sqlite_authority(root, path)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                self.assertIsNone(repository.authority_receipt())
                self.assertEqual(repository.list_runs(), ())
            finally:
                connection.close()

    def test_legacy_v2_timeline_is_not_synthesized_and_is_marked_truncated(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = history_path(root)
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "runs": [
                            {
                                "id": "run_legacy_v2",
                                "status": "completed",
                                "prompt_excerpt": "hello",
                                "response_excerpt": "done",
                                "error_excerpt": "",
                                "created_at": timestamp(),
                                "updated_at": timestamp(1),
                                "completed_at": timestamp(1),
                                "events": [
                                    {
                                        "message": "old event without identity",
                                        "timestamp": timestamp(),
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            path.chmod(0o600)

            ensure_run_sqlite_authority(root, path)
            connection = connect(root)
            try:
                run = RunRepository(connection).get_run("run_legacy_v2")
                events, reset, cursor = RunRepository(connection).list_events(
                    "run_legacy_v2"
                )
            finally:
                connection.close()

        self.assertTrue(run.timeline_truncated)
        self.assertEqual(events, ())
        self.assertTrue(reset)
        self.assertEqual(cursor, 0)

    def test_active_legacy_run_becomes_durable_interrupted_not_running(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = history_path(root)
            active = run_fixture("run_legacy_active", status="running")
            active["completed_at"] = None
            save_run_summaries(path, [active])

            ensure_run_sqlite_authority(root, path)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                run = repository.get_run("run_legacy_active")
                events, _reset, _cursor = repository.list_events(run.id)
            finally:
                connection.close()

        self.assertEqual(run.status, "interrupted")
        self.assertTrue(run.partial)
        self.assertEqual(events[-1].type, AgentEventType.RUN_INTERRUPTED)

    def test_workspace_runs_keep_active_work_ahead_of_newer_terminal_history(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                active = run_fixture(
                    "run_active_workspace", status="running", offset=-100
                )
                active["completed_at"] = None
                terminal = [
                    run_fixture(f"run_terminal_{index:02d}", offset=index)
                    for index in range(51)
                ]
                repository.sync_summaries([active, *terminal])

                visible = repository.list_workspace_runs(limit=50)
            finally:
                connection.close()

        self.assertEqual(len(visible), 50)
        self.assertEqual(visible[0].id, "run_active_workspace")
        self.assertEqual(visible[0].status, "running")
        self.assertNotIn("run_terminal_00", {run.id for run in visible})

    @unittest.skipIf(os.name == "nt", "POSIX link semantics")
    def test_linked_legacy_history_fails_before_authority_claim(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = history_path(root)
            path.parent.mkdir(parents=True)
            target = root / "history-target.json"
            target.write_text('{"schema_version":3,"runs":[]}', encoding="utf-8")
            target.chmod(0o600)
            path.symlink_to(target)

            with self.assertRaises(RunRepositoryValidationError):
                ensure_run_sqlite_authority(root, path)
            connection = connect(root)
            try:
                self.assertIsNone(RunRepository(connection).authority_receipt())
            finally:
                connection.close()

    @unittest.skipIf(os.name == "nt", "POSIX hardlink semantics")
    def test_hardlinked_legacy_history_is_rejected_without_changing_external_inode(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = history_path(root)
            path.parent.mkdir(parents=True)
            target = root / "outside-history.json"
            original = b'{"schema_version":3,"runs":[]}'
            target.write_bytes(original)
            target.chmod(0o644)
            os.link(target, path)
            before_mode = stat.S_IMODE(target.stat().st_mode)

            with self.assertRaises(RunRepositoryValidationError):
                ensure_run_sqlite_authority(root, path)

            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), before_mode)

    def test_malformed_nonempty_history_fails_without_claiming_authority(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = history_path(root)
            path.parent.mkdir(parents=True)
            path.write_text('{"schema_version":3,"runs":["bad"]}', encoding="utf-8")

            with self.assertRaises(RunRepositoryValidationError):
                ensure_run_sqlite_authority(root, path)
            connection = connect(root)
            try:
                receipt = RunRepository(connection).authority_receipt()
                count = connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0]
            finally:
                connection.close()

        self.assertIsNone(receipt)
        self.assertEqual(count, 0)

    def test_summary_sync_round_trips_from_sqlite_without_touching_history(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = history_path(root)
            ensure_run_sqlite_authority(root, path)
            run = run_fixture("run_round_trip", status="running")
            run["completed_at"] = None
            run["events"] = [
                {
                    "id": "event_round_trip_1",
                    "run_id": "run_round_trip",
                    "sequence": 1,
                    "cursor": 1,
                    "type": "status",
                    "kind": "status",
                    "timestamp": timestamp(),
                    "display_text": "Working",
                    "message": "Working",
                    "data": {"phase": "inference"},
                }
            ]
            save_authoritative_run_summaries(root, [run])
            self.assertFalse(path.exists())
            loaded = load_authoritative_run_summaries(root)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["id"], "run_round_trip")
        self.assertEqual(loaded[0]["events"][0]["data"], {"phase": "inference"})

    def test_live_rolling_event_window_appends_without_resetting_durable_cursor(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            run = run_fixture("run_rolling_window", status="running")

            def event(sequence: int) -> dict:
                return {
                    "id": f"event_rolling_{sequence}",
                    "run_id": "run_rolling_window",
                    "sequence": sequence,
                    "cursor": sequence,
                    "type": "status",
                    "kind": "status",
                    "timestamp": timestamp(sequence),
                    "display_text": f"Update {sequence}",
                    "message": f"Update {sequence}",
                    "data": {},
                }

            run["events"] = [event(sequence) for sequence in range(1, 41)]
            save_authoritative_run_summaries(root, [run])
            run["events"] = [event(sequence) for sequence in range(2, 42)]
            save_authoritative_run_summaries(root, [run])
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                stored = repository.get_run(run["id"])
                events, reset, cursor = repository.list_events(run["id"])
                repository.validate()
            finally:
                connection.close()
        self.assertEqual([item.sequence for item in events], list(range(1, 42)))
        self.assertEqual(stored.last_event_sequence, 41)
        self.assertFalse(stored.timeline_truncated)
        self.assertFalse(reset)
        self.assertEqual(cursor, 41)

    def test_domain_event_retry_is_idempotent_and_conflict_fails_closed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(root, [run_fixture("run_events", status="running")])
            event = AgentEvent(
                id="event-domain-1",
                run_id="run_events",
                sequence=1,
                type=AgentEventType.MESSAGE,
                occurred_at=timestamp(),
                summary="Working",
                content="Safe progress",
            )
            changed = AgentEvent(
                id=event.id,
                run_id=event.run_id,
                sequence=event.sequence,
                type=event.type,
                occurred_at=event.occurred_at,
                summary="Different",
                content=event.content,
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                self.assertTrue(repository.append_event(event))
                self.assertFalse(repository.append_event(event))
                with self.assertRaises(RunRepositoryConflict):
                    repository.append_event(changed)
                events, reset, cursor = repository.list_events("run_events")
            finally:
                connection.close()

        self.assertEqual(len(events), 1)
        self.assertFalse(reset)
        self.assertEqual(cursor, 1)

    def test_concurrent_identical_event_append_commits_once(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(
                root, [run_fixture("run_concurrent_event", status="running")]
            )
            event = AgentEvent(
                id="event-concurrent-1",
                run_id="run_concurrent_event",
                sequence=1,
                type=AgentEventType.MESSAGE,
                occurred_at=timestamp(),
                summary="Concurrent progress",
            )
            barrier = threading.Barrier(3)
            results = []
            errors = []

            def append():
                connection = connect(root)
                try:
                    barrier.wait(timeout=5)
                    results.append(RunRepository(connection).append_event(event))
                except Exception as exc:  # pragma: no cover - surfaced below
                    errors.append(exc)
                finally:
                    connection.close()

            workers = [threading.Thread(target=append) for _ in range(2)]
            for worker in workers:
                worker.start()
            barrier.wait(timeout=5)
            for worker in workers:
                worker.join(timeout=5)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                events, _reset, _cursor = repository.list_events(event.run_id)
                repository.validate()
            finally:
                connection.close()

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertCountEqual(results, [True, False])
        self.assertEqual(len(events), 1)

    def test_event_retention_marks_timeline_and_reports_cursor_gap(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository, "EVENT_COUNT_RETENTION", 3
        ):
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(root, [run_fixture("run_compact", status="running")])
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                for sequence in range(1, 6):
                    repository.append_event(
                        AgentEvent(
                            id=f"event-compact-{sequence}",
                            run_id="run_compact",
                            sequence=sequence,
                            type=AgentEventType.MESSAGE,
                            occurred_at=timestamp(sequence),
                            summary=f"Update {sequence}",
                        )
                    )
                events, reset, cursor = repository.list_events(
                    "run_compact", after_sequence=0
                )
            finally:
                connection.close()

        self.assertEqual([event.sequence for event in events], [3, 4, 5])
        self.assertTrue(reset)
        self.assertEqual(cursor, 5)

    def test_global_event_retention_runs_on_direct_append(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository, "GLOBAL_EVENT_COUNT_RETENTION", 2
        ):
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(
                root,
                [
                    run_fixture("run_global_a", status="running", offset=0),
                    run_fixture("run_global_b", status="running", offset=10),
                ],
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                repository.append_event(
                    AgentEvent(
                        id="event-global-a-1",
                        run_id="run_global_a",
                        sequence=1,
                        type=AgentEventType.MESSAGE,
                        occurred_at=timestamp(20),
                        summary="A1",
                    )
                )
                repository.append_event(
                    AgentEvent(
                        id="event-global-a-2",
                        run_id="run_global_a",
                        sequence=2,
                        type=AgentEventType.MESSAGE,
                        occurred_at=timestamp(21),
                        summary="A2",
                    )
                )
                repository.append_event(
                    AgentEvent(
                        id="event-global-b-1",
                        run_id="run_global_b",
                        sequence=1,
                        type=AgentEventType.MESSAGE,
                        occurred_at=timestamp(22),
                        summary="B1",
                    )
                )
                total = connection.execute(
                    "SELECT COUNT(*) FROM mentat_agent_events"
                ).fetchone()[0]
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(total, 2)

    def test_validation_rejects_bypassed_per_run_retention(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository, "EVENT_COUNT_RETENTION", 1
        ):
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(
                root, [run_fixture("run_bypassed_retention", status="running")]
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                with repository.mutation():
                    repository._append_event_record(
                        run_repository._event_from_domain(
                            AgentEvent(
                                id="event-bypass-1",
                                run_id="run_bypassed_retention",
                                sequence=1,
                                type=AgentEventType.MESSAGE,
                                occurred_at=timestamp(),
                                summary="One",
                            )
                        )
                    )
                    repository._append_event_record(
                        run_repository._event_from_domain(
                            AgentEvent(
                                id="event-bypass-2",
                                run_id="run_bypassed_retention",
                                sequence=2,
                                type=AgentEventType.MESSAGE,
                                occurred_at=timestamp(1),
                                summary="Two",
                            )
                        )
                    )
                with self.assertRaisesRegex(
                    RunRepositoryError, "run_repository.corrupt"
                ):
                    repository.validate()
            finally:
                connection.close()

    def test_run_retention_preserves_active_and_newest_terminal_runs(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository, "TERMINAL_RUN_RETENTION", 2
        ):
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            runs = [
                run_fixture("run_active", status="running", offset=0),
                run_fixture("run_terminal_1", offset=1),
                run_fixture("run_terminal_2", offset=2),
                run_fixture("run_terminal_3", offset=3),
            ]
            runs[0]["completed_at"] = None
            report = save_authoritative_run_summaries(root, runs)
            loaded = load_authoritative_run_summaries(root, limit=4)

        self.assertEqual(report.removed_run_ids, ("run_terminal_1",))
        self.assertEqual(
            {run["id"] for run in loaded},
            {"run_active", "run_terminal_2", "run_terminal_3"},
        )

    def test_submission_outcome_enforces_terminal_run_retention(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository, "TERMINAL_RUN_RETENTION", 2
        ):
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            save_authoritative_run_summaries(
                root,
                [
                    run_fixture("run_old_terminal_1", offset=0),
                    run_fixture("run_old_terminal_2", offset=10),
                ],
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-terminal-retention",
                    dispatch_id="dispatch-terminal-retention",
                    run_id="run_dispatch_terminal_retention",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                    now=timestamp(20),
                )
                repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=binding_digest,
                    now=timestamp(21),
                )
                repository.record_submission_outcome(
                    dispatch_id=reservation.dispatch_id,
                    outcome=SubmissionOutcome(SubmissionDisposition.REJECTED),
                    now=timestamp(22),
                )
                terminal_ids = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT id FROM mentat_runs WHERE status NOT IN ("
                        + ",".join("?" for _ in run_repository._ACTIVE_STATUSES)
                        + ")",
                        tuple(sorted(run_repository._ACTIVE_STATUSES)),
                    )
                }
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(len(terminal_ids), 2)
        self.assertIn(reservation.run_id, terminal_ids)
        self.assertNotIn("run_old_terminal_1", terminal_ids)

    def test_dispatch_reservation_is_atomic_idempotent_and_revision_consuming(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                first = repository.reserve_dispatch(
                    idempotency_key="request-key-0001",
                    dispatch_id="dispatch-0001",
                    run_id="run_dispatch_0001",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                    now=timestamp(),
                )
                duplicate = repository.reserve_dispatch(
                    idempotency_key="request-key-0001",
                    dispatch_id="dispatch-ignored",
                    run_id="run_dispatch_ignored",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                    now=timestamp(),
                )
                with self.assertRaises(RunRepositoryConflict):
                    repository.reserve_dispatch(
                        idempotency_key="request-key-0002",
                        dispatch_id="dispatch-0002",
                        run_id="run_dispatch_0002",
                        task=task,
                        task_revision=1,
                        agent_id="agent-main",
                        runtime_type="hermes",
                        runtime_config_id="config-main",
                        binding_digest=binding_digest,
                        capabilities=("run.start",),
                        now=timestamp(),
                    )
                stored = repository.get_run(first.run_id)
                events, reset, cursor = repository.list_events(first.run_id)
            finally:
                connection.close()

        self.assertFalse(first.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.run_id, first.run_id)
        self.assertEqual(stored.status, "reserved")
        self.assertEqual(events[0].type, AgentEventType.DISPATCH_RESERVED)
        self.assertFalse(reset)
        self.assertEqual(cursor, 1)

    def test_dispatch_identifier_boundary_does_not_expand_event_identifier(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-dispatch-id-boundary",
                    dispatch_id="d" * 128,
                    run_id="run_dispatch_id_boundary",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                events, _reset, _cursor = repository.list_events(reservation.run_id)
                repository.validate()
                with self.assertRaisesRegex(
                    RunRepositoryValidationError, "run.identifier_invalid"
                ):
                    repository.reserve_dispatch(
                        idempotency_key="request-key-dispatch-id-too-wide",
                        dispatch_id="d" * 129,
                        run_id="run_dispatch_id_too_wide",
                        task=task,
                        task_revision=1,
                        agent_id="agent-main",
                        runtime_type="hermes",
                        runtime_config_id="config-main",
                        binding_digest=binding_digest,
                        capabilities=("run.start",),
                    )
            finally:
                connection.close()

        self.assertEqual(len(events), 1)
        self.assertLessEqual(len(events[0].id), 128)

    def test_validation_and_backup_reject_unapproved_run_detail_fields(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-corrupt-details",
                    dispatch_id="dispatch-corrupt-details",
                    run_id="run_corrupt_details",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                details = json.loads(
                    connection.execute(
                        "SELECT details_json FROM mentat_runs WHERE id = ?",
                        (reservation.run_id,),
                    ).fetchone()[0]
                )
                details["credential"] = "private-value"
                connection.execute(
                    "UPDATE mentat_runs SET details_json = ? WHERE id = ?",
                    (json.dumps(details, sort_keys=True, separators=(",", ":")), reservation.run_id),
                )
                connection.commit()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.validate()
            finally:
                connection.close()
            with self.assertRaisesRegex(
                PrivateConsoleUnitError, "private_run_repository_invalid"
            ):
                capture_private_console_unit(root)

    def test_validation_rejects_nested_private_attachment_metadata(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-nested-attachment",
                    dispatch_id="dispatch-nested-attachment",
                    run_id="run_nested_attachment",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                details = json.loads(
                    connection.execute(
                        "SELECT details_json FROM mentat_runs WHERE id = ?",
                        (reservation.run_id,),
                    ).fetchone()[0]
                )
                details["attachments"] = [{
                    "id": "attachment_" + ("a" * 32),
                    "name": "note.txt",
                    "mime_type": "text/plain",
                    "kind": "text",
                    "byte_size": 12,
                    "state": "attached",
                    "created_at": {"credential": "super-secret-value"},
                    "expires_at": None,
                    "content_url": "/api/agent-console/attachments/attachment_"
                    + ("a" * 32) + "/content",
                }]
                connection.execute(
                    "UPDATE mentat_runs SET details_json = ? WHERE id = ?",
                    (json.dumps(details, sort_keys=True, separators=(",", ":")), reservation.run_id),
                )
                connection.commit()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.validate()
            finally:
                connection.close()
            with self.assertRaisesRegex(
                PrivateConsoleUnitError, "private_run_repository_invalid"
            ):
                capture_private_console_unit(root)

    def test_authoritative_read_paths_validate_runs_and_events_before_projection(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(root, [run_fixture("run_read_validation")])
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                details = json.loads(
                    connection.execute(
                        "SELECT details_json FROM mentat_runs WHERE id = 'run_read_validation'"
                    ).fetchone()[0]
                )
                details["prompt_excerpt"] = "api_key=abcdefghijklmnop"
                connection.execute(
                    "UPDATE mentat_runs SET details_json = ? WHERE id = 'run_read_validation'",
                    (json.dumps(details, sort_keys=True, separators=(",", ":")),),
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                load_authoritative_run_summaries(root)

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-event-read-validation",
                    dispatch_id="dispatch-event-read-validation",
                    run_id="run_event_read_validation",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                connection.execute(
                    "UPDATE mentat_agent_events SET summary = ? WHERE run_id = ?",
                    ("token=abcdefghijklmnop", reservation.run_id),
                )
                connection.commit()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.list_events(reservation.run_id)
            finally:
                connection.close()

    def test_public_event_presentation_uses_only_validated_source_classes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            run = run_fixture("run_safe_presentation", status="running")
            run["events"] = [
                {
                    "id": "event_tool_started",
                    "run_id": run["id"],
                    "sequence": 1,
                    "cursor": 1,
                    "type": "tool.started",
                    "kind": "tool.started",
                    "timestamp": timestamp(1),
                    "data": {
                        "tool": "shell",
                        "arguments": "DO_NOT_PROJECT_ARGUMENTS",
                        "result": "DO_NOT_PROJECT_RESULTS",
                    },
                    "display_text": "DO_NOT_PROJECT_TOOL_SUMMARY",
                    "message": "DO_NOT_PROJECT_TOOL_MESSAGE",
                },
                {
                    "id": "event_reasoning_available",
                    "run_id": run["id"],
                    "sequence": 2,
                    "cursor": 2,
                    "type": "reasoning.available",
                    "kind": "reasoning.available",
                    "timestamp": timestamp(2),
                    "data": {"reasoning": "DO_NOT_PROJECT_RAW_REASONING"},
                    "display_text": "DO_NOT_PROJECT_REASONING_SUMMARY",
                    "message": "DO_NOT_PROJECT_REASONING_MESSAGE",
                },
                {
                    "id": "event_hostile_lookalike",
                    "run_id": run["id"],
                    "sequence": 3,
                    "cursor": 3,
                    "type": "reasoning.summary",
                    "kind": "reasoning.summary",
                    "timestamp": timestamp(3),
                    "data": {},
                    "display_text": "Ordinary status remains ordinary",
                    "message": "Ordinary status remains ordinary",
                },
            ]
            save_authoritative_run_summaries(root, [run])

            with patch.object(server, "DATA_DIR", root):
                payload = server.mentat_run_events_payload(run["id"], 0)

        self.assertEqual(
            payload["events"][0]["presentation"],
            {
                "kind": "tool",
                "phase": "started",
                "label": "Tool activity started",
            },
        )
        self.assertEqual(
            payload["events"][1]["presentation"],
            {
                "kind": "reasoning",
                "phase": "available",
                "label": "Reasoning summary available",
            },
        )
        self.assertIsNone(payload["events"][2]["presentation"])
        serialized = json.dumps(payload)
        for private_value in (
            "DO_NOT_PROJECT_ARGUMENTS",
            "DO_NOT_PROJECT_RESULTS",
            "DO_NOT_PROJECT_TOOL_SUMMARY",
            "DO_NOT_PROJECT_TOOL_MESSAGE",
            "DO_NOT_PROJECT_RAW_REASONING",
            "DO_NOT_PROJECT_REASONING_SUMMARY",
            "DO_NOT_PROJECT_REASONING_MESSAGE",
        ):
            self.assertNotIn(private_value, serialized)

    def test_console_summary_validates_event_digest_before_hydration(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            run = run_fixture("run_console_event_validation")
            run["events"] = [{
                "id": "event_console_safe",
                "run_id": run["id"],
                "sequence": 1,
                "cursor": 1,
                "type": "message",
                "kind": "message",
                "timestamp": timestamp(1),
                "data": {},
                "display_text": "Safe event",
                "message": "Safe event",
            }]
            save_authoritative_run_summaries(root, [run])
            connection = connect(root)
            try:
                connection.execute(
                    "UPDATE mentat_agent_events SET data_json = ? WHERE run_id = ?",
                    ('{"mentat_agent_id":"agent-forged","task_id":"task-victim"}', run["id"]),
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                load_authoritative_run_summaries(root)

    def test_event_reads_reject_an_interior_sequence_gap(self):
        for deleted_sequence in (1, 2):
            with self.subTest(deleted_sequence=deleted_sequence), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                ensure_run_sqlite_authority(root, history_path(root))
                run = run_fixture(f"run_event_gap_{deleted_sequence}")
                run["events"] = [
                    {
                        "id": f"event_gap_{sequence}",
                        "run_id": run["id"],
                        "sequence": sequence,
                        "cursor": sequence,
                        "type": "message",
                        "kind": "message",
                        "timestamp": timestamp(sequence),
                        "data": {},
                        "display_text": f"Event {sequence}",
                        "message": f"Event {sequence}",
                    }
                    for sequence in range(1, 4)
                ]
                save_authoritative_run_summaries(root, [run])
                connection = connect(root)
                try:
                    connection.execute(
                        "DELETE FROM mentat_agent_events WHERE run_id = ? AND sequence = ?",
                        (run["id"], deleted_sequence),
                    )
                    connection.commit()
                    repository = RunRepository(connection)
                    with self.assertRaisesRegex(
                        RunRepositoryError, "run_repository.corrupt"
                    ):
                        repository.list_events(run["id"])
                    with self.assertRaisesRegex(
                        RunRepositoryError, "run_repository.corrupt"
                    ):
                        repository.list_summaries()
                    with self.assertRaisesRegex(
                        RunRepositoryError, "run_repository.corrupt"
                    ):
                        repository.get_run(run["id"])
                    with self.assertRaisesRegex(
                        RunRepositoryError, "run_repository.corrupt"
                    ):
                        repository.list_runs()
                finally:
                    connection.close()

    def test_rehashed_secret_event_text_fails_validation_reads_and_backup(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-rehashed-secret-event",
                    dispatch_id="dispatch-rehashed-secret-event",
                    run_id="run_rehashed_secret_event",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                event = connection.execute(
                    "SELECT * FROM mentat_agent_events WHERE run_id = ?",
                    (reservation.run_id,),
                ).fetchone()
                record = {
                    key: event[key]
                    for key in (
                        "id", "run_id", "sequence", "event_type", "source_type",
                        "source_key", "occurred_at", "summary", "content",
                        "metrics_json", "data_json",
                    )
                }
                record["summary"] = "token=abcdefghijklmnop"
                digest = hashlib.sha256(
                    run_repository._canonical_json(
                        record, maximum=32_768, code="event.invalid"
                    ).encode("ascii")
                ).hexdigest()
                connection.execute(
                    "UPDATE mentat_agent_events SET summary = ?, payload_digest = ? WHERE id = ?",
                    (record["summary"], digest, event["id"]),
                )
                connection.commit()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.validate()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.list_events(reservation.run_id)
            finally:
                connection.close()
            with self.assertRaisesRegex(
                PrivateConsoleUnitError, "private_run_repository_invalid"
            ):
                capture_private_console_unit(root)

    def test_run_authority_requires_task_authority_and_active_task_row(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-authority-closure",
                    dispatch_id="dispatch-authority-closure",
                    run_id="run_authority_closure",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                connection.execute("DELETE FROM mentat_tasks WHERE id = ?", (task["id"],))
                connection.commit()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.validate()
                connection.execute("DELETE FROM mentat_task_store_state")
                connection.commit()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.validate()
            finally:
                connection.close()
            with self.assertRaisesRegex(
                PrivateConsoleUnitError, "private_run_repository_invalid"
            ):
                capture_private_console_unit(root)

    def test_dispatch_attempt_can_be_claimed_only_once_and_records_acceptance(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-accept",
                    dispatch_id="dispatch-accept",
                    run_id="run_dispatch_accept",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                    now=timestamp(),
                )
                claimed = repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=binding_digest,
                    now=timestamp(1),
                )
                with self.assertRaises(RunRepositoryConflict):
                    repository.claim_dispatch_attempt(
                        dispatch_id=reservation.dispatch_id,
                        expected_binding_digest=binding_digest,
                        now=timestamp(2),
                    )
                result = repository.record_submission_outcome(
                    dispatch_id=reservation.dispatch_id,
                    outcome=SubmissionOutcome(
                        SubmissionDisposition.ACCEPTED,
                        run=AgentRun(
                            id=reservation.run_id,
                            task_id=task["id"],
                            agent_id="agent-main",
                            runtime_type="hermes",
                            status=RunStatus.STARTING,
                        ),
                        runtime_run_ref="runtime-ref-1",
                    ),
                    now=timestamp(3),
                )
                events, _reset, cursor = repository.list_events(reservation.run_id)
            finally:
                connection.close()

        self.assertEqual(claimed.attempt_count, 1)
        self.assertEqual(result.status, "starting")
        self.assertEqual(result.dispatch_state, "accepted")
        self.assertEqual(result.runtime_run_ref, "runtime-ref-1")
        self.assertEqual([event.type for event in events], [
            AgentEventType.DISPATCH_RESERVED,
            AgentEventType.RUN_STARTED,
        ])
        self.assertEqual(cursor, 2)

    def test_vercel_result_projection_requires_the_exact_submission_source(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task = task_fixture()
            task["required_capabilities"] = ["model.generate"]
            source = root / "tasks.json"
            source.write_text(
                json.dumps([task], sort_keys=True) + "\n",
                encoding="utf-8",
            )
            source.chmod(0o600)
            ensure_run_sqlite_authority(root, history_path(root))
            binding_digest = runtime_binding_digest(
                agent_id="agent-main",
                runtime_type="vercel",
                runtime_config_id="connection-vercel",
                runtime_agent_ref="connection-vercel",
                capabilities=("model.generate",),
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="vercel-result-source-key",
                    dispatch_id="dispatch-vercel-source",
                    run_id="run_vercel_projection",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="vercel",
                    runtime_config_id="connection-vercel",
                    binding_digest=binding_digest,
                    capabilities=("model.generate",),
                    now=timestamp(),
                )
                repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=binding_digest,
                    now=timestamp(1),
                )
                source_event_id = "vercel_message_" + hashlib.sha256(
                    b"run_vercel_projection:message"
                ).hexdigest()[:24]
                repository.record_submission_outcome(
                    dispatch_id=reservation.dispatch_id,
                    outcome=SubmissionOutcome(
                        SubmissionDisposition.ACCEPTED,
                        run=AgentRun(
                            id=reservation.run_id,
                            task_id=task["id"],
                            agent_id="agent-main",
                            runtime_type="vercel",
                            status=RunStatus.COMPLETED,
                        ),
                        runtime_run_ref="vercel-runtime-reference",
                        initial_events=(
                            AgentEvent(
                                id=source_event_id,
                                run_id=reservation.run_id,
                                sequence=1,
                                type=AgentEventType.MESSAGE,
                                occurred_at=timestamp(2),
                                summary="Vercel AI Gateway returned a response",
                                content="Trusted result.",
                            ),
                        ),
                    ),
                    now=timestamp(2),
                )
                trusted_id = repository.trusted_vercel_result_message_id(
                    reservation.run_id
                )
                row = connection.execute(
                    "SELECT * FROM mentat_agent_events WHERE id = ?",
                    (trusted_id,),
                ).fetchone()
                forged_source = "submission:vercel_message_" + "0" * 24
                digest_payload = {
                    key: (forged_source if key == "source_key" else row[key])
                    for key in (
                        "id",
                        "run_id",
                        "sequence",
                        "event_type",
                        "source_type",
                        "source_key",
                        "occurred_at",
                        "summary",
                        "content",
                        "metrics_json",
                        "data_json",
                    )
                }
                forged_digest = hashlib.sha256(
                    run_repository._canonical_json(
                        digest_payload,
                        maximum=32_768,
                        code="event.invalid",
                    ).encode("ascii")
                ).hexdigest()
                connection.execute(
                    "UPDATE mentat_agent_events SET source_key = ?, "
                    "payload_digest = ? WHERE id = ?",
                    (forged_source, forged_digest, trusted_id),
                )
                repository.list_events(reservation.run_id)
                with self.assertRaisesRegex(RunRepositoryError, "event.corrupt"):
                    repository.trusted_vercel_result_message_id(reservation.run_id)
            finally:
                connection.close()

            with patch.object(server, "DATA_DIR", root), self.assertRaisesRegex(
                RunRepositoryError,
                "event.corrupt",
            ):
                server.mentat_run_events_payload("run_vercel_projection", 0)

    def test_dispatch_claim_revalidates_task_revision_inside_claim_transaction(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-task-race",
                    dispatch_id="dispatch-task-race",
                    run_id="run_dispatch_task_race",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                connection.execute(
                    "UPDATE mentat_tasks SET revision = 2 WHERE id = ?",
                    (task["id"],),
                )
                with self.assertRaisesRegex(
                    RunRepositoryConflict, "dispatch.task_changed"
                ):
                    repository.claim_dispatch_attempt(
                        dispatch_id=reservation.dispatch_id,
                        expected_binding_digest=binding_digest,
                    )
                stored = repository.get_run(reservation.run_id)
            finally:
                connection.close()

        self.assertEqual(stored.status, "reserved")
        self.assertEqual(stored.dispatch_state, "reserved")

    def test_concurrent_task_commit_wins_before_claim_and_blocks_stale_attempt(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                reservation = RunRepository(connection).reserve_dispatch(
                    idempotency_key="request-key-concurrent-task",
                    dispatch_id="dispatch-concurrent-task",
                    run_id="run_dispatch_concurrent_task",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
            finally:
                connection.close()

            mutation_ready = threading.Event()
            release_mutation = threading.Event()
            claim_started = threading.Event()
            errors = []

            def mutate_task():
                mutation_connection = connect(root)
                try:
                    mutation_connection.execute("BEGIN IMMEDIATE")
                    mutation_connection.execute(
                        "UPDATE mentat_tasks SET revision = 2 WHERE id = ?",
                        (task["id"],),
                    )
                    mutation_ready.set()
                    if not release_mutation.wait(timeout=5):
                        raise TimeoutError("mutation release timed out")
                    mutation_connection.commit()
                except Exception as exc:  # pragma: no cover - surfaced below
                    errors.append(exc)
                finally:
                    mutation_connection.close()

            def claim_dispatch():
                claim_connection = connect(root)
                try:
                    claim_started.set()
                    with self.assertRaisesRegex(
                        RunRepositoryConflict, "dispatch.task_changed"
                    ):
                        RunRepository(claim_connection).claim_dispatch_attempt(
                            dispatch_id=reservation.dispatch_id,
                            expected_binding_digest=binding_digest,
                        )
                except Exception as exc:  # pragma: no cover - surfaced below
                    errors.append(exc)
                finally:
                    claim_connection.close()

            mutator = threading.Thread(target=mutate_task)
            claimant = threading.Thread(target=claim_dispatch)
            mutator.start()
            self.assertTrue(mutation_ready.wait(timeout=5))
            claimant.start()
            self.assertTrue(claim_started.wait(timeout=5))
            release_mutation.set()
            mutator.join(timeout=5)
            claimant.join(timeout=5)

            connection = connect(root)
            try:
                stored = RunRepository(connection).get_run(reservation.run_id)
            finally:
                connection.close()

        self.assertFalse(mutator.is_alive())
        self.assertFalse(claimant.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(stored.status, "reserved")

    def test_submission_outcome_rejects_mismatched_domain_identity(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-identity",
                    dispatch_id="dispatch-identity",
                    run_id="run_dispatch_identity",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=binding_digest,
                )
                with self.assertRaisesRegex(
                    RunRepositoryConflict, "dispatch.runtime_identity_mismatch"
                ):
                    repository.record_submission_outcome(
                        dispatch_id=reservation.dispatch_id,
                        outcome=SubmissionOutcome(
                            SubmissionDisposition.ACCEPTED,
                            run=AgentRun(
                                id=reservation.run_id,
                                task_id="task-other",
                                agent_id="agent-main",
                                runtime_type="hermes",
                                status=RunStatus.STARTING,
                            ),
                        ),
                    )
                stored = repository.get_run(reservation.run_id)
            finally:
                connection.close()

        self.assertEqual(stored.status, "submitting")
        self.assertEqual(stored.dispatch_state, "submitting")

    def test_accepted_outcome_preserves_worker_terminal_state(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-worker-race",
                    dispatch_id="dispatch-worker-race",
                    run_id="run_dispatch_worker_race",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                    now=timestamp(),
                )
                repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=binding_digest,
                    now=timestamp(1),
                )
                connection.execute(
                    "UPDATE mentat_runs SET status = 'completed', updated_at = ?, completed_at = ?, "
                    "state_revision = state_revision + 1 WHERE id = ?",
                    (timestamp(3), timestamp(3), reservation.run_id),
                )
                result = repository.record_submission_outcome(
                    dispatch_id=reservation.dispatch_id,
                    outcome=SubmissionOutcome(
                        SubmissionDisposition.ACCEPTED,
                        run=AgentRun(
                            id=reservation.run_id,
                            task_id=task["id"],
                            agent_id="agent-main",
                            runtime_type="hermes",
                            status=RunStatus.STARTING,
                        ),
                        runtime_run_ref="runtime-worker-race",
                    ),
                )
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.dispatch_state, "accepted")

    def test_restart_changes_claimed_submission_to_unknown_without_retry(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-restart",
                    dispatch_id="dispatch-restart",
                    run_id="run_dispatch_restart",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                    now=timestamp(),
                )
                repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=binding_digest,
                    now=timestamp(1),
                )
                recovered = repository.recover_submitting_as_unknown(now=timestamp(2))
                repeated = repository.recover_submitting_as_unknown(now=timestamp(3))
                run = repository.get_run(reservation.run_id)
                events, _reset, _cursor = repository.list_events(reservation.run_id)
            finally:
                connection.close()

        self.assertEqual(recovered, (reservation.run_id,))
        self.assertEqual(repeated, ())
        self.assertEqual(run.status, "unknown")
        self.assertTrue(run.partial)
        self.assertEqual(events[-1].type, AgentEventType.SUBMISSION_UNKNOWN)

    def test_restart_preserves_worker_advanced_submission_and_repairs_dispatch_state(self):
        for advanced_status in ("running", "completed"):
            with self.subTest(advanced_status=advanced_status), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                task, binding_digest = self.prepare_dispatch_root(root)
                connection = connect(root)
                try:
                    repository = RunRepository(connection)
                    reservation = repository.reserve_dispatch(
                        idempotency_key=f"request-key-worker-{advanced_status}",
                        dispatch_id=f"dispatch-worker-{advanced_status}",
                        run_id=f"run_dispatch_worker_{advanced_status}",
                        task=task,
                        task_revision=1,
                        agent_id="agent-main",
                        runtime_type="hermes",
                        runtime_config_id="config-main",
                        binding_digest=binding_digest,
                        capabilities=("run.start",),
                        now=timestamp(),
                    )
                    repository.claim_dispatch_attempt(
                        dispatch_id=reservation.dispatch_id,
                        expected_binding_digest=binding_digest,
                        now=timestamp(1),
                    )
                    connection.execute(
                        "UPDATE mentat_runs SET status = ?, completed_at = ?, "
                        "state_revision = state_revision + 1 WHERE id = ?",
                        (
                            advanced_status,
                            timestamp(2) if advanced_status == "completed" else None,
                            reservation.run_id,
                        ),
                    )
                    recovered = repository.recover_submitting_as_unknown(now=timestamp(3))
                    run = repository.get_run(reservation.run_id)
                    state = connection.execute(
                        "SELECT state FROM mentat_dispatch_reservations WHERE run_id = ?",
                        (reservation.run_id,),
                    ).fetchone()[0]
                    repository.validate()
                finally:
                    connection.close()

                self.assertEqual(recovered, (reservation.run_id,))
                self.assertEqual(run.status, advanced_status)
                self.assertEqual(run.dispatch_state, "accepted")
                self.assertEqual(state, "accepted")

    def test_restart_resolves_never_attempted_reservation_without_submission(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-before-attempt",
                    dispatch_id="dispatch-before-attempt",
                    run_id="run_dispatch_before_attempt",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                    now=timestamp(),
                )
                recovered = repository.recover_reserved_as_interrupted(
                    now=timestamp(2)
                )
                repeated = repository.recover_reserved_as_interrupted(
                    now=timestamp(3)
                )
                run = repository.get_run(reservation.run_id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(recovered, (reservation.run_id,))
        self.assertEqual(repeated, ())
        self.assertEqual(run.status, "interrupted")
        self.assertEqual(run.dispatch_state, "rejected")

    def test_restart_marks_bridge_accepted_run_unknown_without_resubmission(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-accepted-restart",
                    dispatch_id="dispatch-accepted-restart",
                    run_id="run_dispatch_accepted_restart",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                    now=timestamp(),
                )
                repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=binding_digest,
                    now=timestamp(1),
                )
                repository.record_submission_outcome(
                    dispatch_id=reservation.dispatch_id,
                    outcome=SubmissionOutcome(
                        SubmissionDisposition.ACCEPTED,
                        run=AgentRun(
                            id=reservation.run_id,
                            task_id=task["id"],
                            agent_id="agent-main",
                            runtime_type="hermes",
                            status=RunStatus.RUNNING,
                        ),
                    ),
                    now=timestamp(2),
                )
                recovered = repository.recover_unattached_dispatches_as_unknown(
                    now=timestamp(3)
                )
                repeated = repository.recover_unattached_dispatches_as_unknown(
                    now=timestamp(4)
                )
                run = repository.get_run(reservation.run_id)
                events, _reset, _cursor = repository.list_events(reservation.run_id)
            finally:
                connection.close()

        self.assertEqual(recovered, (reservation.run_id,))
        self.assertEqual(repeated, ())
        self.assertEqual(run.status, "unknown")
        self.assertEqual(run.dispatch_state, "unknown")
        self.assertTrue(run.partial)
        self.assertEqual(events[-1].type, AgentEventType.SUBMISSION_UNKNOWN)

    def test_restart_preserves_accepted_run_with_durable_runtime_reference(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-runtime-reference",
                    dispatch_id="dispatch-runtime-reference",
                    run_id="run_dispatch_runtime_reference",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                    now=timestamp(),
                )
                repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=binding_digest,
                    now=timestamp(1),
                )
                repository.record_submission_outcome(
                    dispatch_id=reservation.dispatch_id,
                    outcome=SubmissionOutcome(
                        SubmissionDisposition.ACCEPTED,
                        run=AgentRun(
                            id=reservation.run_id,
                            task_id=task["id"],
                            agent_id="agent-main",
                            runtime_type="hermes",
                            status=RunStatus.RUNNING,
                        ),
                        runtime_run_ref="hermes-runtime-run-1",
                    ),
                    now=timestamp(2),
                )
                recovered = repository.recover_unattached_dispatches_as_unknown(
                    now=timestamp(3)
                )
                run = repository.get_run(reservation.run_id)
            finally:
                connection.close()

        self.assertEqual(recovered, ())
        self.assertEqual(run.status, "running")
        self.assertEqual(run.dispatch_state, "accepted")
        self.assertEqual(run.runtime_run_ref, "hermes-runtime-run-1")

    def test_restart_interrupts_only_active_legacy_console_runs(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(
                root,
                [
                    run_fixture("run_console_active", status="running"),
                    run_fixture("run_console_complete", status="completed", offset=10),
                ],
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                recovered = repository.recover_console_runs_as_interrupted(
                    now=timestamp(20)
                )
                repeated = repository.recover_console_runs_as_interrupted(
                    now=timestamp(21)
                )
                active = repository.get_run("run_console_active")
                complete = repository.get_run("run_console_complete")
                events, _reset, _cursor = repository.list_events("run_console_active")
            finally:
                connection.close()

        self.assertEqual(recovered, ("run_console_active",))
        self.assertEqual(repeated, ())
        self.assertEqual(active.status, "interrupted")
        self.assertTrue(active.partial)
        self.assertEqual(complete.status, "completed")
        self.assertEqual(events[-1].type, AgentEventType.RUN_INTERRUPTED)

    def test_task_dispatch_unknown_is_canonical_but_not_legacy_console_history(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-canonical-unknown",
                    dispatch_id="dispatch-canonical-unknown",
                    run_id="run_canonical_unknown",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=binding_digest,
                )
                repository.record_submission_outcome(
                    dispatch_id=reservation.dispatch_id,
                    outcome=SubmissionOutcome(
                        SubmissionDisposition.UNKNOWN,
                        failure_code="runtime.submission_unknown",
                    ),
                )
                canonical = repository.get_run(reservation.run_id)
                repository.validate()
            finally:
                connection.close()
            compatibility = load_authoritative_run_summaries(root)

        self.assertEqual(canonical.status, "unknown")
        self.assertEqual(compatibility, [])

    def test_terminal_task_dispatch_rejects_stale_console_projection(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-terminal-projection",
                    dispatch_id="dispatch-terminal-projection",
                    run_id="run_terminal_projection",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=binding_digest,
                )
                repository.record_submission_outcome(
                    dispatch_id=reservation.dispatch_id,
                    outcome=SubmissionOutcome(
                        SubmissionDisposition.ACCEPTED,
                        run=AgentRun(
                            id=reservation.run_id,
                            task_id=task["id"],
                            agent_id="agent-main",
                            runtime_type="hermes",
                            status=RunStatus.STARTING,
                        ),
                        runtime_run_ref="runtime-terminal-projection",
                    ),
                )
                canonical = repository.get_run(reservation.run_id)
            finally:
                connection.close()
            completed = run_fixture(reservation.run_id, status="completed")
            completed.update(
                mentat_agent_id="agent-main",
                task_id=task["id"],
                created_at=canonical.created_at,
                updated_at=canonical.updated_at,
                started_at=canonical.started_at,
                completed_at=canonical.updated_at,
            )
            save_authoritative_run_summaries(root, [completed])
            stale = {**completed, "status": "running", "completed_at": None}
            with self.assertRaisesRegex(RunRepositoryConflict, "run.status_regression"):
                save_authoritative_run_summaries(root, [stale])
            connection = connect(root)
            try:
                stored = RunRepository(connection).get_run(reservation.run_id)
            finally:
                connection.close()

        self.assertEqual(stored.status, "completed")
        self.assertIsNotNone(stored.completed_at)

    def test_validation_rejects_coordinated_but_impossible_dispatch_state(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="request-key-impossible-state",
                    dispatch_id="dispatch-impossible-state",
                    run_id="run_impossible_state",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                connection.execute(
                    "UPDATE mentat_runs SET dispatch_state = 'accepted' WHERE id = ?",
                    (reservation.run_id,),
                )
                connection.execute(
                    "UPDATE mentat_dispatch_reservations SET state = 'accepted', "
                    "attempt_count = 1 WHERE run_id = ?",
                    (reservation.run_id,),
                )
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.validate()
            finally:
                connection.close()

    def test_console_admission_rolls_back_when_active_runs_fill_capacity(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository, "MAX_SOURCE_RUNS", 1
        ):
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(
                root, [run_fixture("run_capacity_one", status="running")]
            )
            with self.assertRaisesRegex(
                RunRepositoryValidationError, "run.capacity_exceeded"
            ):
                save_authoritative_run_summaries(
                    root, [run_fixture("run_capacity_two", status="running")]
                )
            connection = connect(root)
            try:
                count = connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0]
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(count, 1)

    def test_validation_rejects_noncanonical_task_snapshot(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                repository.reserve_dispatch(
                    idempotency_key="snapshot-corruption-key",
                    dispatch_id="dispatch_snapshot_corrupt",
                    run_id="run_snapshot_corrupt",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=digest,
                    capabilities=("run.start",),
                )
                connection.execute(
                    "UPDATE mentat_runs SET task_snapshot_json = '[]' WHERE id = ?",
                    ("run_snapshot_corrupt",),
                )
                connection.commit()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.validate()
            finally:
                connection.close()

    def test_validation_rejects_semantically_invalid_event_with_matching_digest(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(root, [run_fixture("run_event_corrupt")])
            event = AgentEvent(
                id="event-semantic-corrupt",
                run_id="run_event_corrupt",
                sequence=1,
                type=AgentEventType.MESSAGE,
                occurred_at=timestamp(),
                summary="Valid before corruption",
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                repository.append_event(event)
                row = connection.execute(
                    "SELECT * FROM mentat_agent_events WHERE id = ?", (event.id,)
                ).fetchone()
                record = {
                    key: row[key]
                    for key in (
                        "id", "run_id", "sequence", "event_type", "source_type",
                        "source_key", "occurred_at", "summary", "content", "metrics_json",
                        "data_json",
                    )
                }
                record["metrics_json"] = "[]"
                payload_digest = hashlib.sha256(
                    run_repository._canonical_json(
                        record, maximum=32_768, code="event.invalid"
                    ).encode("ascii")
                ).hexdigest()
                connection.execute(
                    "UPDATE mentat_agent_events SET metrics_json = '[]', payload_digest = ? "
                    "WHERE id = ?",
                    (payload_digest, event.id),
                )
                connection.commit()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.validate()
            finally:
                connection.close()

    def test_validation_rejects_task_capabilities_absent_from_run_binding(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="capability-mismatch-key",
                    dispatch_id="dispatch_capability_mismatch",
                    run_id="run_capability_mismatch",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                snapshot = {
                    "id": task["id"],
                    "title": task["title"],
                    "description": task["description"],
                    "status": task["status"],
                    "assigned_agent_id": task["assigned_agent_id"],
                    "required_capabilities": ["capability.not_bound"],
                }
                snapshot_json = run_repository._canonical_json(
                    snapshot,
                    maximum=run_repository.TASK_SNAPSHOT_LIMIT,
                    code="dispatch.task_invalid",
                )
                request_digest = run_repository.dispatch_request_digest(
                    task=snapshot,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    capabilities=("run.start",),
                )
                connection.execute(
                    "UPDATE mentat_runs SET task_snapshot_json = ? WHERE id = ?",
                    (snapshot_json, reservation.run_id),
                )
                connection.execute(
                    "UPDATE mentat_dispatch_reservations SET request_digest = ? WHERE run_id = ?",
                    (request_digest, reservation.run_id),
                )
                connection.execute(
                    "UPDATE mentat_task_dispatch_heads SET request_digest = ? WHERE run_id = ?",
                    (request_digest, reservation.run_id),
                )
                connection.commit()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.validate()
            finally:
                connection.close()

    def test_validation_rejects_semantically_invalid_run_row(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="invalid-run-row-key",
                    dispatch_id="dispatch_invalid_run_row",
                    run_id="run_invalid_run_row",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                )
                connection.execute(
                    "UPDATE mentat_runs SET created_at = 'not-a-time', "
                    "updated_at = 'not-a-time', runtime_type = '../invalid', "
                    "capabilities_json = '[7]' WHERE id = ?",
                    (reservation.run_id,),
                )
                connection.commit()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.validate()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.get_run(reservation.run_id)
            finally:
                connection.close()

    def test_validation_rejects_event_source_type_mismatch_with_matching_digest(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(root, [run_fixture("run_source_mismatch")])
            event = AgentEvent(
                id="event-source-mismatch",
                run_id="run_source_mismatch",
                sequence=1,
                type=AgentEventType.MESSAGE,
                occurred_at=timestamp(),
                summary="Valid before source corruption",
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                repository.append_event(event)
                row = connection.execute(
                    "SELECT * FROM mentat_agent_events WHERE id = ?", (event.id,)
                ).fetchone()
                record = {
                    key: row[key]
                    for key in (
                        "id", "run_id", "sequence", "event_type", "source_type",
                        "source_key", "occurred_at", "summary", "content", "metrics_json",
                        "data_json",
                    )
                }
                record["source_type"] = "cost"
                payload_digest = hashlib.sha256(
                    run_repository._canonical_json(
                        record, maximum=32_768, code="event.invalid"
                    ).encode("ascii")
                ).hexdigest()
                connection.execute(
                    "UPDATE mentat_agent_events SET source_type = 'cost', payload_digest = ? "
                    "WHERE id = ?",
                    (payload_digest, event.id),
                )
                connection.commit()
                with self.assertRaisesRegex(RunRepositoryError, "run_repository.corrupt"):
                    repository.validate()
            finally:
                connection.close()

    def test_canonical_typed_events_always_remain_repository_valid(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(root, [run_fixture("run_typed_events")])
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                for sequence, event_type in enumerate(AgentEventType, start=1):
                    repository.append_event(
                        AgentEvent(
                            id=f"event-typed-{sequence}",
                            run_id="run_typed_events",
                            sequence=sequence,
                            type=event_type,
                            occurred_at=timestamp(sequence),
                            summary=f"Typed {event_type.value}",
                        )
                    )
                repository.validate()
            finally:
                connection.close()
            unit = capture_private_console_unit(root)

        self.assertEqual(unit.run_count, 1)

    def test_legacy_event_id_boundary_rolls_back_invalid_authority(self):
        for length, accepted in ((128, True), (129, False), (160, False)):
            with self.subTest(length=length), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                path = history_path(root)
                run = run_fixture(f"run_event_id_{length}")
                run["events"] = [
                    {
                        "id": "e" * length,
                        "run_id": run["id"],
                        "sequence": 1,
                        "cursor": 1,
                        "type": "complete",
                        "kind": "complete",
                        "timestamp": timestamp(1),
                        "display_text": "Complete",
                        "message": "Complete",
                        "data": {},
                    }
                ]
                save_run_summaries(path, [run])
                if accepted:
                    ensure_run_sqlite_authority(root, path)
                else:
                    with self.assertRaisesRegex(
                        RunRepositoryValidationError, "run_migration.source_invalid"
                    ):
                        ensure_run_sqlite_authority(root, path)
                connection = connect(root)
                try:
                    repository = RunRepository(connection)
                    receipt = repository.authority_receipt()
                    counts = tuple(
                        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        for table in ("mentat_runs", "mentat_agent_events")
                    )
                finally:
                    connection.close()
                if accepted:
                    self.assertIsNotNone(receipt)
                    self.assertEqual(counts, (1, 1))
                else:
                    self.assertIsNone(receipt)
                    self.assertEqual(counts, (0, 0))

    def test_validation_rejects_run_reservation_and_head_timestamp_corruption(self):
        corruptions = (
            ("mentat_runs", "created_at = '2027-01-01T00:00:00+00:00'"),
            ("mentat_dispatch_reservations", "dispatch_id = 'bad id'"),
            (
                "mentat_dispatch_reservations",
                "created_at = '2027-01-01T00:00:00+00:00', "
                "updated_at = '2026-01-01T00:00:00+00:00'",
            ),
            ("mentat_task_dispatch_heads", "updated_at = 'not-a-time'"),
        )
        for table, assignment in corruptions:
            with self.subTest(table=table, assignment=assignment), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                task, binding_digest = self.prepare_dispatch_root(root)
                connection = connect(root)
                try:
                    repository = RunRepository(connection)
                    repository.reserve_dispatch(
                        idempotency_key=f"timestamp-corruption-{table}-{len(assignment)}",
                        dispatch_id="dispatch_timestamp_corrupt",
                        run_id="run_timestamp_corrupt",
                        task=task,
                        task_revision=1,
                        agent_id="agent-main",
                        runtime_type="hermes",
                        runtime_config_id="config-main",
                        binding_digest=binding_digest,
                        capabilities=("run.start",),
                        now=timestamp(),
                    )
                    connection.execute(f"UPDATE {table} SET {assignment}")
                    connection.commit()
                    with self.assertRaisesRegex(
                        RunRepositoryError, "run_repository.corrupt"
                    ):
                        repository.validate()
                finally:
                    connection.close()

    def test_supported_mutations_roll_back_when_the_clock_moves_backward(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="clock-rollback-claim",
                    dispatch_id="dispatch_clock_rollback",
                    run_id="run_clock_rollback",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                    now=timestamp(10),
                )
                with self.assertRaisesRegex(
                    RunRepositoryValidationError, "run.timestamp_invalid"
                ):
                    repository.claim_dispatch_attempt(
                        dispatch_id=reservation.dispatch_id,
                        expected_binding_digest=binding_digest,
                        now=timestamp(5),
                    )
                stored = repository.get_run(reservation.run_id)
                state = connection.execute(
                    "SELECT state, attempt_count, updated_at "
                    "FROM mentat_dispatch_reservations WHERE dispatch_id = ?",
                    (reservation.dispatch_id,),
                ).fetchone()
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(stored.status, "reserved")
        self.assertEqual(stored.updated_at, timestamp(10))
        self.assertEqual(tuple(state), ("reserved", 0, timestamp(10)))

    def test_recovery_rolls_back_when_its_timestamp_precedes_the_reservation(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task, binding_digest = self.prepare_dispatch_root(root)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="clock-rollback-recovery",
                    dispatch_id="dispatch_clock_recovery",
                    run_id="run_clock_recovery",
                    task=task,
                    task_revision=1,
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    binding_digest=binding_digest,
                    capabilities=("run.start",),
                    now=timestamp(10),
                )
                with self.assertRaisesRegex(
                    RunRepositoryValidationError, "run.timestamp_invalid"
                ):
                    repository.recover_reserved_as_interrupted(now=timestamp(5))
                stored = repository.get_run(reservation.run_id)
                events, _reset, _cursor = repository.list_events(reservation.run_id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(stored.status, "reserved")
        self.assertEqual([event.type for event in events], [AgentEventType.DISPATCH_RESERVED])


if __name__ == "__main__":
    unittest.main()
