from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from mentat_db import SCHEMA_VERSION, connect, database_path
from project_repository import (
    ProjectRepositoryConflict,
    ensure_project_sqlite_authority,
    mutate_authoritative_projects,
    read_authoritative_projects,
)
from task_repository import (
    TaskRepository,
    TaskRepositoryConflict,
    TaskRepositoryValidationError,
    ensure_task_sqlite_authority,
    mutate_authoritative_tasks,
    read_authoritative_tasks,
)


def task(project: str = "Mentat") -> dict:
    return {
        "id": "task_pt1a",
        "title": "Protect Project membership",
        "description": "",
        "project": project,
        "status": "todo",
        "priority": "medium",
        "assignee": None,
        "due_date": None,
        "source": "test",
        "tags": [],
        "review_required": False,
        "needs_attention": False,
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
        "completed_at": None,
    }


def project(name: str = "Mentat", identifier: str = "project_mentat") -> dict:
    return {
        "id": identifier,
        "name": name,
        "type": "software",
        "status": "active",
        "description": "",
        "obsidian_note": "",
        "aliases": ["Agent OS"] if name == "Mentat" else [],
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
    }


class ProjectRepositoryTests(unittest.TestCase):
    def root(self, temporary: str, *, task_project: str = "Mentat") -> Path:
        root = Path(temporary)
        (root / "tasks.json").write_text(json.dumps([task(task_project)]), encoding="utf-8")
        (root / "projects.json").write_text(json.dumps([project()]), encoding="utf-8")
        ensure_task_sqlite_authority(root, required_source_mode=None)
        return root

    def test_cutover_claims_receipt_and_maps_every_task_to_immutable_project_id(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            receipt = ensure_project_sqlite_authority(root, required_source_mode=None)

            self.assertEqual(receipt.source_project_count, 1)
            self.assertEqual(read_authoritative_projects(root)[0]["id"], "project_mentat")
            self.assertEqual(read_authoritative_tasks(root)[0]["project_id"], "project_mentat")

            connection = connect(root)
            try:
                repository = TaskRepository(connection)
                snapshot = repository.get("task_pt1a")
                with self.assertRaises(TaskRepositoryConflict):
                    repository.replace(
                        {**snapshot.document, "project_id": "project_other"},
                        expected_revision=snapshot.revision,
                    )
            finally:
                connection.close()
            self.assertEqual(ensure_project_sqlite_authority(root, required_source_mode=None), receipt)

    def test_cutover_rejects_unknown_legacy_task_project_without_partial_claim(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary, task_project="Missing")
            with self.assertRaisesRegex(ProjectRepositoryConflict, "task_project_missing"):
                ensure_project_sqlite_authority(root, required_source_mode=None)

            connection = connect(root)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_projects").fetchone()[0], 0)
                self.assertIsNone(connection.execute("SELECT project_id FROM mentat_tasks").fetchone()[0])
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_project_store_state").fetchone()[0], 0)
            finally:
                connection.close()

    def test_authoritative_reads_do_not_consult_changed_projects_json(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            ensure_project_sqlite_authority(root, required_source_mode=None)
            (root / "projects.json").write_text(json.dumps([project("Rewritten", "project_rewritten")]), encoding="utf-8")

            self.assertEqual(read_authoritative_projects(root)[0]["name"], "Mentat")
            self.assertEqual(read_authoritative_tasks(root)[0]["project_id"], "project_mentat")

    def test_schema18_refuses_forward_versions_before_a_consumer_can_open_it(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            ensure_project_sqlite_authority(root, required_source_mode=None)
            raw = sqlite3.connect(database_path(root))
            try:
                raw.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)", (SCHEMA_VERSION + 1,))
                raw.commit()
            finally:
                raw.close()
            with self.assertRaisesRegex(Exception, "newer"):
                connect(root)

    def test_existing_project_ids_cannot_be_replaced_or_removed_by_collection_mutation(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            ensure_project_sqlite_authority(root, required_source_mode=None)
            with self.assertRaisesRegex(ProjectRepositoryConflict, "membership_immutable"):
                mutate_authoritative_projects(root, lambda _projects: ([], {"ok": True}))

    def test_renaming_a_project_preserves_its_id_and_updates_legacy_task_display_name(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            ensure_project_sqlite_authority(root, required_source_mode=None)

            def rename(projects):
                updated = [dict(item) for item in projects]
                updated[0]["name"] = "Mentat Next"
                updated[0]["updated_at"] = "2026-09-01T01:00:00+00:00"
                return updated, None

            mutate_authoritative_projects(root, rename)
            self.assertEqual(read_authoritative_projects(root)[0]["id"], "project_mentat")
            task_after = read_authoritative_tasks(root)[0]
            self.assertEqual(task_after["project_id"], "project_mentat")
            self.assertEqual(task_after["project"], "Mentat Next")

    def test_task_membership_cannot_be_omitted_changed_or_orphaned_after_cutover(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            (root / "projects.json").write_text(
                json.dumps([project(), project("Other", "project_other")]),
                encoding="utf-8",
            )
            ensure_project_sqlite_authority(root, required_source_mode=None)

            for invalid_id, expected in (
                (None, TaskRepositoryValidationError),
                ("project_missing", TaskRepositoryValidationError),
                ("project_other", TaskRepositoryConflict),
            ):
                with self.assertRaises(expected):
                    mutate_authoritative_tasks(
                        root,
                        lambda tasks, invalid_id=invalid_id: (
                            [
                                {
                                    **(
                                        {key: value for key, value in tasks[0].items() if key != "project_id"}
                                        if invalid_id is None
                                        else tasks[0]
                                    ),
                                    **(
                                        {"project_id": invalid_id}
                                        if invalid_id is not None
                                        else {}
                                    ),
                                }
                            ],
                            None,
                        ),
                    )

            self.assertEqual(read_authoritative_tasks(root)[0]["project_id"], "project_mentat")


if __name__ == "__main__":
    unittest.main()
