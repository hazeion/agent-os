import json
import unittest
from unittest.mock import patch

from project_leads_http import dispatch_project_leads
from tests import test_owner_bridge_admission as admission_tests
from tests import test_task_inputs


class ProjectLeadCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_task_inputs.TaskInputStorageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def test_owner_read_and_exact_selection_are_safe_and_do_not_dispatch(self):
        before, status = dispatch_project_leads(
            self.root, "project", {"project_id": "project_mentat"},
        )
        self.assertEqual((status, before["data"]["status"]), (200, "unassigned"))
        choice = before["data"]["choices"][0]
        body = {"project_id": "project_mentat", "agent_id": choice["id"],
                "expected_project_revision": before["data"]["project_revision"],
                "expected_lead_revision": before["data"]["revision"],
                "selection_token": choice["selection_token"]}
        saved, status = dispatch_project_leads(self.root, "select", body)
        self.assertEqual((status, saved["data"]["revision"], saved["data"]["status"]),
                         (200, 1, "context_bound"))
        self.assertFalse(saved["data"]["proposal_available"])
        self.assertNotIn("binding_digest", json.dumps(saved))
        stale, status = dispatch_project_leads(self.root, "select", body)
        self.assertEqual((status, stale["status"]), (409, "revision_conflict"))

    def test_widened_and_forged_selection_fail_before_write(self):
        for operation, body in (
            ("shell", {}),
            ("project", {"project_id": "project_mentat", "runtime_ref": "private"}),
            ("select", {"project_id": "project_mentat"}),
            ("select", {"project_id": "project_mentat", "agent_id": "agent_research",
                        "expected_project_revision": 1, "expected_lead_revision": 0,
                        "selection_token": "x" * 64}),
        ):
            with self.subTest(operation=operation):
                _, status = dispatch_project_leads(self.root, operation, body)
                self.assertEqual(status, 400)


class ProjectLeadBridgeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = admission_tests.OwnerBridgeAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_owner_session_and_csrf_gate_named_lead_paths(self):
        bridge, owner = self.fixture.bridge, self.fixture.owner
        with patch("project_leads_http.dispatch_project_leads", return_value=({"schema_version": 1, "status": "ready"}, 200)) as dispatch:
            path = "/bridge/v1/project-leads/project?project_id=project_mentat"
            status, _, _ = bridge.request(path=path)
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            headers = {"X-Mentat-Owner-Session": owner.cookie}
            status, _, _ = bridge.request(path=path, headers=headers)
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
            dispatch.reset_mock()
            status, _, _ = bridge.request(method="POST", path="/bridge/v1/project-leads/select",
                                          headers={**headers, "Content-Type": "application/json"}, body=b"{}")
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            status, _, _ = bridge.request(method="POST", path="/bridge/v1/project-leads/select",
                                          headers={**headers, "Content-Type": "application/json",
                                                   "X-Mentat-Owner-Csrf": owner.csrf}, body=b"{}")
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
