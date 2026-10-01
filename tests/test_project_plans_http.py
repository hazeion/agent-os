import json
import unittest
from unittest.mock import patch

from project_plans_http import dispatch_project_plans
from task_inputs import publish_task_inputs
from task_repository import mutate_authoritative_tasks
from tests import test_owner_bridge_admission as admission_tests
from tests.test_task_inputs import TaskInputStorageTests


class ProjectPlanCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = TaskInputStorageTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.saved_input = publish_task_inputs(self.root, self.fixture.payload)

    def body(self):
        return {"project_id": "project_mentat", "expected_project_revision": 1,
                "expected_plan_revision": 0, "title": "Organize the garage",
                "nodes": [{"task_id": "task_research", "expected_task_revision": 1,
                           "agent_id": "agent_research", "input_version_id": self.saved_input["input_id"],
                           "after": [], "segment": 0, "max_attempts": 1,
                           "max_wall_seconds": 900, "max_work_units": 100}]}

    def test_exact_owner_publish_and_current_and_historical_reads(self):
        empty, status = dispatch_project_plans(self.root, "project", {"project_id": "project_mentat"})
        self.assertEqual((status, empty["data"]["plan_revision"]), (200, 0))
        result, status = dispatch_project_plans(self.root, "publish", self.body())
        self.assertEqual((status, result["data"]["status"]), (200, "unapproved"))
        current, status = dispatch_project_plans(self.root, "project", {"project_id": "project_mentat"})
        self.assertEqual((status, current["data"]["plan_revision"]), (200, 1))
        self.assertFalse(current["data"]["execution_available"])
        self.assertNotIn("incarnation", json.dumps(current))
        historical, status = dispatch_project_plans(self.root, "version", {
            "project_id": "project_mentat", "version_id": result["data"]["id"],
        })
        self.assertEqual((status, historical["data"]["current"]), (200, True))
        self.assertEqual(historical["data"]["nodes"][0]["task_id"], "task_research")
        self.assertNotIn("incarnation", json.dumps(historical))

    def test_widened_malformed_and_stale_requests_fail_closed(self):
        for operation, body in (
            ("shell", {}),
            ("project", {"project_id": "project_mentat", "runtime_ref": "private"}),
            ("version", {"project_id": "project_mentat", "version_id": "../private"}),
            ("publish", {**self.body(), "runtime_method": "run"}),
            ("publish", {**self.body(), "nodes": [{**self.body()["nodes"][0], "after": ["task_research"]}]}),
        ):
            with self.subTest(operation=operation):
                _, status = dispatch_project_plans(self.root, operation, body)
                self.assertEqual(status, 400)
        dispatch_project_plans(self.root, "publish", self.body())
        stale, status = dispatch_project_plans(self.root, "publish", self.body())
        self.assertEqual((status, stale["status"]), (409, "revision_conflict"))

    def test_historical_read_marks_changed_task_identity_without_copying_new_title(self):
        saved, status = dispatch_project_plans(self.root, "publish", self.body())
        self.assertEqual(status, 200)
        mutate_authoritative_tasks(self.root, lambda rows: ([{**rows[0], "title": "Different goal"}], None))
        historical, status = dispatch_project_plans(self.root, "version", {
            "project_id": "project_mentat", "version_id": saved["data"]["id"],
        })
        self.assertEqual(status, 200)
        node = historical["data"]["nodes"][0]
        self.assertEqual((node["task_state"], node["task_title"]), ("changed", None))
        self.assertEqual((node["agent_state"], node["agent_name"]), ("current", "Research"))


class ProjectPlanBridgeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = admission_tests.OwnerBridgeAdmissionTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_owner_session_and_csrf_gate_named_plan_paths(self):
        bridge, owner = self.fixture.bridge, self.fixture.owner
        with patch("project_plans_http.dispatch_project_plans", return_value=({"schema_version": 1, "status": "ready"}, 200)) as dispatch:
            status, _, _ = bridge.request(path="/bridge/v1/project-plans/project?project_id=project_mentat")
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            headers = {"X-Mentat-Owner-Session": owner.cookie}
            status, _, _ = bridge.request(path="/bridge/v1/project-plans/project?project_id=project_mentat", headers=headers)
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
            dispatch.reset_mock()
            status, _, _ = bridge.request(method="POST", path="/bridge/v1/project-plans/publish",
                                          headers={**headers, "Content-Type": "application/json"}, body=b"{}")
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            status, _, _ = bridge.request(method="POST", path="/bridge/v1/project-plans/publish",
                                          headers={**headers, "Content-Type": "application/json", "X-Mentat-Owner-Csrf": owner.csrf}, body=b"{}")
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
            dispatch.reset_mock()
            status, _, _ = bridge.request(path="/bridge/v1/project-plans/project?project_id=x&project_id=y", headers=headers)
            self.assertEqual(status, 404)
            dispatch.assert_not_called()
