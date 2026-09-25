from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
import unittest

import mentat_db
import private_console_unit
import project_context
import project_context_access
from planning_deletion import PlanningDeletionError, PlanningDeletionService
from project_repository import mutate_authoritative_projects
from project_plans import ProjectPlanError, normalize_owner_plan, publish_owner_plan, read_project_plan, validate_plan_connection
from task_inputs import TaskInputError, preview_task_input_prune, publish_task_inputs, read_task_input_editor
from task_inputs_http import dispatch_task_inputs
from task_repository import mutate_authoritative_tasks
from tests.test_task_inputs import TaskInputStorageTests
from tests.test_task_repository import task
from tests.test_project_repository import project


class ProjectPlanTests(unittest.TestCase):
    def setUp(self):
        self.fixture = TaskInputStorageTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.first = publish_task_inputs(self.root, self.fixture.payload)

    def node(self, **changes):
        return {"task_id": "task_research", "expected_task_revision": 1,
                "agent_id": "agent_research", "input_version_id": self.first["input_id"],
                "after": [], "segment": 0, "max_attempts": 1,
                "max_wall_seconds": 900, "max_work_units": 100, **changes}

    def publish(self, **changes):
        return publish_owner_plan(self.root, "project_mentat", "Garage organization",
                                  [self.node(**changes)], expected_project_revision=1,
                                  expected_plan_revision=0)

    def add_layout_task(self, *, dependencies=None):
        mutate_authoritative_tasks(self.root, lambda rows: ([*rows, {
            **task("task_layout", dependencies=dependencies), "project_id": "project_mentat",
            "assigned_agent_id": "agent_research"}], None))
        payload = {**self.fixture.payload, "task_id": "task_layout", "attachment_ids": [],
                   "expected_task_token": read_task_input_editor(self.root, "task_layout")["expected_task_token"]}
        return publish_task_inputs(self.root, payload)

    def test_schema32_exact_upgrade_and_drift_gate(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "prior.sqlite3"
            private_console_unit._initialize_database(path, schema_version=32)
            with closing(sqlite3.connect(path)) as connection:
                prior = private_console_unit.PrivateConsoleUnit(
                    history_raw=private_console_unit._empty_history(), database_raw=path.read_bytes(),
                    registry_database_raw=None, blobs=(),
                )
                private_console_unit.validate_private_console_unit(prior)
                restored = private_console_unit.sanitize_owner_auth_restore_unit(
                    prior, epoch_seed=b"p" * 32,
                )
                target = Path(temporary) / "restored"
                (target / "private").mkdir(parents=True)
                private_console_unit.materialize_private_console_unit(
                    target, restored, target / "private" / "console",
                )
                with closing(mentat_db.connect(target)) as upgraded:
                    self.assertEqual(upgraded.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], mentat_db.SCHEMA_VERSION)
                    validate_plan_connection(upgraded)
                mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], mentat_db.SCHEMA_VERSION)
                validate_plan_connection(connection)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "drift.sqlite3"
            private_console_unit._initialize_database(path, schema_version=32)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP VIEW mentat_retained_attachments")
                connection.execute("CREATE VIEW mentat_retained_attachments AS SELECT attachment_id FROM run_attachments")
                with self.assertRaises(mentat_db.MentatDatabaseError):
                    mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 32)

    def test_owner_plan_is_immutable_unapproved_and_backup_capable(self):
        result = self.publish()
        self.assertEqual((result["revision"], result["status"]), (1, "unapproved"))
        view = read_project_plan(self.root, "project_mentat")
        self.assertEqual(view["current"]["title"], "Garage organization")
        self.assertEqual(view["current"]["nodes"][0]["task_id"], "task_research")
        self.assertFalse(view["execution_available"])
        self.assertEqual(view["stale_reasons"], [])
        self.assertNotIn("incarnation", repr(view))
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_plan_input_refs").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM mentat_task_input_versions WHERE id=?", (self.first["input_id"],))
            connection.rollback()
            validate_plan_connection(connection)
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)
        self.assertEqual(private_console_unit.validate_private_console_unit(private_console_unit.sanitize_owner_auth_restore_unit(unit)).database_raw[:16], b"SQLite format 3\x00")

    def test_wrong_agent_stale_task_and_invalid_dependency_fail_before_write(self):
        for node in (
            self.node(agent_id="agent_other"),
            self.node(after=["task_missing"]),
            self.node(segment=1),
            self.node(max_wall_seconds=0),
            self.node(max_work_units=True),
        ):
            with self.subTest(node=node), self.assertRaises(ProjectPlanError):
                publish_owner_plan(self.root, "project_mentat", "Garage", [node],
                                   expected_project_revision=1, expected_plan_revision=0)
        mutate_authoritative_tasks(self.root, lambda rows: ([{**rows[0], "title": "New research goal"}], None))
        with self.assertRaisesRegex(ProjectPlanError, "task_changed"):
            self.publish()
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_plan_versions").fetchone()[0], 0)

    def test_task_edit_makes_saved_plan_advisory_stale_without_erasing_history(self):
        self.publish()
        mutate_authoritative_tasks(self.root, lambda rows: ([{**rows[0], "title": "New research goal"}], None))
        view = read_project_plan(self.root, "project_mentat")
        self.assertIn("task_changed", view["stale_reasons"])
        self.assertEqual(view["plan_revision"], 1)
        self.assertFalse(view["execution_available"])

    def test_project_edit_stales_its_exact_saved_revision(self):
        self.publish()
        mutate_authoritative_projects(self.root, lambda rows: ([{**rows[0], "name": "Garage Replanned"}], None))
        self.assertIn("project_changed", read_project_plan(self.root, "project_mentat")["stale_reasons"])

    def test_two_node_checkpoint_plan_matches_canonical_dependencies(self):
        layout = self.add_layout_task(dependencies=["task_research"])
        second = self.node(task_id="task_layout", input_version_id=layout["input_id"],
                           after=["task_research"], segment=1)
        result = publish_owner_plan(self.root, "project_mentat", "Research then layout",
                                    [self.node(), second], expected_project_revision=1,
                                    expected_plan_revision=0)
        self.assertEqual(result["status"], "unapproved")
        view = read_project_plan(self.root, "project_mentat")
        self.assertEqual([node["segment"] for node in view["current"]["nodes"]], [0, 1])
        self.assertEqual(view["stale_reasons"], [])
        self.assertEqual(view["dependency_comparison"]["missing_count"], 0)
        self.assertEqual(view["dependency_comparison"]["additional_count"], 0)

    def test_dependency_comparison_discloses_both_plan_and_task_graphs(self):
        layout = self.add_layout_task(dependencies=["task_research"])
        second = self.node(task_id="task_layout", input_version_id=layout["input_id"],
                           after=[], segment=1)
        publish_owner_plan(self.root, "project_mentat", "Missing prerequisite",
                           [self.node(), second], expected_project_revision=1,
                           expected_plan_revision=0)
        view = read_project_plan(self.root, "project_mentat")
        self.assertIn("dependency_mismatch", view["stale_reasons"])
        self.assertEqual(view["dependency_comparison"]["missing_from_plan"], [
            {"task_id": "task_layout", "prerequisite_id": "task_research"}])
        # A second Project can still prepare an extra sequencing edge, but it
        # must be shown as different from the canonical Task dependency graph.
        # This fixture creates a new plan version after the Task dependency is
        # removed and its input is explicitly republished.
        mutate_authoritative_tasks(self.root, lambda rows: ([rows[0], {key: value for key, value in rows[1].items() if key != "depends_on"}], None))
        payload = {**self.fixture.payload, "task_id": "task_layout", "attachment_ids": [],
                   "expected_input_revision": 1,
                   "expected_task_revision": read_task_input_editor(self.root, "task_layout")["task"]["revision"],
                   "expected_task_token": read_task_input_editor(self.root, "task_layout")["expected_task_token"]}
        replacement = publish_task_inputs(self.root, payload)
        next_node = self.node(task_id="task_layout", expected_task_revision=payload["expected_task_revision"],
                              input_version_id=replacement["input_id"], after=["task_research"], segment=1)
        publish_owner_plan(self.root, "project_mentat", "Extra sequence",
                           [self.node(), next_node], expected_project_revision=1,
                           expected_plan_revision=1)
        next_view = read_project_plan(self.root, "project_mentat")
        self.assertIn("dependency_mismatch", next_view["stale_reasons"])
        self.assertEqual(next_view["dependency_comparison"]["additional_in_plan"], [
            {"task_id": "task_layout", "prerequisite_id": "task_research"}])

    def test_plan_protects_referenced_input_from_retired_pruning(self):
        self.publish()
        publish_task_inputs(self.root, {**self.fixture.payload, "expected_input_revision": 1,
                                        "instructions": "New instructions"})
        with self.assertRaisesRegex(TaskInputError, "retained_plan"):
            preview_task_input_prune(self.root, self.first["input_id"])
        public, status = dispatch_task_inputs(self.root, "prune-preview", {"input_id": self.first["input_id"]})
        self.assertEqual((status, public["status"]), (409, "retained_plan"))
        self.assertIn("input_changed", read_project_plan(self.root, "project_mentat")["stale_reasons"])

    def test_task_id_reuse_does_not_reactivate_historical_plan(self):
        self.publish()
        mutate_authoritative_tasks(self.root, lambda rows: ([], None))
        mutate_authoritative_tasks(self.root, lambda rows: ([{**task("task_research"),
            "project_id": "project_mentat", "assigned_agent_id": "agent_research"}], None))
        view = read_project_plan(self.root, "project_mentat")
        self.assertIn("task_changed", view["stale_reasons"])
        with closing(mentat_db.connect(self.root)) as connection:
            validate_plan_connection(connection)

    def test_revoked_context_grant_stales_plan_and_blocks_new_publication(self):
        self.publish()
        project_context_access.revoke_context_grant(
            self.root, "project_mentat", self.fixture.context["id"], "agent_research",
            expected_revision=1,
        )
        self.assertIn("grant_changed", read_project_plan(self.root, "project_mentat")["stale_reasons"])
        with self.assertRaisesRegex(ProjectPlanError, "grant_changed"):
            publish_owner_plan(self.root, "project_mentat", "Changed plan", [self.node()],
                               expected_project_revision=1, expected_plan_revision=1)

    def test_reviewed_deletion_snapshot_binds_plan_and_retains_history(self):
        service = PlanningDeletionService(self.root)
        prior = service.preview("project", "project_mentat")
        saved = self.publish()
        with self.assertRaisesRegex(PlanningDeletionError, "deletion_stale"):
            service.finalize(prior)
        fresh = service.preview("project", "project_mentat")
        self.assertEqual(fresh.retained_plan_versions, 1)
        service.finalize(fresh)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT id FROM mentat_plan_versions").fetchone()[0], saved["id"])
            self.assertIsNotNone(connection.execute("SELECT retired_at FROM mentat_plan_scopes").fetchone()[0])
            validate_plan_connection(connection)
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, project("Garage Again", "project_mentat")], None))
        replacement = read_project_plan(self.root, "project_mentat")
        self.assertEqual(replacement["plan_revision"], 0)
        self.assertIsNone(replacement["current"])

    def test_concurrent_same_revision_only_one_plan_publishes(self):
        barrier = Barrier(2)
        outcomes = []
        def worker():
            barrier.wait(timeout=10)
            try: outcomes.append(self.publish())
            except ProjectPlanError as exc: outcomes.append(str(exc))
        threads = [Thread(target=worker) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sum(isinstance(item, dict) for item in outcomes), 1)
        self.assertEqual(sum(item == "project_plan.revision_conflict" for item in outcomes), 1)

    def test_per_scope_version_ceiling_fails_closed(self):
        self.publish()
        with closing(mentat_db.connect(self.root)) as connection:
            source = connection.execute(
                "SELECT scope_id,project_revision,format,content_json,content_digest,origin,created_at "
                "FROM mentat_plan_versions WHERE revision=1"
            ).fetchone()
            scope_id = source[0]
            for revision in range(2, 33):
                identifier = f"plan_version_{revision:032x}"
                connection.execute("INSERT INTO mentat_plan_versions VALUES(?,?,?,?,?,?,?,?,?)",
                                   (identifier, scope_id, revision, *tuple(source)[1:-1], source[-1] + revision))
                connection.execute("INSERT INTO mentat_plan_input_refs VALUES(?,?)",
                                   (identifier, self.first["input_id"]))
            connection.execute("UPDATE mentat_plan_scopes SET head_revision=32 WHERE id=?", (scope_id,))
            connection.commit()
            validate_plan_connection(connection)
        with self.assertRaisesRegex(ProjectPlanError, "capacity"):
            publish_owner_plan(self.root, "project_mentat", "One too many", [self.node()],
                               expected_project_revision=1, expected_plan_revision=32)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_plan_versions").fetchone()[0], 32)

    def test_global_version_ceiling_includes_all_project_scopes(self):
        self.publish()
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, *[
            project(f"Garage {index}", f"project_garage_{index}") for index in range(2, 10)
        ]], None))
        mutate_authoritative_tasks(self.root, lambda rows: ([*rows, *[
            {**task(f"task_garage_{index}"), "project": f"Garage {index}",
             "project_id": f"project_garage_{index}",
             "assigned_agent_id": "agent_research"} for index in range(2, 10)
        ]], None))
        ninth_input = None
        for index in range(2, 10):
            project_id, task_id = f"project_garage_{index}", f"task_garage_{index}"
            context = project_context.publish_project_context(
                self.root, project_id, expected_project_revision=1, expected_revision=0,
                brief="Garage goals", attachment_ids=[],
            )
            preview = project_context_access.preview_context_grant(
                self.root, project_id, context["id"], "agent_research",
            )
            project_context_access.confirm_context_grant(
                self.root, project_id, context["id"], "agent_research",
                confirmation_id=preview["confirmation_id"],
            )
            payload = {**self.fixture.payload, "project_id": project_id, "task_id": task_id,
                       "context_id": context["id"], "attachment_ids": [],
                       "expected_task_token": read_task_input_editor(self.root, task_id)["expected_task_token"]}
            saved_input = publish_task_inputs(self.root, payload)
            if index == 9:
                ninth_input = saved_input["input_id"]
            else:
                publish_owner_plan(self.root, project_id, "Garage plan",
                                   [self.node(task_id=task_id, input_version_id=saved_input["input_id"])],
                                   expected_project_revision=1, expected_plan_revision=0)
        with closing(mentat_db.connect(self.root)) as connection:
            for scope_index, (scope_id,) in enumerate(connection.execute(
                "SELECT id FROM mentat_plan_scopes ORDER BY id"
            ), 1):
                source = connection.execute(
                    "SELECT project_revision,format,content_json,content_digest,origin,created_at "
                    "FROM mentat_plan_versions WHERE scope_id=? AND revision=1", (scope_id,),
                ).fetchone()
                input_id = connection.execute(
                    "SELECT r.input_id FROM mentat_plan_input_refs r JOIN mentat_plan_versions v "
                    "ON v.id=r.version_id WHERE v.scope_id=? AND v.revision=1", (scope_id,),
                ).fetchone()[0]
                for revision in range(2, 33):
                    identifier = f"plan_version_{scope_index:02x}{revision:030x}"
                    connection.execute("INSERT INTO mentat_plan_versions VALUES(?,?,?,?,?,?,?,?,?)",
                                       (identifier, scope_id, revision, *tuple(source)[:-1], source[-1] + revision))
                    connection.execute("INSERT INTO mentat_plan_input_refs VALUES(?,?)", (identifier, input_id))
                connection.execute("UPDATE mentat_plan_scopes SET head_revision=32 WHERE id=?", (scope_id,))
            connection.commit()
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_plan_versions").fetchone()[0], 256)
            validate_plan_connection(connection)
        with self.assertRaisesRegex(ProjectPlanError, "capacity"):
            publish_owner_plan(self.root, "project_garage_9", "Blocked by global cap",
                               [self.node(task_id="task_garage_9", input_version_id=ninth_input)],
                               expected_project_revision=1, expected_plan_revision=0)

    def test_public_node_contract_rejects_widened_or_cyclic_graph(self):
        with self.assertRaises(ProjectPlanError):
            normalize_owner_plan("Garage\u202e", [self.node()])
        for nodes in ([], [self.node(after=["task_research"])], [self.node(runtime_ref="private")],
                      [self.node(), self.node()], [self.node(segment=2)]):
            with self.subTest(nodes=nodes), self.assertRaises(ProjectPlanError):
                normalize_owner_plan("Garage", nodes)
