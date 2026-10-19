"""Owner Project-input publication retains evidence without Agent work."""

from contextlib import closing
from dataclasses import replace
import sqlite3
from threading import Barrier, Thread
import unittest

import mentat_db
import private_console_unit
import project_context_access
from planning_deletion import PlanningDeletionService
from project_leads import read_project_lead, select_project_lead
from project_repository import mutate_authoritative_projects
from project_planning_inputs import (ProjectPlanningInputError,
    normalize_project_input_request, publish_project_input,
    read_project_input_editor, reconcile_project_input_action)
from tests import test_task_inputs
from tests.test_project_repository import project


class ProjectPlanningInputEditorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_task_inputs.TaskInputStorageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        before = read_project_lead(self.root, "project_mentat")
        choice = next(item for item in before["choices"] if item["id"] == "agent_research")
        select_project_lead(self.root, "project_mentat", "agent_research",
                            expected_project_revision=before["project_revision"],
                            expected_lead_revision=before["revision"],
                            selection_token=choice["selection_token"])

    def payload(self, *, action="a" * 32, files=True):
        editor = read_project_input_editor(self.root, "project_mentat")
        return {"project_id": "project_mentat",
                "expected_project_revision": editor["project"]["revision"],
                "lead_role_id": editor["lead"]["id"],
                "expected_lead_revision": editor["lead"]["revision"],
                "context_id": editor["context"]["id"],
                "expected_grant_revision": editor["grant_revision"],
                "expected_input_revision": editor["input_revision"],
                "scope_token": editor["scope_token"],
                "selection_token": editor["selection_token"],
                "action_id": "project_input_action_" + action,
                "instructions": "Use the measured garage dimensions.",
                "attachment_ids": [self.fixture.attachment] if files else []}

    def test_exact_save_and_replay_do_not_dispatch_or_duplicate(self):
        before = read_project_input_editor(self.root, "project_mentat")
        self.assertTrue(before["save_available"])
        request = self.payload()
        first = publish_project_input(self.root, request)
        self.assertEqual((first["revision"], first["status"]), (1, "saved"))
        replay = publish_project_input(self.root, request)
        self.assertEqual(replay, {"input_id": first["input_id"], "revision": 1,
                                  "status": "committed_needs_review"})
        with self.assertRaisesRegex(ProjectPlanningInputError, "action_conflict"):
            publish_project_input(self.root, {**request, "instructions": "Different"})
        after = read_project_input_editor(self.root, "project_mentat")
        self.assertEqual(after["version"]["id"], first["input_id"])
        self.assertEqual(after["version"]["files"][0]["id"], self.fixture.attachment)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_project_planning_input_actions"
            ).fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0], 0)
        private_console_unit.validate_private_console_unit(
            private_console_unit.capture_private_console_unit(self.root)
        )

    def test_lost_response_reconciles_exact_action_without_write(self):
        request = self.payload()
        saved = publish_project_input(self.root, request)
        result = reconcile_project_input_action(
            self.root, "project_mentat", request["action_id"], request["scope_token"]
        )
        self.assertEqual(result, {"status": "committed_needs_review",
                                  "input_id": saved["input_id"], "revision": 1})
        self.assertEqual(reconcile_project_input_action(
            self.root, "project_mentat", "project_input_action_" + "b" * 32,
            request["scope_token"],
        )["status"], "not_found")
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_project_planning_input_versions"
            ).fetchone()[0], 1)

    def test_changed_context_grant_or_head_blocks_new_action_but_replay_survives(self):
        original = self.payload()
        saved = publish_project_input(self.root, original)
        with self.assertRaisesRegex(ProjectPlanningInputError, "revision_conflict"):
            publish_project_input(self.root, {**original,
                "action_id": "project_input_action_" + "b" * 32})
        project_context_access.revoke_context_grant(
            self.root, "project_mentat", self.fixture.context["id"],
            "agent_research", expected_revision=1,
        )
        self.assertFalse(read_project_input_editor(self.root, "project_mentat")["save_available"])
        self.assertEqual(publish_project_input(self.root, original)["input_id"], saved["input_id"])
        with self.assertRaisesRegex(ProjectPlanningInputError, "lead_changed"):
            publish_project_input(self.root, {**original,
                "action_id": "project_input_action_" + "c" * 32})

    def test_widened_and_overlimit_requests_fail_before_write(self):
        baseline = self.payload()
        for candidate in ({**baseline, "runtime_ref": "private"},
                          {**baseline, "expected_input_revision": True},
                          {**baseline, "attachment_ids": [self.fixture.attachment] * 2},
                          {**baseline, "attachment_ids": [f"attachment_{index:032x}" for index in range(9)]},
                          {**baseline, "instructions": "🚲" * 4097}):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ProjectPlanningInputError):
                    normalize_project_input_request(candidate)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_project_planning_input_versions"
            ).fetchone()[0], 0)

    def test_two_devices_cannot_publish_same_revision(self):
        first = self.payload(action="a" * 32)
        second = {**first, "action_id": "project_input_action_" + "b" * 32}
        barrier = Barrier(2)
        results = []
        def attempt(request):
            barrier.wait()
            try:
                results.append(publish_project_input(self.root, request)["status"])
            except ProjectPlanningInputError as exc:
                results.append(str(exc))
        threads = [Thread(target=attempt, args=(item,)) for item in (first, second)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertEqual(sorted(results), sorted(["saved", "project_input.revision_conflict"]))

    def test_project_revision_change_requires_new_input_but_keeps_lead(self):
        request = self.payload()
        saved = publish_project_input(self.root, request)
        mutate_authoritative_projects(self.root, lambda rows: ([
            {**item, "name": "Renamed garage"} if item["id"] == "project_mentat" else item
            for item in rows], None))
        latest = read_project_input_editor(self.root, "project_mentat")
        self.assertEqual(latest["lead"]["status"], "context_bound")
        self.assertNotEqual(latest["project"]["revision"], request["expected_project_revision"])
        with self.assertRaisesRegex(ProjectPlanningInputError, "project_changed"):
            publish_project_input(self.root, {**request,
                "action_id": "project_input_action_" + "b" * 32})
        self.assertEqual(publish_project_input(self.root, request)["input_id"], saved["input_id"])

    def test_project_id_reuse_changes_opaque_scope_and_cannot_inherit_save(self):
        old = self.payload()
        deletion = PlanningDeletionService(self.root)
        deletion.finalize(deletion.preview("project", "project_mentat"))
        mutate_authoritative_projects(self.root, lambda rows: ([
            *rows, project("Replacement garage", "project_mentat")], None))
        current = read_project_input_editor(self.root, "project_mentat")
        self.assertNotEqual(current["scope_token"], old["scope_token"])
        self.assertEqual(current["lead"]["status"], "unassigned")
        with self.assertRaises(ProjectPlanningInputError):
            publish_project_input(self.root, {**old,
                "action_id": "project_input_action_" + "b" * 32})

    def test_restore_retains_action_but_rotates_scope_and_revokes_grant(self):
        request = self.payload()
        saved = publish_project_input(self.root, request)
        unit = private_console_unit.capture_private_console_unit(self.root)
        target = self.root / "restored-project-input-editor"
        (target / "private").mkdir(parents=True, mode=0o700)
        private_console_unit.materialize_private_console_unit(
            target, private_console_unit.sanitize_owner_auth_restore_unit(unit),
            target / "private" / "console",
        )
        restored = read_project_input_editor(target, "project_mentat")
        self.assertFalse(restored["save_available"])
        self.assertNotEqual(restored["scope_token"], request["scope_token"])
        with closing(mentat_db.connect(target)) as connection:
            self.assertEqual(connection.execute(
                "SELECT input_id FROM mentat_project_planning_input_actions"
            ).fetchone()[0], saved["input_id"])
        with self.assertRaisesRegex(ProjectPlanningInputError, "scope_changed"):
            reconcile_project_input_action(target, "project_mentat",
                request["action_id"], request["scope_token"])

    def test_tampered_action_receipt_fails_private_backup_validation(self):
        publish_project_input(self.root, self.payload())
        unit = private_console_unit.capture_private_console_unit(self.root)
        snapshot = self.root / "tampered-project-action.sqlite3"
        snapshot.write_bytes(unit.database_raw)
        with closing(sqlite3.connect(snapshot)) as connection:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='mentat_project_planning_input_action_immutable'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER mentat_project_planning_input_action_immutable")
            connection.execute(
                "UPDATE mentat_project_planning_input_actions SET request_digest=?",
                ("f" * 64,),
            )
            connection.execute(trigger)
            connection.commit()
        with self.assertRaises(private_console_unit.PrivateConsoleUnitError):
            private_console_unit.validate_private_console_unit(
                replace(unit, database_raw=snapshot.read_bytes())
            )

    def test_missing_action_receipt_fails_private_backup_validation(self):
        publish_project_input(self.root, self.payload())
        unit = private_console_unit.capture_private_console_unit(self.root)
        snapshot = self.root / "missing-project-action.sqlite3"
        snapshot.write_bytes(unit.database_raw)
        with closing(sqlite3.connect(snapshot)) as connection:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='mentat_project_planning_input_action_retained'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER mentat_project_planning_input_action_retained")
            connection.execute("DELETE FROM mentat_project_planning_input_actions")
            connection.execute(trigger)
            connection.commit()
        with self.assertRaises(private_console_unit.PrivateConsoleUnitError):
            private_console_unit.validate_private_console_unit(
                replace(unit, database_raw=snapshot.read_bytes())
            )

    def test_changed_action_id_fails_private_backup_validation(self):
        publish_project_input(self.root, self.payload())
        unit = private_console_unit.capture_private_console_unit(self.root)
        snapshot = self.root / "changed-project-action-id.sqlite3"
        snapshot.write_bytes(unit.database_raw)
        with closing(sqlite3.connect(snapshot)) as connection:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='mentat_project_planning_input_action_immutable'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER mentat_project_planning_input_action_immutable")
            connection.execute(
                "UPDATE mentat_project_planning_input_actions SET action_id=?",
                ("project_input_action_" + "f" * 32,),
            )
            connection.execute(trigger)
            connection.commit()
        with self.assertRaises(private_console_unit.PrivateConsoleUnitError):
            private_console_unit.validate_private_console_unit(
                replace(unit, database_raw=snapshot.read_bytes())
            )

    def test_owner_receipt_cannot_be_reclassified_as_legacy(self):
        publish_project_input(self.root, self.payload())
        unit = private_console_unit.capture_private_console_unit(self.root)
        snapshot = self.root / "reclassified-project-action.sqlite3"
        snapshot.write_bytes(unit.database_raw)
        with closing(sqlite3.connect(snapshot)) as connection:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='mentat_project_planning_input_action_immutable'"
            ).fetchone()[0]
            row = connection.execute(
                "SELECT id,files_digest,created_at FROM mentat_project_planning_input_versions"
            ).fetchone()
            connection.execute("DROP TRIGGER mentat_project_planning_input_action_immutable")
            connection.execute(
                "UPDATE mentat_project_planning_input_actions SET action_id=?,"
                "scope_token=?,selection_token=?,request_digest=?,source_kind='legacy',created_at=?",
                ("project_input_action_" + row[0][14:], "0" * 64, "0" * 64,
                 row[1], row[2]),
            )
            connection.execute(trigger)
            connection.commit()
        with self.assertRaises(private_console_unit.PrivateConsoleUnitError):
            private_console_unit.validate_private_console_unit(
                replace(unit, database_raw=snapshot.read_bytes())
            )

    def test_first_save_activates_materialized_virtual_schema_cutoff(self):
        request = self.payload()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute(
                "UPDATE schema_migrations SET applied_at=0 WHERE version=40"
            )
            connection.commit()
        saved = publish_project_input(self.root, request)
        self.assertEqual(saved["status"], "saved")
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertGreater(connection.execute(
                "SELECT applied_at FROM schema_migrations WHERE version=40"
            ).fetchone()[0], 0)
        private_console_unit.validate_private_console_unit(
            private_console_unit.capture_private_console_unit(self.root)
        )


if __name__ == "__main__":
    unittest.main()
