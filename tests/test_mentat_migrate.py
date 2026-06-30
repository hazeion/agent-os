from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import mentat_migrate


class MentatMigrationTests(unittest.TestCase):
    def write_json(self, root: Path, name: str, payload) -> None:
        (root / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def test_migration_normalizes_previous_project_records_with_backup(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(
                root,
                "projects.json",
                [
                    {
                        "id": mentat_migrate.PREVIOUS_PROJECT_ID,
                        "name": mentat_migrate.PREVIOUS_PROJECT_NAME,
                        "legacy_names": [mentat_migrate.PREVIOUS_PROJECT_NAME],
                    }
                ],
            )
            self.write_json(root, "tasks.json", [{"id": "task_one", "project": mentat_migrate.PREVIOUS_PROJECT_NAME}])
            report = mentat_migrate.migrate_data(root, write=True)
            projects = json.loads((root / "projects.json").read_text(encoding="utf-8"))
            tasks = json.loads((root / "tasks.json").read_text(encoding="utf-8"))

        self.assertEqual(sorted(report["changed_files"]), ["projects.json", "tasks.json"])
        self.assertTrue(report["backup_dir"])
        self.assertEqual(projects[0]["id"], "project_mentat")
        self.assertEqual(projects[0]["name"], "Mentat")
        self.assertNotIn("legacy_names", projects[0])
        self.assertEqual(tasks[0]["project"], "Mentat")


if __name__ == "__main__":
    unittest.main()
