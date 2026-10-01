import json
import unittest
from unittest.mock import patch

from owner_inbox_http import dispatch_owner_inbox
from task_repository import TaskRepositoryUnavailable
from tests import test_owner_bridge_admission as admission_tests
from tests import test_owner_inbox as inbox_tests


class OwnerInboxCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = inbox_tests.OwnerInboxTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_exact_list_and_mark_expose_no_source_incarnation(self):
        self.fixture.complete()
        listed, status = dispatch_owner_inbox(self.fixture.root, "list", {})
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["data"]), 1)
        self.assertNotIn("incarnation", json.dumps(listed))
        item = listed["data"][0]
        marked, status = dispatch_owner_inbox(self.fixture.root, "mark", {
            "item_id": item["id"], "action": "acknowledge", "expected_revision": item["revision"],
        })
        self.assertEqual((status, marked["data"]["revision"]), (200, item["revision"] + 1))
        duplicate, status = dispatch_owner_inbox(self.fixture.root, "mark", {
            "item_id": item["id"], "action": "acknowledge", "expected_revision": item["revision"],
        })
        self.assertEqual((status, duplicate["data"]["duplicate"]), (200, True))

    def test_widened_or_stale_requests_fail_closed(self):
        self.fixture.complete()
        item = dispatch_owner_inbox(self.fixture.root, "list", {})[0]["data"][0]
        for operation, body in (
            ("unknown", {}), ("list", {"source_id": "project_mentat"}),
            ("mark", {"item_id": item["id"], "action": "approve", "expected_revision": 1}),
            ("mark", {"item_id": item["id"], "action": "read", "expected_revision": True}),
            ("mark", {"item_id": item["id"], "action": "read", "expected_revision": 1, "run_id": "private"}),
        ):
            with self.subTest(operation=operation, body=body):
                self.assertEqual(dispatch_owner_inbox(self.fixture.root, operation, body)[1], 400)
        dispatch_owner_inbox(self.fixture.root, "mark", {
            "item_id": item["id"], "action": "read", "expected_revision": 1,
        })
        stale, status = dispatch_owner_inbox(self.fixture.root, "mark", {
            "item_id": item["id"], "action": "acknowledge", "expected_revision": 1,
        })
        self.assertEqual((status, stale["status"]), (409, "stale"))

    def test_unavailable_repository_returns_bounded_failure(self):
        with patch("owner_inbox_http.read_inbox", side_effect=TaskRepositoryUnavailable("task_repository.unavailable")):
            result, status = dispatch_owner_inbox(self.fixture.root, "list", {})
        self.assertEqual((status, result), (503, {"schema_version": 1, "status": "unavailable"}))


class OwnerInboxBridgeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = admission_tests.OwnerBridgeAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_owner_session_and_csrf_gate_named_paths(self):
        bridge, owner = self.fixture.bridge, self.fixture.owner
        with patch("owner_inbox_http.dispatch_owner_inbox", return_value=({"schema_version": 1, "status": "ready"}, 200)) as dispatch:
            status, _, _ = bridge.request(path="/bridge/v1/owner-inbox/list")
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            headers = {"X-Mentat-Owner-Session": owner.cookie}
            status, _, _ = bridge.request(path="/bridge/v1/owner-inbox/list", headers=headers)
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
            dispatch.reset_mock()
            status, _, _ = bridge.request(method="POST", path="/bridge/v1/owner-inbox/mark",
                                          headers={**headers, "Content-Type": "application/json"}, body=b"{}")
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            status, _, _ = bridge.request(method="POST", path="/bridge/v1/owner-inbox/mark",
                                          headers={**headers, "Content-Type": "application/json", "X-Mentat-Owner-Csrf": owner.csrf}, body=b"{}")
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
            dispatch.reset_mock()
            status, _, _ = bridge.request(path="/bridge/v1/owner-inbox/list?source_id=x", headers=headers)
            self.assertEqual(status, 404)
            dispatch.assert_not_called()
