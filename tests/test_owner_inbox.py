from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import mentat_db
import private_console_unit
from owner_inbox import _digest
from owner_inbox import OwnerInboxError, mark_item, read_inbox, read_inbox_page, read_result_review_item, preview_result_review_item, confirm_result_review_item, reconcile_inbox_at_startup, validate_inbox_connection
from project_deliverable_review import confirm_review, preview_review
from project_deliverables import DeliverableError, publish_owner_edit
from planning_deletion import PlanningDeletionService
from project_repository import mutate_authoritative_projects
from tests import test_project_context as context_tests
from tests.test_project_deliverable_content import garage_layout
from tests.test_project_repository import project


class OwnerInboxTests(unittest.TestCase):
    def setUp(self):
        self.fixture = context_tests.ProjectContextTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def complete(self):
        versions = {}
        for slot, content in (
            ("layout", garage_layout()),
            ("products", {"items": [], "notes": "Check prices"}),
            ("steps", {"steps": [], "notes": "Measure first"}),
        ):
            versions[slot] = publish_owner_edit(self.root, "project_mentat", slot, content,
                                                 expected_project_revision=1, expected_slot_revision=0)
        return versions

    def test_schema_33_upgrade_adds_empty_bounded_inbox_without_rewriting_sources(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.sqlite3"
            private_console_unit._initialize_database(path, schema_version=33)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 33)
                mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 35)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_inbox_items").fetchone()[0], 0)
                validate_inbox_connection(connection)

    def test_schema_34_upgrade_rejects_a_drifted_schema_33_source(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "drifted.sqlite3"
            private_console_unit._initialize_database(path, schema_version=33)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("ALTER TABLE mentat_projects ADD COLUMN unsafe_extension TEXT")
                with self.assertRaises(mentat_db.MentatDatabaseError):
                    mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 33)

    def test_exact_pending_generation_read_and_ack_are_durable_and_idempotent(self):
        self.assertEqual(read_inbox(self.root), [])
        self.complete()
        items = read_inbox(self.root)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual((item["state"], item["unread"], item["acknowledged"]), ("needs_review", True, False))
        first = mark_item(self.root, item["id"], action="read", expected_revision=item["revision"])
        self.assertFalse(first["duplicate"])
        self.assertTrue(mark_item(self.root, item["id"], action="read", expected_revision=item["revision"])["duplicate"])
        ack = mark_item(self.root, item["id"], action="acknowledge", expected_revision=first["revision"])
        self.assertFalse(ack["duplicate"])
        with self.assertRaisesRegex(OwnerInboxError, "stale"):
            mark_item(self.root, item["id"], action="acknowledge", expected_revision=item["revision"])
        self.assertEqual((read_inbox(self.root)[0]["unread"], read_inbox(self.root)[0]["acknowledged"]), (False, True))
        with closing(mentat_db.connect(self.root)) as connection:
            validate_inbox_connection(connection)

    def test_page_filters_keep_acknowledged_unresolved_work_visible(self):
        self.complete()
        first = read_inbox_page(self.root)
        self.assertEqual((len(first["items"]), first["counts"]), (1, {"needs_me": 1, "unread": 1, "all": 1}))
        item = first["items"][0]
        marked = mark_item(self.root, item["id"], action="read", expected_revision=item["revision"])
        mark_item(self.root, item["id"], action="acknowledge", expected_revision=marked["revision"])
        self.assertEqual(read_inbox_page(self.root)["counts"], {"needs_me": 1, "unread": 0, "all": 1})
        self.assertEqual(read_inbox_page(self.root, view="unread")["items"], [])
        self.assertEqual(read_inbox_page(self.root, view="needs_me")["items"][0]["id"], item["id"])

    def test_page_cursor_is_exact_and_stale_when_filter_membership_changes(self):
        versions = self.complete()
        first_id = read_inbox_page(self.root)["items"][0]["id"]
        publish_owner_edit(self.root, "project_mentat", "layout", {**garage_layout(), "notes": "Revision"},
                           expected_project_revision=1, expected_slot_revision=1,
                           source_version_id=versions["layout"]["version_id"])
        page = read_inbox_page(self.root, view="all", limit=1)
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["next_cursor"], page["items"][0]["id"])
        older = read_inbox_page(self.root, view="all", after=page["next_cursor"], limit=1)
        self.assertEqual((older["items"][0]["id"], older["next_cursor"]), (first_id, None))
        with self.assertRaisesRegex(OwnerInboxError, "stale"):
            read_inbox_page(self.root, view="needs_me", after=first_id)

    def test_exact_accept_or_change_request_resolves_without_resurrection(self):
        versions = self.complete()
        first = read_inbox(self.root)[0]
        preview = preview_review(self.root, "project_mentat", "request_changes", "Move shelves", ["layout"])
        confirm_review(self.root, "project_mentat", "request_changes", "Move shelves", ["layout"], preview["confirmation_id"])
        self.assertEqual(read_inbox(self.root)[0]["state"], "resolved")
        self.assertEqual(read_inbox(self.root)[0]["id"], first["id"])
        publish_owner_edit(self.root, "project_mentat", "layout", {**garage_layout(), "notes": "Revised"},
                           expected_project_revision=1, expected_slot_revision=1,
                           source_version_id=versions["layout"]["version_id"])
        items = read_inbox(self.root)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["state"], "needs_review")
        self.assertNotEqual(items[0]["id"], first["id"])
        preview = preview_review(self.root, "project_mentat", "accept", "", ["layout", "products", "steps"])
        confirm_review(self.root, "project_mentat", "accept", "", ["layout", "products", "steps"], preview["confirmation_id"])
        self.assertTrue(all(item["state"] == "resolved" for item in read_inbox(self.root)))

    def test_item_bound_review_confirmation_replays_only_same_source_generation(self):
        versions = self.complete()
        item = read_inbox(self.root)[0]
        preview = preview_review(self.root, "project_mentat", "accept", "", ["layout", "products", "steps"],
                                 inbox_item_id=item["id"])
        first = confirm_review(self.root, "project_mentat", "accept", "", ["layout", "products", "steps"],
                               preview["confirmation_id"], inbox_item_id=item["id"])
        self.assertFalse(first["duplicate"])
        self.assertTrue(confirm_review(self.root, "project_mentat", "accept", "", ["layout", "products", "steps"],
                                       preview["confirmation_id"], inbox_item_id=item["id"])["duplicate"])
        publish_owner_edit(self.root, "project_mentat", "layout", {**garage_layout(), "notes": "New"},
                           expected_project_revision=1, expected_slot_revision=1,
                           source_version_id=versions["layout"]["version_id"])
        new_item = read_inbox_page(self.root)["items"][0]
        with self.assertRaisesRegex(OwnerInboxError, "stale"):
            confirm_review(self.root, "project_mentat", "accept", "", ["layout", "products", "steps"],
                           preview["confirmation_id"], inbox_item_id=new_item["id"])
        self.assertTrue(confirm_review(self.root, "project_mentat", "accept", "", ["layout", "products", "steps"],
                                       preview["confirmation_id"], inbox_item_id=item["id"])["duplicate"])

    def test_item_bound_open_displays_exact_three_heads_before_review(self):
        self.complete()
        item = read_inbox_page(self.root)["items"][0]
        opened = read_result_review_item(self.root, item["id"])
        self.assertEqual(opened["item"]["state"], "needs_review")
        self.assertEqual(opened["review"]["status"], "pending")
        self.assertEqual([slot["slot"] for slot in opened["project"]["slots"]], ["layout", "products", "steps"])
        self.assertTrue(all(slot["versions"][0]["content"] is not None for slot in opened["project"]["slots"]))
        preview = preview_result_review_item(self.root, item["id"], "accept", "", ["layout", "products", "steps"])
        decision = confirm_result_review_item(self.root, item["id"], "accept", "",
                                              ["layout", "products", "steps"], preview["confirmation_id"])
        self.assertFalse(decision["duplicate"])
        self.assertTrue(confirm_result_review_item(self.root, item["id"], "accept", "",
                                                   ["layout", "products", "steps"], preview["confirmation_id"])["duplicate"])
        retained = read_result_review_item(self.root, item["id"])
        self.assertEqual(retained["item"]["state"], "resolved")
        self.assertEqual([version["slot"] for version in retained["versions"]], ["layout", "products", "steps"])
        self.assertEqual(retained["versions"][0]["content"]["notes"], "Keep the bicycles near the side door.")

    def test_item_bound_open_closes_controls_when_decision_lands_during_read(self):
        self.complete()
        item = read_inbox_page(self.root)["items"][0]
        from project_deliverable_review import read_review_status
        def decide_during_read(data_dir, project_id):
            status = read_review_status(data_dir, project_id)
            preview = preview_review(data_dir, project_id, "accept", "", ["layout", "products", "steps"])
            confirm_review(data_dir, project_id, "accept", "", ["layout", "products", "steps"], preview["confirmation_id"])
            return status
        with patch("project_deliverable_review.read_review_status", side_effect=decide_during_read):
            with self.assertRaisesRegex(OwnerInboxError, "stale"):
                read_result_review_item(self.root, item["id"])

    def test_backup_validator_rejects_wrong_source_generation(self):
        self.complete()
        item = read_inbox(self.root)[0]
        with closing(mentat_db.connect(self.root)) as connection:
            # Immutable-source trigger rejects tampering before the backup validator.
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE mentat_inbox_items SET generation_digest=? WHERE id=?",
                                   ("0" * 64, item["id"]))
            connection.execute("DROP TRIGGER mentat_inbox_source_immutable")
            connection.execute("UPDATE mentat_inbox_items SET generation_digest=? WHERE id=?",
                               ("0" * 64, item["id"]))
            with self.assertRaisesRegex(OwnerInboxError, "invalid"):
                validate_inbox_connection(connection)

    def test_startup_reconciles_preexisting_pending_bundle_once(self):
        self.complete()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("DELETE FROM mentat_inbox_items")
            connection.commit()
        reconcile_inbox_at_startup(self.root)
        first = read_inbox(self.root)
        reconcile_inbox_at_startup(self.root)
        self.assertEqual(read_inbox(self.root), first)
        self.assertEqual(len(first), 1)

    def test_backup_validator_rejects_suppressed_current_attention(self):
        self.complete()
        item = read_inbox(self.root)[0]
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("UPDATE mentat_inbox_items SET resolved_at=updated_at,revision=revision+1 WHERE id=?",
                               (item["id"],))
            with self.assertRaisesRegex(OwnerInboxError, "source_state_invalid"):
                validate_inbox_connection(connection)

    def test_backup_validator_rejects_ack_receipt_without_ack_state(self):
        self.complete()
        item = read_inbox(self.root)[0]
        mark_item(self.root, item["id"], action="read", expected_revision=1)
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute(
                "UPDATE mentat_inbox_items SET last_action_digest=? WHERE id=?",
                (_digest([item["id"], "acknowledge", 1]), item["id"]),
            )
            with self.assertRaisesRegex(OwnerInboxError, "receipt_invalid"):
                validate_inbox_connection(connection)

    def test_backup_validator_bounds_blob_typed_receipt(self):
        self.complete()
        item = read_inbox(self.root)[0]
        mark_item(self.root, item["id"], action="read", expected_revision=1)
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("UPDATE mentat_inbox_items SET last_action_digest=? WHERE id=?",
                               (bytes(64), item["id"]))
            with self.assertRaisesRegex(OwnerInboxError, "invalid"):
                validate_inbox_connection(connection)

    def test_nonactive_and_deleted_project_never_open_as_current_review(self):
        self.complete()
        item = read_inbox(self.root)[0]
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("UPDATE mentat_projects SET status='paused' WHERE id='project_mentat'")
            connection.commit()
        self.assertEqual(read_inbox(self.root)[0]["state"], "activation_required")
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("UPDATE mentat_projects SET status='archived' WHERE id='project_mentat'")
            connection.commit()
        self.assertEqual(read_inbox(self.root)[0]["state"], "activation_required")
        service = PlanningDeletionService(self.root)
        service.finalize(service.preview("project", "project_mentat"))
        retained = read_inbox(self.root)[0]
        self.assertEqual((retained["id"], retained["state"], retained["title"]),
                         (item["id"], "resolved", "Retained Project results"))
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, project("New Garage", "project_mentat")], None))
        self.assertEqual((read_inbox(self.root)[0]["id"], read_inbox(self.root)[0]["title"]),
                         (item["id"], "Retained Project results"))
        historical = read_result_review_item(self.root, item["id"])
        self.assertEqual(historical["item"]["state"], "resolved")
        self.assertEqual(historical["versions"][0]["content"]["notes"], "Keep the bicycles near the side door.")
        self.assertIsNone(historical["project"])

    def test_full_unresolved_inbox_rolls_back_new_result_version(self):
        versions = self.complete()
        first = read_inbox(self.root)[0]
        with patch("owner_inbox.MAX_RESULT_ITEMS", 1):
            with self.assertRaisesRegex(DeliverableError, "inbox_capacity"):
                publish_owner_edit(self.root, "project_mentat", "layout", {**garage_layout(), "notes": "Revised"},
                                   expected_project_revision=1, expected_slot_revision=1,
                                   source_version_id=versions["layout"]["version_id"])
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_deliverable_versions").fetchone()[0], 3)
            validate_inbox_connection(connection)
        self.assertEqual((read_inbox(self.root)[0]["id"], read_inbox(self.root)[0]["state"]),
                         (first["id"], "needs_review"))

    def test_private_backup_restore_preserves_exact_read_state_without_work(self):
        self.complete()
        item = read_inbox(self.root)[0]
        mark_item(self.root, item["id"], action="acknowledge", expected_revision=item["revision"])
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)
        restored = private_console_unit.sanitize_owner_auth_restore_unit(unit)
        private_console_unit.validate_private_console_unit(restored)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "restored.sqlite3"
            path.write_bytes(restored.database_raw)
            with closing(sqlite3.connect(path)) as connection:
                validate_inbox_connection(connection)
                row = connection.execute(
                    "SELECT id,read_at,acknowledged_at,resolved_at FROM mentat_inbox_items"
                ).fetchone()
                self.assertEqual(row[0], item["id"])
                self.assertIsNotNone(row[1])
                self.assertIsNotNone(row[2])
                self.assertIsNone(row[3])
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0], 0)
