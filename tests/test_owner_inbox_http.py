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

    def test_fixed_page_reports_bounded_counts_and_rejects_extra_selectors(self):
        self.fixture.complete()
        result, status = dispatch_owner_inbox(self.fixture.root, "page", {"view": "needs_me", "after": None})
        self.assertEqual((status, len(result["data"]["items"]), result["data"]["counts"]["needs_me"]), (200, 1, 1))
        for body in ({"view": "all"}, {"view": "all", "after": None, "project_id": "project_mentat"},
                     {"view": "anything", "after": None}, {"view": "unread", "after": "../private"}):
            self.assertEqual(dispatch_owner_inbox(self.fixture.root, "page", body)[1], 400)

    def test_run_notice_open_and_owner_actions_expose_only_safe_outcome(self):
        self.fixture.insert_run_outcome("run_http_failure")
        page, status = dispatch_owner_inbox(self.fixture.root, "page", {"view": "needs_me", "after": None})
        self.assertEqual(status, 200)
        item = page["data"]["items"][0]
        self.assertEqual(item["kind"], "run_outcome")
        opened, status = dispatch_owner_inbox(self.fixture.root, "open", {"item_id": item["id"]})
        self.assertEqual((status, opened["data"]["run"]["status"]), (200, "failed"))
        self.assertNotIn("incarnation", json.dumps(opened))
        self.assertNotIn("runtime_run_ref", json.dumps(opened))
        acknowledged, status = dispatch_owner_inbox(self.fixture.root, "mark", {
            "item_id": item["id"], "action": "acknowledge", "expected_revision": item["revision"],
        })
        self.assertEqual(status, 200)
        dismissed, status = dispatch_owner_inbox(self.fixture.root, "mark", {
            "item_id": item["id"], "action": "dismiss", "expected_revision": acknowledged["data"]["revision"],
        })
        self.assertEqual((status, dismissed["data"]["revision"]), (200, acknowledged["data"]["revision"] + 1))

    def test_item_bound_open_preview_and_confirm_never_select_a_project_id(self):
        self.fixture.complete()
        item = dispatch_owner_inbox(self.fixture.root, "page", {"view": "needs_me", "after": None})[0]["data"]["items"][0]
        opened, status = dispatch_owner_inbox(self.fixture.root, "open", {"item_id": item["id"]})
        self.assertEqual((status, opened["data"]["review"]["status"]), (200, "pending"))
        self.assertNotIn("incarnation", json.dumps(opened))
        action = {"item_id": item["id"], "action": "accept", "note": "",
                  "affected_slots": ["layout", "products", "steps"]}
        preview, status = dispatch_owner_inbox(self.fixture.root, "preview", action)
        self.assertEqual(status, 200)
        confirmed, status = dispatch_owner_inbox(self.fixture.root, "confirm", {
            **action, "confirmation_id": preview["data"]["confirmation_id"],
        })
        self.assertEqual((status, confirmed["data"]["duplicate"]), (200, False))
        self.assertEqual(dispatch_owner_inbox(self.fixture.root, "open", {"item_id": item["id"]})[0]["data"]["item"]["state"], "resolved")

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
            status, _, _ = bridge.request(path="/bridge/v1/owner-inbox/page?view=needs_me", headers=headers)
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
            self.assertEqual(dispatch.call_args.args[1:], ('page', {'view': 'needs_me', 'after': None}))
            dispatch.reset_mock()
            status, _, _ = bridge.request(path="/bridge/v1/owner-inbox/open?item_id=inbox_item_" + "a" * 32, headers=headers)
            self.assertEqual(status, 200)
            self.assertEqual(dispatch.call_args.args[1:], ('open', {'item_id': 'inbox_item_' + 'a' * 32}))
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
            status, _, _ = bridge.request(method="POST", path="/bridge/v1/owner-inbox/preview",
                                          headers={**headers, "Content-Type": "application/json"}, body=b"{}")
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            status, _, _ = bridge.request(method="POST", path="/bridge/v1/owner-inbox/preview",
                                          headers={**headers, "Content-Type": "application/json", "X-Mentat-Owner-Csrf": owner.csrf}, body=b"{}")
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
            dispatch.reset_mock()
            status, _, _ = bridge.request(path="/bridge/v1/owner-inbox/list?source_id=x", headers=headers)
            self.assertEqual(status, 404)
            dispatch.assert_not_called()
