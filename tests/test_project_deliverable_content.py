from io import BytesIO
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
import unittest
from unittest.mock import patch

from PIL import Image

import agent_console_attachments
import mentat_db
import private_console_unit
import project_context
from project_deliverables import DeliverableError, content_digest, normalize_content, publish_owner_edit, read_deliverable_preview, read_deliverable_version, read_project_deliverables, read_retired_deliverable_history, read_retired_deliverable_version, render_document, render_layout_png, safe_product_url
from project_repository import mutate_authoritative_projects
from task_repository import _schema5_private_unit
from task_repository import mutate_authoritative_tasks
from tests import test_project_context as context_tests
from tests.test_project_repository import project
from tests.test_task_repository import task


def garage_layout():
    return {
        "width_mm": 6000, "depth_mm": 5000, "notes": "Keep the bicycles near the side door.",
        "openings": [{"edge": "south", "offset_mm": 1300, "width_mm": 2400, "kind": "garage_door"}],
        "placements": [
            {"id": "shelves", "kind": "storage", "label": "Wall shelves", "x_mm": 100,
             "y_mm": 100, "width_mm": 1800, "depth_mm": 500},
            {"id": "bench", "kind": "workbench", "label": "Workbench", "x_mm": 3900,
             "y_mm": 100, "width_mm": 1600, "depth_mm": 700},
        ],
    }


class DeliverableContentTests(unittest.TestCase):
    def test_exact_schema_30_upgrades_without_creating_deliverables(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "schema30.sqlite3"
            private_console_unit._initialize_database(path, schema_version=30)
            with closing(sqlite3.connect(path)) as connection:
                mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 34)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_deliverable_versions").fetchone()[0], 0)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "drifted-schema30.sqlite3"
            private_console_unit._initialize_database(path, schema_version=30)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP VIEW mentat_retained_attachments")
                connection.execute("CREATE VIEW mentat_retained_attachments AS SELECT attachment_id FROM run_attachments")
                with self.assertRaises(mentat_db.MentatDatabaseError):
                    mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 30)

    def test_dimensioned_garage_layout_has_bounded_render_and_digest(self):
        layout = normalize_content("layout", garage_layout())
        png = render_layout_png(layout)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.size, (1200, 900))
            self.assertEqual(image.format, "PNG")
        self.assertEqual(content_digest(layout), content_digest(normalize_content("layout", garage_layout())))

    def test_missing_or_invented_dimensions_and_outside_placements_fail(self):
        for value in (
            {**garage_layout(), "width_mm": None},
            {**garage_layout(), "width_mm": True},
            {**garage_layout(), "width_mm": 0},
            {**garage_layout(), "placements": [{**garage_layout()["placements"][0], "x_mm": 5900}]},
            {**garage_layout(), "openings": [{"edge": "south", "offset_mm": 5000, "width_mm": 2400, "kind": "garage_door"}]},
            {**garage_layout(), "openings": [{"edge": {}, "offset_mm": 0, "width_mm": 1000, "kind": "door"}]},
            {**garage_layout(), "placements": [{**garage_layout()["placements"][0], "kind": []}]},
        ):
            with self.subTest(value=value), self.assertRaises(DeliverableError):
                normalize_content("layout", value)

    def test_products_preserve_exact_public_links_and_reject_unsafe_destinations(self):
        content = {"notes": "Compare prices before buying.", "items": [
            {"id": "shelf_1", "name": "Wall shelf", "quantity": 2,
             "url": "https://example.com/shelves?size=large", "notes": "Check wall anchors."},
        ]}
        self.assertEqual(normalize_content("products", content)["items"][0]["url"], content["items"][0]["url"])
        document = render_document("products", content)
        self.assertIn("[Source](https://example.com/shelves?size=large)", document)
        for url in ("http://example.com/", "https://localhost/", "https://127.0.0.1/",
                    "https://127.0.0.01/", "https://0x7f.0x0.0x0.0x1/", "https://127.1/",
                    "https://user@example.com/", "https://example.com:8080/", "javascript:alert(1)",
                    "https://example.com\\@evil.test/", "https://example.com/#secret",
                    "https://example.com/a)(javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(DeliverableError):
                safe_product_url(url)

    def test_steps_are_ordered_and_dependencies_name_prior_steps_only(self):
        steps = {"notes": "Keep a vehicle bay open.", "steps": [
            {"id": "measure", "title": "Measure walls", "details": "Confirm actual dimensions.", "after": []},
            {"id": "mount", "title": "Install shelves", "details": "Locate studs.", "after": ["measure"]},
        ]}
        self.assertEqual(normalize_content("steps", steps)["steps"][1]["after"], ["measure"])
        for after in (["future"], ["mount"], ["measure", "measure"], [["measure"]]):
            with self.subTest(after=after), self.assertRaises(DeliverableError):
                normalize_content("steps", {**steps, "steps": [{**steps["steps"][0], "after": after}, *steps["steps"][1:]]})


class OwnerDeliverableStorageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = context_tests.ProjectContextTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def test_owner_layout_edit_keeps_exact_versions_preview_and_backup(self):
        first = publish_owner_edit(self.root, "project_mentat", "layout", garage_layout(),
                                   expected_project_revision=1, expected_slot_revision=0)
        self.assertEqual(first["revision"], 1)
        preview = agent_console_attachments.read_attachment_bytes(self.root, first["preview_attachment_id"])[1]
        self.assertTrue(preview.startswith(b"\x89PNG\r\n\x1a\n"))
        with self.assertRaisesRegex(DeliverableError, "revision_conflict"):
            publish_owner_edit(self.root, "project_mentat", "layout", garage_layout(),
                               expected_project_revision=1, expected_slot_revision=0)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0], 1)
        second = publish_owner_edit(self.root, "project_mentat", "layout",
                                    {**garage_layout(), "notes": "Revised owner layout"},
                                    expected_project_revision=1, expected_slot_revision=1,
                                    source_version_id=first["version_id"])
        self.assertEqual(second["revision"], 2)
        view = read_project_deliverables(self.root, "project_mentat")
        self.assertEqual(view["slots"][0]["versions"][0]["content"]["notes"], "Revised owner layout")
        self.assertIsNone(view["slots"][0]["versions"][1]["content"])
        self.assertEqual(read_deliverable_version(self.root, "project_mentat", first["version_id"])["content"], garage_layout())
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, project("Other", "project_other")], None))
        with self.assertRaisesRegex(DeliverableError, "version_unavailable"):
            read_deliverable_version(self.root, "project_other", first["version_id"])
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_deliverable_versions").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT source_version_id FROM mentat_deliverable_versions WHERE id=?",
                                                (second["version_id"],)).fetchone()[0], first["version_id"])
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM mentat_deliverable_versions WHERE id=?", (first["version_id"],))
            connection.rollback()
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)
        restored = private_console_unit.sanitize_owner_auth_restore_unit(unit)
        private_console_unit.validate_private_console_unit(restored)
        compatible = _schema5_private_unit(unit)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "compatible.sqlite3"
            path.write_bytes(compatible.database_raw)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 5)
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='mentat_deliverable_versions'",
                ).fetchone())

    def test_products_and_steps_are_owner_versions_without_run_provenance(self):
        products = publish_owner_edit(self.root, "project_mentat", "products",
                                      {"items": [{"id": "shelf", "name": "Wall shelf", "quantity": 2,
                                                  "url": "https://example.com/shelf", "notes": "Check anchors"}], "notes": "Compare sources"},
                                      expected_project_revision=1, expected_slot_revision=0)
        steps = publish_owner_edit(self.root, "project_mentat", "steps",
                                   {"steps": [{"id": "measure", "title": "Confirm dimensions", "details": "Measure twice", "after": []}],
                                    "notes": "Keep bicycle access clear"},
                                   expected_project_revision=1, expected_slot_revision=0)
        self.assertIsNone(products["preview_attachment_id"])
        self.assertIsNone(steps["preview_attachment_id"])
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual([tuple(row) for row in connection.execute(
                "SELECT origin,source_run_id FROM mentat_deliverable_versions ORDER BY id")],
                [("owner_edit", None), ("owner_edit", None)])

    def test_project_deletion_retires_versions_before_id_reuse(self):
        first = publish_owner_edit(self.root, "project_mentat", "layout", garage_layout(),
                                   expected_project_revision=1, expected_slot_revision=0)
        service = self.fixture.deletion_service()
        deletion = service.preview("project", "project_mentat")
        self.assertEqual(deletion.retained_deliverable_versions, 1)
        service.finalize(deletion)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertIsNotNone(connection.execute(
                "SELECT retired_at FROM mentat_deliverable_slots WHERE id=?", (first["slot_id"],),
            ).fetchone()[0])
        self.assertEqual(read_retired_deliverable_history(self.root)["versions"][0]["id"], first["version_id"])
        self.assertEqual(read_retired_deliverable_version(self.root, first["version_id"])["content"], garage_layout())
        self.assertTrue(read_deliverable_preview(self.root, first["version_id"]).startswith(b"\x89PNG"))
        agent_console_attachments.garbage_collect(self.root, now=9999999999, orphan_grace=0)
        self.assertTrue(read_deliverable_preview(self.root, first["version_id"]).startswith(b"\x89PNG"))
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, project("New Garage", "project_mentat")], None))
        second = publish_owner_edit(self.root, "project_mentat", "layout",
                                    {**garage_layout(), "notes": "New lifetime"},
                                    expected_project_revision=1, expected_slot_revision=0)
        self.assertNotEqual(first["slot_id"], second["slot_id"])
        visible = read_project_deliverables(self.root, "project_mentat")
        self.assertEqual([item["id"] for item in visible["slots"]], [second["slot_id"]])

    def test_task_deletion_discloses_but_does_not_remove_associated_deliverable(self):
        mutate_authoritative_tasks(self.root, lambda rows: (
            [*rows, {**task("task_layout"), "project_id": "project_mentat"}], None,
        ))
        version = publish_owner_edit(self.root, "project_mentat", "steps",
                                     {"steps": [], "notes": "Attach after Task review"},
                                     expected_project_revision=1, expected_slot_revision=0,
                                     associated_task_id="task_layout", expected_task_revision=1)
        service = self.fixture.deletion_service()
        deletion = service.preview("task", "task_layout")
        self.assertEqual(deletion.retained_deliverable_versions, 1)
        service.finalize(deletion)
        visible = read_project_deliverables(self.root, "project_mentat")
        self.assertEqual(visible["slots"][0]["versions"][0]["id"], version["version_id"])

    def test_unrelated_project_creation_and_rename_preserve_live_deliverable_identity(self):
        first = publish_owner_edit(self.root, "project_mentat", "layout", garage_layout(),
                                   expected_project_revision=1, expected_slot_revision=0)
        with closing(mentat_db.connect(self.root)) as connection:
            incarnation = connection.execute("SELECT deliverable_incarnation FROM mentat_projects WHERE id='project_mentat'").fetchone()[0]
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, project("Other", "project_other")], None))
        mutate_authoritative_projects(self.root, lambda rows: (
            [{**item, "name": "Renamed Garage"} if item["id"] == "project_mentat" else item for item in rows], None,
        ))
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT deliverable_incarnation FROM mentat_projects WHERE id='project_mentat'").fetchone()[0], incarnation)
            self.assertIsNone(connection.execute("SELECT retired_at FROM mentat_deliverable_slots WHERE id=?", (first["slot_id"],)).fetchone()[0])
        visible = read_project_deliverables(self.root, "project_mentat")
        self.assertEqual(visible["project"]["name"], "Renamed Garage")
        self.assertEqual(visible["slots"][0]["versions"][0]["id"], first["version_id"])

    def test_project_reorder_and_name_swap_do_not_retire_versions(self):
        first = publish_owner_edit(self.root, "project_mentat", "steps",
                                   {"steps": [], "notes": "Keep this history"},
                                   expected_project_revision=1, expected_slot_revision=0)
        mutate_authoritative_projects(self.root, lambda rows: ([*rows, project("Other", "project_other")], None))
        def swap(rows):
            by_id = {item["id"]: item for item in rows}
            return ([{**by_id["project_other"], "name": "Garage"},
                     {**by_id["project_mentat"], "name": "Other"}], None)
        mutate_authoritative_projects(self.root, swap)
        visible = read_project_deliverables(self.root, "project_mentat")
        self.assertEqual(visible["project"]["name"], "Other")
        self.assertEqual(visible["slots"][0]["versions"][0]["id"], first["version_id"])

    def test_new_deliverable_invalidates_exact_project_deletion_preview(self):
        from planning_deletion import PlanningDeletionError
        service = self.fixture.deletion_service()
        old = service.preview("project", "project_mentat")
        publish_owner_edit(self.root, "project_mentat", "steps",
                           {"steps": [], "notes": "New owner result"},
                           expected_project_revision=1, expected_slot_revision=0)
        with self.assertRaises(PlanningDeletionError):
            service.finalize(old)
        self.assertEqual(service.preview("project", "project_mentat").retained_deliverable_versions, 1)

    def test_failed_layout_publication_releases_its_staged_preview(self):
        with patch("agent_console_attachments.read_attachment_bytes", side_effect=agent_console_attachments.AttachmentUnavailable("unavailable")):
            with self.assertRaises(agent_console_attachments.AttachmentUnavailable):
                publish_owner_edit(self.root, "project_mentat", "layout", garage_layout(),
                                   expected_project_revision=1, expected_slot_revision=0)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_deliverable_versions").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM attachments WHERE state='staged'").fetchone()[0], 0)

    def test_shared_metadata_budget_rolls_back_layout_and_preview(self):
        with patch("project_context.PLAN_MAX_METADATA_BYTES", 100):
            with self.assertRaisesRegex(project_context.ProjectContextError, "capacity"):
                publish_owner_edit(self.root, "project_mentat", "layout", garage_layout(),
                                   expected_project_revision=1, expected_slot_revision=0)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_deliverable_versions").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM attachments WHERE state='staged'").fetchone()[0], 0)

    def test_forged_generated_provenance_remains_unavailable(self):
        owner = publish_owner_edit(self.root, "project_mentat", "products",
                                   {"items": [], "notes": "Owner research"},
                                   expected_project_revision=1, expected_slot_revision=0)
        with closing(mentat_db.connect(self.root)) as connection:
            source = connection.execute("SELECT content_json,content_digest FROM mentat_deliverable_versions WHERE id=?",
                                        (owner["version_id"],)).fetchone()
            connection.execute("UPDATE mentat_deliverable_slots SET head_revision=2 WHERE id=?", (owner["slot_id"],))
            connection.execute(
                "INSERT INTO mentat_deliverable_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("deliverable_version_" + "a" * 32, owner["slot_id"], 2, "generated", owner["version_id"],
                 None, None, source[0], source[1], "run_forged", "f" * 64, "task_forged", "a" * 32, 1790035200.0),
            )
            with self.assertRaisesRegex(project_context.ProjectContextError, "deliverables_invalid"):
                project_context.validate_project_context_connection(connection)
            connection.rollback()

    def test_concurrent_owner_edits_have_one_exact_revision_winner(self):
        barrier = Barrier(2)
        outcomes = []
        def save(note):
            barrier.wait(timeout=5)
            try:
                result = publish_owner_edit(self.root, "project_mentat", "steps",
                                            {"steps": [], "notes": note},
                                            expected_project_revision=1, expected_slot_revision=0)
                outcomes.append(("saved", result["revision"]))
            except DeliverableError as exc:
                outcomes.append(("rejected", str(exc)))
        workers = [Thread(target=save, args=(note,)) for note in ("Owner A", "Owner B")]
        for worker in workers: worker.start()
        for worker in workers: worker.join(timeout=15)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(sum(status == "saved" for status, _ in outcomes), 1)
        self.assertEqual(sum(status == "rejected" for status, _ in outcomes), 1)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_deliverable_versions").fetchone()[0], 1)
