"""Schema-30 retained Run-input evidence without Project execution authority."""

from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from agent_registry import AgentRegistry
import agent_console_attachments as attachment_store
import mentat_db
import private_console_unit
import project_context
import project_context_access
from run_input_receipts import _digest, validate_run_input_connection, RunInputReceiptError
from run_repository import RunRepository
from task_inputs import publish_task_inputs, read_task_input_editor, preview_task_input_prune, TaskInputError
from task_repository import mutate_authoritative_tasks, TaskRepository
from task_repository import _schema5_private_unit
from tests import test_project_context as context_tests
from tests.test_task_repository import task
from tests.sqlite_authority_support import ensure_run_sqlite_authority
from private_state import history_path


class RunInputReceiptStorageTests(unittest.TestCase):
    def test_schema_29_upgrade_is_exact_and_creates_no_approval(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "schema29.sqlite3"
            private_console_unit._initialize_database(path, schema_version=29)
            with closing(sqlite3.connect(path)) as connection:
                mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 36)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_run_input_receipts").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_run_input_files").fetchone()[0], 0)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "drifted-schema29.sqlite3"
            private_console_unit._initialize_database(path, schema_version=29)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP VIEW mentat_retained_attachments")
                connection.execute("CREATE VIEW mentat_retained_attachments AS SELECT attachment_id FROM run_attachments")
                with self.assertRaises(mentat_db.MentatDatabaseError):
                    mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 29)

    def setUp(self):
        self.fixture = context_tests.ProjectContextTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        ensure_run_sqlite_authority(self.root, history_path(self.root))
        AgentRegistry(self.root, supported_runtime_types=("codex",)).create_agent(
            agent_id="agent_research", name="Research", runtime_config_id="config_research",
            runtime_type="codex", runtime_agent_ref="default", capabilities=("run.start",),
        )
        mutate_authoritative_tasks(self.root, lambda rows: (
            [*rows, {**task("task_research"), "project_id": "project_mentat", "assigned_agent_id": "agent_research"}], None,
        ))
        self.file_id = self.fixture.upload()
        self.context = self.fixture.publish(self.file_id)
        preview = project_context_access.preview_context_grant(
            self.root, "project_mentat", self.context["id"], "agent_research",
        )
        project_context_access.confirm_context_grant(
            self.root, "project_mentat", self.context["id"], "agent_research",
            confirmation_id=preview["confirmation_id"],
        )
        editor = read_task_input_editor(self.root, "task_research")
        self.input = publish_task_inputs(self.root, {
            "project_id": "project_mentat", "task_id": "task_research", "agent_id": "agent_research",
            "expected_task_revision": editor["task"]["revision"], "expected_input_revision": 0,
            "expected_task_token": editor["expected_task_token"], "context_id": self.context["id"],
            "expected_grant_revision": 1, "instructions": "Research safe garage organization options",
            "attachment_ids": [self.file_id],
        })

    def _reserve_and_record(self):
        with closing(mentat_db.connect(self.root)) as connection:
            task_snapshot = TaskRepository(connection).get("task_research")
            run_id = "run_receipt_test"
            binding = "a" * 64
            RunRepository(connection).reserve_dispatch(
                idempotency_key="exact-receipt-test-key-00001", dispatch_id="dispatch_receipt_test",
                run_id=run_id, task=task_snapshot.document, task_revision=task_snapshot.revision,
                agent_id="agent_research", runtime_type="codex", runtime_config_id="config_research",
                binding_digest=binding, capabilities=("run.start",), planning_execution=True,
            )
            source = connection.execute(
                "SELECT v.scope_id,v.task_revision,v.agent_id,v.agent_incarnation,v.context_id,"
                "v.grant_revision,v.binding_digest,v.instructions,s.task_id,s.task_incarnation,"
                "s.project_scope_id,ps.project_id,c.revision,c.brief "
                "FROM mentat_task_input_versions v JOIN mentat_task_input_scopes s ON s.id=v.scope_id "
                "JOIN mentat_project_context_scopes ps ON ps.id=s.project_scope_id "
                "JOIN mentat_project_context_versions c ON c.id=v.context_id WHERE v.id=?",
                (self.input["input_id"],),
            ).fetchone()
            file = connection.execute(
                "SELECT a.id,a.blob_id,b.sha256,a.byte_size,a.kind,a.mime_type "
                "FROM attachments a JOIN blobs b ON b.id=a.blob_id WHERE a.id=?", (self.file_id,),
            ).fetchone()
            manifest = _digest([self.input["input_id"], source[4], source[12], source[13], source[7], [list(file)]])
            connection.execute(
                "INSERT INTO mentat_run_input_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, self.input["input_id"], source[0], source[8], source[9], source[1],
                 source[10], source[11], source[2], source[3], "codex", "config_research",
                 source[4], source[12], source[5],
                 binding, source[6], _digest(["run.start"]), _digest(["qualified-fixture"]), _digest(["approval-fixture"]),
                 _digest(["objective-fixture"]), _digest(["tools-fixture"]), _digest(["limits-fixture"]),
                 manifest, time.time()),
            )
            connection.execute(
                "INSERT INTO mentat_run_input_files VALUES(?,?,?,?,?,?,?,?)",
                (run_id, 0, *file),
            )
            connection.commit()
            validate_run_input_connection(connection)
            project_context.validate_project_context_connection(connection)
            return run_id

    def test_receipt_pins_run_input_and_file_through_backup(self):
        run_id = self._reserve_and_record()
        with closing(mentat_db.connect(self.root)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE mentat_run_input_receipts SET approval_digest=? WHERE run_id=?", ("b" * 64, run_id))
            connection.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM mentat_run_input_files WHERE run_id=?", (run_id,))
            connection.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM mentat_run_input_receipts WHERE run_id=?", (run_id,))
            connection.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM mentat_runs WHERE id=?", (run_id,))
            connection.rollback()
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)
        compatible = _schema5_private_unit(unit)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "compatible.sqlite3"
            path.write_bytes(compatible.database_raw)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 5)
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='mentat_run_input_receipts'",
                ).fetchone())
        restored = private_console_unit.sanitize_owner_auth_restore_unit(unit)
        private_console_unit.validate_private_console_unit(restored)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "restored.sqlite3"
            path.write_bytes(restored.database_raw)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute(
                    "SELECT input_id FROM mentat_run_input_receipts WHERE run_id=?", (run_id,),
                ).fetchone()[0], self.input["input_id"])
                self.assertEqual(connection.execute(
                    "SELECT state FROM mentat_project_context_grants",
                ).fetchone()[0], "revoked")

    def test_tampered_manifest_is_rejected_and_terminal_retention_preserves_receipt(self):
        run_id = self._reserve_and_record()
        with closing(mentat_db.connect(self.root)) as connection:
            repository = RunRepository(connection)
            repository.reject_reserved_dispatch(dispatch_id="dispatch_receipt_test", failure_code="test_fixture")
            with patch("run_repository.TERMINAL_RUN_RETENTION", 0):
                repository._apply_retention()
                self.assertIsNotNone(connection.execute(
                    "SELECT id FROM mentat_runs WHERE id=?", (run_id,),
                ).fetchone())
            repository.validate()
            connection.execute("DROP TRIGGER mentat_run_input_receipt_immutable")
            connection.execute("UPDATE mentat_run_input_receipts SET manifest_digest=? WHERE run_id=?", ("0" * 64, run_id))
            with self.assertRaises(RunInputReceiptError):
                validate_run_input_connection(connection)
            connection.rollback()

    def test_missing_blob_identity_and_capacity_fail_closed(self):
        self._reserve_and_record()
        with closing(mentat_db.connect(self.root)) as connection:
            with patch("run_input_receipts.MAX_RUN_INPUT_RECEIPTS", 0), self.assertRaisesRegex(
                project_context.ProjectContextError, "capacity",
            ):
                project_context.validate_project_context_connection(connection)
            connection.execute("UPDATE blobs SET sha256=? WHERE id=(SELECT blob_id FROM attachments WHERE id=?)",
                               ("0" * 64, self.file_id))
            with self.assertRaises(RunInputReceiptError):
                validate_run_input_connection(connection)
            connection.rollback()
        attachment_store.resolve_blob_path(self.root, self.file_id).write_bytes(b"changed after receipt")
        with self.assertRaises(private_console_unit.PrivateConsoleUnitError):
            private_console_unit.capture_private_console_unit(self.root)

    def test_retired_input_remains_unprunable_while_receipt_exists(self):
        self._reserve_and_record()
        with closing(mentat_db.connect(self.root)) as connection:
            RunRepository(connection).reject_reserved_dispatch(
                dispatch_id="dispatch_receipt_test", failure_code="test_fixture",
            )
        mutate_authoritative_tasks(self.root, lambda _rows: ([], None))
        with self.assertRaisesRegex(TaskInputError, "retained_run"):
            preview_task_input_prune(self.root, self.input["input_id"])
