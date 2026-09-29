"""A selected lead remains owner intent, not a Project permission or Run."""

from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
import unittest
import uuid

import mentat_db
import private_console_unit
import project_context
import project_context_access
from planning_deletion import PlanningDeletionService
from project_leads import ProjectLeadError, read_project_lead, select_project_lead, validate_lead_connection
from project_repository import mutate_authoritative_projects
from tests import test_task_inputs
from tests.test_project_repository import project


class ProjectLeadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_task_inputs.TaskInputStorageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def choice(self, view, agent_id="agent_research"):
        return next(item for item in view["choices"] if item["id"] == agent_id)

    def select(self, view, project_id="project_mentat", agent_id="agent_research"):
        return select_project_lead(
            self.root, project_id, agent_id, expected_project_revision=view["project_revision"],
            expected_lead_revision=view["revision"],
            selection_token=self.choice(view, agent_id)["selection_token"],
        )

    def test_exact_selection_is_context_bound_without_run_task_or_grant_mutation(self):
        before = read_project_lead(self.root, "project_mentat")
        self.assertEqual((before["revision"], before["status"]), (0, "unassigned"))
        self.assertEqual(len(before["choices"]), 1)
        selected = self.select(before)
        self.assertEqual((selected["revision"], selected["status"], selected["reasons"]),
                         (1, "context_bound", []))
        self.assertFalse(selected["proposal_available"])
        self.assertNotIn("binding_digest", json.dumps(selected))
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_tasks").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_project_context_grants").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_project_lead_versions").fetchone()[0], 1)
            validate_lead_connection(connection)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE mentat_project_lead_versions SET action='clear'")
            connection.rollback()
        private_console_unit.validate_private_console_unit(
            private_console_unit.capture_private_console_unit(self.root)
        )

    def test_contextless_project_can_select_unready_then_requires_explicit_reselection(self):
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, project("Garage", "project_garage")], None))
        before = read_project_lead(self.root, "project_garage")
        self.assertFalse(self.choice(before)["context_bound"])
        unready = self.select(before, project_id="project_garage")
        self.assertEqual((unready["status"], unready["reasons"]),
                         ("unready", ["context_grant_needed"]))
        self.assertFalse(unready["proposal_available"])
        old_identity = None
        with closing(mentat_db.connect(self.root)) as connection:
            old_identity = connection.execute(
                "SELECT deliverable_incarnation FROM mentat_projects WHERE id='project_garage'"
            ).fetchone()[0]
        deletion = PlanningDeletionService(self.root)
        deletion.finalize(deletion.preview("project", "project_garage"))
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, project("New Garage", "project_garage")], None))
        recreated = read_project_lead(self.root, "project_garage")
        self.assertEqual((recreated["revision"], recreated["status"]), (0, "unassigned"))
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertNotEqual(connection.execute(
                "SELECT deliverable_incarnation FROM mentat_projects WHERE id='project_garage'"
            ).fetchone()[0], old_identity)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_project_lead_versions WHERE project_incarnation=?",
                (old_identity,),
            ).fetchone()[0], 1)

    def test_grant_change_stales_selection_and_old_token_cannot_bind_new_grant(self):
        before = read_project_lead(self.root, "project_mentat")
        selected = self.select(before)
        context_id = self.fixture.context["id"]
        project_context_access.revoke_context_grant(
            self.root, "project_mentat", context_id, "agent_research", expected_revision=1,
        )
        self.assertIn("grant_changed", read_project_lead(self.root, "project_mentat")["reasons"])
        with self.assertRaisesRegex(ProjectLeadError, "selection_changed"):
            select_project_lead(self.root, "project_mentat", "agent_research",
                                expected_project_revision=selected["project_revision"],
                                expected_lead_revision=selected["revision"],
                                selection_token=self.choice(selected)["selection_token"])
        preview = project_context_access.preview_context_grant(
            self.root, "project_mentat", context_id, "agent_research",
        )
        project_context_access.confirm_context_grant(
            self.root, "project_mentat", context_id, "agent_research",
            confirmation_id=preview["confirmation_id"],
        )
        still_stale = read_project_lead(self.root, "project_mentat")
        self.assertIn("grant_changed", still_stale["reasons"])
        refreshed = self.select(still_stale)
        self.assertEqual((refreshed["revision"], refreshed["status"]), (2, "context_bound"))

    def test_competing_exact_selections_have_one_winner(self):
        before = read_project_lead(self.root, "project_mentat")
        barrier = Barrier(2)
        results = []
        def attempt():
            barrier.wait()
            try:
                results.append(self.select(before)["revision"])
            except ProjectLeadError as exc:
                results.append(str(exc))
        threads = [Thread(target=attempt) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertEqual(sorted(results, key=str), sorted([1, "project_lead.revision_conflict"], key=str))
        self.assertEqual(read_project_lead(self.root, "project_mentat")["revision"], 1)

    def test_new_context_requires_explicit_current_grant_and_reselection(self):
        selected = self.select(read_project_lead(self.root, "project_mentat"))
        newer = project_context.publish_project_context(
            self.root, "project_mentat", expected_project_revision=1,
            expected_revision=1, brief="New garage constraints", attachment_ids=[self.fixture.attachment],
        )
        stale = read_project_lead(self.root, "project_mentat")
        self.assertEqual((stale["status"], stale["reasons"]), ("stale", ["context_changed"]))
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute(
                "SELECT state FROM mentat_project_context_grants WHERE agent_id='agent_research'"
            ).fetchone()[0], "active")
        with self.assertRaisesRegex(ProjectLeadError, "selection_changed"):
            select_project_lead(self.root, "project_mentat", "agent_research",
                                expected_project_revision=1, expected_lead_revision=selected["revision"],
                                selection_token=self.choice(selected)["selection_token"])
        unready = self.select(stale)
        self.assertEqual((unready["status"], unready["reasons"]), ("unready", ["context_grant_needed"]))
        preview = project_context_access.preview_context_grant(
            self.root, "project_mentat", newer["id"], "agent_research",
        )
        project_context_access.confirm_context_grant(
            self.root, "project_mentat", newer["id"], "agent_research",
            confirmation_id=preview["confirmation_id"],
        )
        self.assertEqual(read_project_lead(self.root, "project_mentat")["status"], "unready")
        self.assertEqual(self.select(read_project_lead(self.root, "project_mentat"))["status"], "context_bound")

    def test_agent_binding_change_stales_role(self):
        self.select(read_project_lead(self.root, "project_mentat"))
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("UPDATE agent_runtime_configs SET updated_at=updated_at+1 WHERE id='config_research'")
        self.assertIn("agent_changed", read_project_lead(self.root, "project_mentat")["reasons"])

    def test_selected_role_survives_backup_but_restore_requires_new_grant(self):
        selected = self.select(read_project_lead(self.root, "project_mentat"))
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)
        restored = private_console_unit.sanitize_owner_auth_restore_unit(unit)
        target = self.root / "restored-role"
        (target / "private").mkdir(parents=True, mode=0o700)
        private_console_unit.materialize_private_console_unit(target, restored, target / "private" / "console")
        view = read_project_lead(target, "project_mentat")
        self.assertEqual((view["id"], view["revision"]), (selected["id"], 1))
        self.assertIn("grant_changed", view["reasons"])
        self.assertFalse(view["proposal_available"])

    def test_tampered_selected_role_fails_private_backup_validation(self):
        self.select(read_project_lead(self.root, "project_mentat"))
        unit = private_console_unit.capture_private_console_unit(self.root)
        snapshot = self.root / "tampered-role.sqlite3"
        snapshot.write_bytes(unit.database_raw)
        with closing(sqlite3.connect(snapshot)) as connection:
            trigger = connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_project_lead_immutable'").fetchone()[0]
            connection.execute("DROP TRIGGER mentat_project_lead_immutable")
            connection.execute("UPDATE mentat_project_lead_versions SET binding_digest=?", ("z" * 64,))
            connection.execute(trigger)
            connection.commit()
        tampered = replace(unit, database_raw=snapshot.read_bytes())
        with self.assertRaises(private_console_unit.PrivateConsoleUnitError):
            private_console_unit.validate_private_console_unit(tampered)

    def test_project_incarnation_capacity_rejects_next_selection(self):
        first = self.select(read_project_lead(self.root, "project_mentat"))
        with closing(mentat_db.connect(self.root)) as connection:
            incarnation = connection.execute(
                "SELECT project_incarnation FROM mentat_project_lead_versions WHERE id=?", (first["id"],)
            ).fetchone()[0]
            for revision in range(2, 33):
                connection.execute(
                    "INSERT INTO mentat_project_lead_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"lead_role_{uuid.uuid4().hex}", "project_mentat", incarnation,
                     revision, "clear", None, None, None, None, None, None, 1.0),
                )
            connection.commit()
        at_limit = read_project_lead(self.root, "project_mentat")
        self.assertEqual((at_limit["revision"], at_limit["status"]), (32, "unassigned"))
        with self.assertRaisesRegex(ProjectLeadError, "capacity"):
            select_project_lead(self.root, "project_mentat", None,
                                expected_project_revision=at_limit["project_revision"],
                                expected_lead_revision=at_limit["revision"],
                                selection_token=at_limit["clear_token"])


class ProjectLeadMigrationTests(unittest.TestCase):
    def test_exact_schema37_upgrade_and_drift_gate(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "prior.sqlite3"
            private_console_unit._initialize_database(path, schema_version=37)
            with closing(sqlite3.connect(path)) as connection:
                mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 41), "expected")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "drift.sqlite3"
            private_console_unit._initialize_database(path, schema_version=37)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP TRIGGER mentat_plan_version_immutable")
                with self.assertRaisesRegex(mentat_db.MentatDatabaseError, "schema 37"):
                    mentat_db.migrate(connection)
                self.assertEqual(connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0], 37)


if __name__ == "__main__":
    unittest.main()
