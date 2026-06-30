from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = json.loads((ROOT / "data" / "projects.json").read_text(encoding="utf-8"))
TASKS = json.loads((ROOT / "data" / "tasks.json").read_text(encoding="utf-8"))


class DataFixtureTests(unittest.TestCase):
    def test_no_dummy_projects_or_tasks_remain(self):
        project_blob = json.dumps(PROJECTS).lower()
        task_blob = json.dumps(TASKS).lower()
        self.assertNotIn("project_dummy", project_blob)
        self.assertNotIn("dummy_test", task_blob)

    def test_only_mentat_project_remains_active_for_v1(self):
        self.assertEqual([project["name"] for project in PROJECTS], ["Mentat"])
        self.assertEqual({task["project"] for task in TASKS}, {"Mentat"})

    def test_tracked_seed_data_uses_current_public_identity(self):
        payload = json.dumps({"projects": PROJECTS, "tasks": TASKS})
        blocked_terms = [
            "Agent " "OS",
            "agent" "-os",
            "agent" "_os",
            "AGENT" "_OS",
            "Agent" "OS",
            "E:/code/",
            "E:\\code\\",
        ]
        for term in blocked_terms:
            self.assertNotIn(term, payload)


if __name__ == "__main__":
    unittest.main()
