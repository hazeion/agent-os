import json
import unittest
from unittest.mock import patch

from project_leads import read_project_lead, select_project_lead
from project_planning_inputs_http import dispatch_project_planning_inputs
from tests import test_owner_bridge_admission as admission_tests
from tests import test_task_inputs


class ProjectPlanningInputCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_task_inputs.TaskInputStorageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        lead = read_project_lead(self.root, "project_mentat")
        choice = lead["choices"][0]
        select_project_lead(self.root, "project_mentat", choice["id"],
            expected_project_revision=lead["project_revision"],
            expected_lead_revision=0, selection_token=choice["selection_token"])

    def test_owner_read_save_and_reconcile_use_only_safe_projections(self):
        before, status = dispatch_project_planning_inputs(
            self.root, "project", {"project_id": "project_mentat"}
        )
        self.assertEqual((status, before["data"]["input_revision"]), (200, 0))
        view = before["data"]
        body = {"project_id": "project_mentat",
                "expected_project_revision": view["project"]["revision"],
                "lead_role_id": view["lead"]["id"],
                "expected_lead_revision": view["lead"]["revision"],
                "context_id": view["context"]["id"],
                "expected_grant_revision": view["grant_revision"],
                "expected_input_revision": 0,
                "scope_token": view["scope_token"],
                "selection_token": view["selection_token"],
                "action_id": "project_input_action_" + "a" * 32,
                "instructions": "Keep bicycle access clear.",
                "attachment_ids": [self.fixture.attachment]}
        saved, status = dispatch_project_planning_inputs(self.root, "publish", body)
        self.assertEqual((status, saved["data"]["status"]), (200, "saved"))
        replay, status = dispatch_project_planning_inputs(self.root, "publish", body)
        self.assertEqual((status, replay["data"]["status"]), (200, "committed_needs_review"))
        reconciled, status = dispatch_project_planning_inputs(self.root, "reconcile",
            {"project_id": "project_mentat", "action_id": body["action_id"],
             "scope_token": body["scope_token"]})
        self.assertEqual((status, reconciled["data"]["input_id"]),
                         (200, saved["data"]["input_id"]))
        self.assertNotIn("blob_id", json.dumps(before) + json.dumps(saved) + json.dumps(reconciled))

    def test_widened_or_forged_requests_fail_before_write(self):
        for operation, body in (("shell", {}),
                                ("project", {"project_id": "project_mentat", "runtime_ref": "private"}),
                                ("version", {"project_id": "project_mentat", "input_id": "../private"}),
                                ("publish", {"project_id": "project_mentat"})):
            with self.subTest(operation=operation):
                _, status = dispatch_project_planning_inputs(self.root, operation, body)
                self.assertEqual(status, 400)


class ProjectPlanningInputBridgeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = admission_tests.OwnerBridgeAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_named_read_and_write_require_owner_and_csrf(self):
        bridge, owner = self.fixture.bridge, self.fixture.owner
        with patch("project_planning_inputs_http.dispatch_project_planning_inputs",
                   return_value=({"schema_version": 1, "status": "ready"}, 200)) as dispatch:
            path = "/bridge/v1/project-planning-inputs/project?project_id=project_mentat"
            status, _, _ = bridge.request(path=path)
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            headers = {"X-Mentat-Owner-Session": owner.cookie}
            status, _, _ = bridge.request(path=path, headers=headers)
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
            dispatch.reset_mock()
            status, _, _ = bridge.request(method="POST",
                path="/bridge/v1/project-planning-inputs/publish",
                headers={**headers, "Content-Type": "application/json"}, body=b"{}")
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            status, _, _ = bridge.request(method="POST",
                path="/bridge/v1/project-planning-inputs/publish",
                headers={**headers, "Content-Type": "application/json",
                         "X-Mentat-Owner-Csrf": owner.csrf}, body=b"{}")
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
