from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
import unittest

import mentat_db
import private_console_unit
from project_deliverable_review import (
    DeliverableReviewError, SLOTS, confirm_review, preview_review, read_review_status,
    validate_review_connection,
)
from project_deliverables import publish_owner_edit
from planning_deletion import PlanningDeletionError, PlanningDeletionService
from tests import test_project_context as context_tests
from tests.test_project_deliverable_content import garage_layout


class DeliverableReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = context_tests.ProjectContextTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def _complete(self):
        versions = {}
        for slot, content in (
            ("layout", garage_layout()),
            ("products", {"items": [], "notes": "Check prices"}),
            ("steps", {"steps": [], "notes": "Measure before building"}),
        ):
            versions[slot] = publish_owner_edit(
                self.root, "project_mentat", slot, content,
                expected_project_revision=1, expected_slot_revision=0,
            )
        return versions

    def test_exact_schema_31_upgrade_and_drift_gate(self):
        self.assertEqual(
            private_console_unit.private_console_unit_digest(private_console_unit.empty_private_console_unit()),
            private_console_unit.private_console_unit_digest(private_console_unit.empty_private_console_unit()),
        )
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.sqlite3"
            private_console_unit._initialize_database(path, schema_version=31)
            with closing(sqlite3.connect(path)) as connection:
                mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 33)
                self.assertEqual(validate_review_connection(connection)[0][2], 0)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "drift.sqlite3"
            private_console_unit._initialize_database(path, schema_version=31)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP VIEW mentat_retained_attachments")
                connection.execute("CREATE VIEW mentat_retained_attachments AS SELECT attachment_id FROM run_attachments")
                with self.assertRaises(mentat_db.MentatDatabaseError):
                    mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 31)

    def test_accept_requires_complete_exact_heads_and_is_idempotent(self):
        self.assertEqual(read_review_status(self.root, "project_mentat")["status"], "incomplete")
        with self.assertRaisesRegex(DeliverableReviewError, "incomplete"):
            preview_review(self.root, "project_mentat", "accept", "", list(("layout", "products", "steps")))
        self._complete()
        preview = preview_review(self.root, "project_mentat", "accept", "", list(("layout", "products", "steps")))
        self.assertEqual([head["slot"] for head in preview["heads"]], ["layout", "products", "steps"])
        result = confirm_review(self.root, "project_mentat", "accept", "", list(("layout", "products", "steps")), preview["confirmation_id"])
        self.assertFalse(result["duplicate"])
        self.assertEqual(read_review_status(self.root, "project_mentat")["status"], "accept")
        repeated = confirm_review(self.root, "project_mentat", "accept", "", list(("layout", "products", "steps")), preview["confirmation_id"])
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(repeated["id"], result["id"])
        with self.assertRaisesRegex(DeliverableReviewError, "confirmation_conflict"):
            confirm_review(self.root, "project_mentat", "request_changes", "Fix the layout", ["layout"], preview["confirmation_id"])

    def test_changed_head_invalidates_preview_and_current_decision(self):
        versions = self._complete()
        preview = preview_review(self.root, "project_mentat", "request_changes", "Move shelves", ["layout"])
        publish_owner_edit(self.root, "project_mentat", "layout", {**garage_layout(), "notes": "Revised"},
                           expected_project_revision=1, expected_slot_revision=1,
                           source_version_id=versions["layout"]["version_id"])
        with self.assertRaisesRegex(DeliverableReviewError, "stale"):
            confirm_review(self.root, "project_mentat", "request_changes", "Move shelves", ["layout"], preview["confirmation_id"])
        fresh = preview_review(self.root, "project_mentat", "request_changes", "Move shelves", ["layout"])
        confirm_review(self.root, "project_mentat", "request_changes", "Move shelves", ["layout"], fresh["confirmation_id"])
        self.assertEqual(read_review_status(self.root, "project_mentat")["status"], "request_changes")
        publish_owner_edit(self.root, "project_mentat", "products", {"items": [], "notes": "Other"},
                           expected_project_revision=1, expected_slot_revision=1,
                           source_version_id=versions["products"]["version_id"])
        status = read_review_status(self.root, "project_mentat")
        self.assertEqual(status["status"], "pending")
        self.assertFalse(status["latest"]["current"])

    def test_invalid_requests_and_restore_rotate_preview_epoch(self):
        self._complete()
        for action, note, slots in (
            ("accept", "maybe", list(("layout", "products", "steps"))),
            ("accept", "", ["layout"]),
            ("request_changes", "", ["layout"]),
            ("request_changes", "fix", []),
            ("request_changes", "fix", [[], "layout"]),
        ):
            with self.subTest(action=action, note=note, slots=slots), self.assertRaises(DeliverableReviewError):
                preview_review(self.root, "project_mentat", action, note, slots)
        preview = preview_review(self.root, "project_mentat", "accept", "", list(("layout", "products", "steps")))
        before = private_console_unit.capture_private_console_unit(self.root)
        after = private_console_unit.sanitize_owner_auth_restore_unit(before)
        with TemporaryDirectory() as temporary:
            prior_path = Path(temporary) / "prior.sqlite3"
            path = Path(temporary) / "restored.sqlite3"
            prior_path.write_bytes(before.database_raw)
            path.write_bytes(after.database_raw)
            with closing(sqlite3.connect(path)) as connection:
                with closing(sqlite3.connect(prior_path)) as old:
                    prior = old.execute("SELECT confirmation_epoch FROM mentat_deliverable_review_state").fetchone()[0]
                current = connection.execute("SELECT confirmation_epoch FROM mentat_deliverable_review_state").fetchone()[0]
                self.assertNotEqual(current, prior)
        self.assertEqual(len(preview["confirmation_id"]), 64)

    def test_review_changes_deletion_snapshot_and_history_survives_project_delete(self):
        self._complete()
        service = PlanningDeletionService(self.root)
        old = service.preview("project", "project_mentat")
        reviewed = preview_review(self.root, "project_mentat", "accept", "", list(("layout", "products", "steps")))
        receipt = confirm_review(self.root, "project_mentat", "accept", "", list(("layout", "products", "steps")), reviewed["confirmation_id"])
        with self.assertRaisesRegex(PlanningDeletionError, "deletion_stale"):
            service.finalize(old)
        current = service.preview("project", "project_mentat")
        self.assertEqual(current.retained_deliverable_reviews, 1)
        service.finalize(current)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT id FROM mentat_deliverable_reviews").fetchone()[0], receipt["id"])
            validate_review_connection(connection)

    def test_first_real_preview_activates_empty_authority_epoch(self):
        self._complete()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute(
                "UPDATE mentat_deliverable_review_state SET confirmation_epoch=zeroblob(32) WHERE singleton=1"
            )
            connection.commit()
        preview = preview_review(self.root, "project_mentat", "accept", "", list(SLOTS))
        with closing(mentat_db.connect(self.root)) as connection:
            epoch = connection.execute("SELECT confirmation_epoch FROM mentat_deliverable_review_state").fetchone()[0]
            self.assertNotEqual(epoch, bytes(32))
        self.assertFalse(confirm_review(self.root, "project_mentat", "accept", "", list(SLOTS), preview["confirmation_id"])["duplicate"])

    def test_concurrent_exact_confirmations_commit_one_decision(self):
        self._complete()
        preview = preview_review(self.root, "project_mentat", "accept", "", list(SLOTS))
        barrier = Barrier(2)
        results = []
        def worker():
            barrier.wait(timeout=10)
            try:
                results.append(confirm_review(
                    self.root, "project_mentat", "accept", "", list(SLOTS), preview["confirmation_id"],
                ))
            except Exception as exc:
                results.append(exc)
        threads = [Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 2)
        self.assertEqual(sorted(result["duplicate"] for result in results), [False, True])
        self.assertEqual(results[0]["id"], results[1]["id"])
