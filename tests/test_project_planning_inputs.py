"""Schema-39 Project input history is storage, never proposal admission."""

from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
import unittest

import mentat_db
import private_console_unit
import project_context
import project_context_access
from project_context_editor import (ProjectContextEditorError, preview_context_prune,
                                    read_context_version)
from project_leads import read_project_lead, select_project_lead
from project_planning_inputs import (ProjectPlanningInputError,
                                     validate_project_planning_input_connection)
from task_repository import _schema5_private_unit
from tests import test_task_inputs


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


class ProjectPlanningInputStorageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_task_inputs.TaskInputStorageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        before = read_project_lead(self.root, "project_mentat")
        choice = next(item for item in before["choices"] if item["id"] == "agent_research")
        self.lead = select_project_lead(
            self.root, "project_mentat", "agent_research",
            expected_project_revision=before["project_revision"],
            expected_lead_revision=before["revision"],
            selection_token=choice["selection_token"],
        )

    def insert_version(self, revision=1, *, context_id=None, attachment=True):
        identifier = f"project_input_{revision:032x}"
        with closing(mentat_db.connect(self.root)) as connection:
            role = connection.execute(
                "SELECT project_id,project_incarnation,revision,agent_id,"
                "agent_incarnation,agent_revision,binding_digest,context_id,grant_revision "
                "FROM mentat_project_lead_versions WHERE id=?", (self.lead["id"],)
            ).fetchone()
            entries = []
            selected_context = context_id or role[7]
            instructions = "Plan the garage using supplied dimensions."
            if attachment:
                item = connection.execute(
                    "SELECT a.id,a.blob_id,b.sha256,a.byte_size,a.kind,a.mime_type "
                    "FROM attachments a JOIN blobs b ON b.id=a.blob_id WHERE a.id=?",
                    (self.fixture.attachment,),
                ).fetchone()
                entries.append(list(item))
            created = time.time()
            connection.execute(
                "INSERT INTO mentat_project_planning_input_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (identifier, role[0], role[1], revision, self.lead["project_revision"],
                 self.lead["id"], role[2], role[3], role[4], role[5], role[6],
                 selected_context, role[8], instructions,
                 _digest(entries), created),
            )
            for ordinal, item in enumerate(entries):
                connection.execute(
                    "INSERT INTO mentat_project_planning_input_files VALUES(?,?,?,?,?,?,?,?)",
                    (identifier, ordinal, *item),
                )
            action_id = "project_input_action_" + f"{revision:032x}"
            scope_token, selection_token = "1" * 64, "2" * 64
            request_digest = _digest([
                action_id, role[0], self.lead["project_revision"], self.lead["id"],
                role[2], selected_context, role[8], revision - 1,
                scope_token, selection_token, instructions,
                [item[0] for item in entries],
            ])
            connection.execute(
                "INSERT INTO mentat_project_planning_input_actions VALUES(?,?,?,?,?,?,?)",
                (action_id, identifier, scope_token, selection_token,
                 request_digest, "owner", created),
            )
            connection.commit()
        return identifier

    def test_retained_project_input_validates_and_protects_context_without_run(self):
        identifier = self.insert_version()
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(len(validate_project_planning_input_connection(connection)[0]), 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0], 0)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_retained_attachments WHERE attachment_id=?",
                (self.fixture.attachment,),
            ).fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE mentat_project_planning_input_versions SET instructions='changed' WHERE id=?",
                    (identifier,),
                )
            connection.rollback()
        with self.assertRaisesRegex(ProjectContextEditorError, "project_input"):
            preview_context_prune(self.root, self.fixture.context["id"])
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)

    def test_historical_context_reports_exact_project_input_pin(self):
        self.insert_version()
        self.fixture.fixture.publish(expected=1, brief="Revised garage goals")
        project_context_access.revoke_context_grant(
            self.root, "project_mentat", self.fixture.context["id"],
            "agent_research", expected_revision=1,
        )
        self.assertEqual(read_context_version(
            self.root, self.fixture.context["id"]
        )["prune_blocked"], "project_input")

    def test_wrong_role_context_or_file_digest_fails_closed(self):
        self.insert_version()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(ProjectPlanningInputError, "invalid"):
                connection.execute("DROP TRIGGER mentat_project_planning_input_immutable")
                connection.execute(
                    "UPDATE mentat_project_planning_input_versions SET grant_revision=grant_revision+1"
                )
                validate_project_planning_input_connection(connection)
            connection.rollback()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP TRIGGER mentat_project_planning_input_immutable")
            connection.execute(
                "UPDATE mentat_project_planning_input_versions SET files_digest=?", ("0" * 64,)
            )
            with self.assertRaisesRegex(ProjectPlanningInputError, "files_invalid"):
                validate_project_planning_input_connection(connection)
            connection.rollback()

    def test_context_version_cannot_postdate_prepared_input(self):
        self.insert_version()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP TRIGGER mentat_project_context_version_immutable")
            connection.execute(
                "UPDATE mentat_project_context_versions SET created_at=? WHERE id=?",
                (time.time() + 3600, self.fixture.context["id"]),
            )
            with self.assertRaisesRegex(ProjectPlanningInputError, "invalid"):
                validate_project_planning_input_connection(connection)
            connection.rollback()

    def test_context_version_cannot_postdate_selected_lead_role(self):
        self.insert_version()
        with closing(mentat_db.connect(self.root)) as connection:
            context_created = connection.execute(
                "SELECT created_at FROM mentat_project_context_versions WHERE id=?",
                (self.fixture.context["id"],),
            ).fetchone()[0]
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP TRIGGER mentat_project_lead_immutable")
            connection.execute(
                "UPDATE mentat_project_lead_versions SET created_at=? WHERE id=?",
                (context_created - 0.001, self.lead["id"]),
            )
            with self.assertRaisesRegex(ProjectPlanningInputError, "invalid"):
                validate_project_planning_input_connection(connection)
            connection.rollback()

    def test_format4_restore_retains_history_but_revokes_grant(self):
        identifier = self.insert_version()
        unit = private_console_unit.capture_private_console_unit(self.root)
        restored = private_console_unit.sanitize_owner_auth_restore_unit(unit)
        target = self.root / "restored-project-input"
        (target / "private").mkdir(parents=True, mode=0o700)
        private_console_unit.materialize_private_console_unit(
            target, restored, target / "private" / "console",
        )
        with closing(mentat_db.connect(target)) as connection:
            self.assertEqual(connection.execute(
                "SELECT id FROM mentat_project_planning_input_versions"
            ).fetchone()[0], identifier)
            self.assertEqual(connection.execute(
                "SELECT state FROM mentat_project_context_grants WHERE agent_id='agent_research'"
            ).fetchone()[0], "revoked")
            validate_project_planning_input_connection(connection, require_available=False)

    def test_tampered_file_evidence_fails_private_backup_validation(self):
        self.insert_version()
        unit = private_console_unit.capture_private_console_unit(self.root)
        snapshot = self.root / "tampered-project-input.sqlite3"
        snapshot.write_bytes(unit.database_raw)
        with closing(sqlite3.connect(snapshot)) as connection:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='mentat_project_planning_input_file_immutable'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER mentat_project_planning_input_file_immutable")
            connection.execute(
                "UPDATE mentat_project_planning_input_files SET sha256=?", ("0" * 64,)
            )
            connection.execute(trigger)
            connection.commit()
        with self.assertRaises(private_console_unit.PrivateConsoleUnitError):
            private_console_unit.validate_private_console_unit(
                replace(unit, database_raw=snapshot.read_bytes())
            )

    def test_schema5_compatible_export_omits_new_authority(self):
        self.insert_version()
        unit = private_console_unit.capture_private_console_unit(self.root)
        compatible = _schema5_private_unit(unit)
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.deserialize(compatible.database_raw)
            self.assertEqual(connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0], 5)
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name='mentat_project_planning_input_versions'"
            ).fetchone())
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_project_planning_input_versions"
            ).fetchone()[0], 1)

    def test_per_project_incarnation_capacity_is_bounded(self):
        for revision in range(1, 33):
            self.insert_version(revision, attachment=False)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(len(validate_project_planning_input_connection(connection)[0]), 32)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO mentat_project_planning_input_versions SELECT "
                    "'project_input_ffffffffffffffffffffffffffffffff',project_id,project_incarnation,"
                    "33,project_revision,lead_role_id,lead_revision,agent_id,agent_incarnation,"
                    "agent_revision,binding_digest,context_id,grant_revision,instructions,files_digest,created_at "
                    "FROM mentat_project_planning_input_versions WHERE revision=1"
                )

    def test_populated_schema39_upgrade_backfills_explicit_legacy_receipt(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "schema39.sqlite3"
            private_console_unit._initialize_database(path, schema_version=39)
            identifier = "project_input_" + "d" * 32
            digest = _digest([])
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "INSERT INTO mentat_project_context_scopes VALUES(?,?,?,?,?)",
                    ("project_scope_" + "a" * 32, "project_garage", 1, 1.0, 5.0),
                )
                connection.execute(
                    "INSERT INTO mentat_project_context_versions VALUES(?,?,?,?,?,?)",
                    ("project_context_" + "b" * 32,
                     "project_scope_" + "a" * 32, 1, "Old garage", digest, 2.0),
                )
                connection.execute(
                    "INSERT INTO mentat_project_lead_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("lead_role_" + "c" * 32, "project_garage", "e" * 32, 1,
                     "select", "agent_research", "f" * 32, 1, "1" * 64,
                     "project_context_" + "b" * 32, 1, 3.0),
                )
                connection.execute(
                    "INSERT INTO mentat_project_planning_input_versions "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (identifier, "project_garage", "e" * 32, 1, 1,
                     "lead_role_" + "c" * 32, 1, "agent_research", "f" * 32,
                     1, "1" * 64, "project_context_" + "b" * 32, 1,
                     "Plan the old garage", digest, 4.0),
                )
                connection.commit()
                self.assertEqual(mentat_db.schema_signature_state(connection, 39), "expected")
                mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 41), "expected")
                row = connection.execute(
                    "SELECT action_id,input_id,request_digest,source_kind "
                    "FROM mentat_project_planning_input_actions"
                ).fetchone()
                self.assertEqual(row, (
                    "project_input_action_" + identifier[14:], identifier,
                    digest, "legacy",
                ))


class ProjectPlanningInputMigrationTests(unittest.TestCase):
    def test_deterministic_empty_private_unit_accepts_virtual_migration_cutoff(self):
        unit = private_console_unit.empty_private_console_unit()
        private_console_unit.validate_private_console_unit(unit)

    def test_exact_schema39_action_upgrade_and_drift_rejection(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.sqlite3"
            private_console_unit._initialize_database(path, schema_version=39)
            with closing(sqlite3.connect(path)) as connection:
                mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 41), "expected")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "drift.sqlite3"
            private_console_unit._initialize_database(path, schema_version=39)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP TRIGGER mentat_project_planning_input_immutable")
                with self.assertRaisesRegex(mentat_db.MentatDatabaseError, "schema 39"):
                    mentat_db.migrate(connection)
                self.assertEqual(connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0], 39)

    def test_exact_schema38_upgrade_and_drift_rejection(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.sqlite3"
            private_console_unit._initialize_database(path, schema_version=38)
            with closing(sqlite3.connect(path)) as connection:
                mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 41), "expected")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "drift.sqlite3"
            private_console_unit._initialize_database(path, schema_version=38)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP TRIGGER mentat_project_lead_immutable")
                with self.assertRaisesRegex(mentat_db.MentatDatabaseError, "schema 38"):
                    mentat_db.migrate(connection)
                self.assertEqual(connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0], 38)


if __name__ == "__main__":
    unittest.main()
