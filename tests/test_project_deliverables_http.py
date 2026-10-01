import base64
import json
import unittest
from unittest.mock import patch

import project_deliverables_http as api
from project_deliverables import publish_owner_edit
from tests import test_project_context as context_tests
from tests import test_owner_bridge_admission as admission_tests
from tests.test_project_deliverable_content import garage_layout


class DeliverableCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = context_tests.ProjectContextTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def publish(self):
        return api.dispatch_project_deliverables(self.root, "publish", {
            "project_id": "project_mentat", "slot": "layout", "content": garage_layout(),
            "expected_project_revision": 1, "expected_slot_revision": 0,
            "source_version_id": None, "associated_task_id": None, "expected_task_revision": None,
        })

    def test_exact_owner_write_read_and_retired_preview(self):
        published, status = self.publish()
        self.assertEqual(status, 200)
        version_id = published["data"]["version_id"]
        listing, status = api.dispatch_project_deliverables(self.root, "project", {"project_id": "project_mentat"})
        self.assertEqual(status, 200)
        self.assertEqual(listing["data"]["slots"][0]["versions"][0]["id"], version_id)
        detail, status = api.dispatch_project_deliverables(self.root, "version", {
            "project_id": "project_mentat", "version_id": version_id,
        })
        self.assertEqual(status, 200)
        self.assertEqual(detail["data"]["content"], garage_layout())
        preview, status = api.dispatch_project_deliverables(self.root, "preview", {"version_id": version_id})
        self.assertEqual(status, 200)
        self.assertTrue(base64.b64decode(preview["data"]["content_base64"]).startswith(b"\x89PNG"))
        for private in ("storage_key", "runtime_agent_ref", "deliverable_incarnation"):
            self.assertNotIn(private, json.dumps(listing))
        service = self.fixture.deletion_service()
        service.finalize(service.preview("project", "project_mentat"))
        history, status = api.dispatch_project_deliverables(self.root, "retired-history", {})
        self.assertEqual((status, history["data"]["versions"][0]["id"]), (200, version_id))
        self.assertIsNone(history["data"]["next_offset"])
        retired, status = api.dispatch_project_deliverables(self.root, "retired-version", {"version_id": version_id})
        self.assertEqual((status, retired["data"]["content"]), (200, garage_layout()))

    def test_unknown_and_widened_requests_never_reach_storage(self):
        with patch.object(api, "publish_owner_edit") as write:
            for operation, body in (("shell", {}),
                                    ("project", {"project_id": "project_mentat", "path": "private"}),
                                    ("publish", {"project_id": "project_mentat", "runtime_agent_ref": "default"}),
                                    ("version", {"project_id": "project_mentat", "version_id": "../private"})):
                _, status = api.dispatch_project_deliverables(self.root, operation, body)
                self.assertEqual(status, 400)
            write.assert_not_called()

    def test_history_accepts_only_bounded_page_offsets(self):
        for value in ({"offset": "1"}, {"offset": "-50"}, {"offset": 300}, {"offset": []}, {"offset": "50", "path": "private"}):
            _, status = api.dispatch_project_deliverables(self.root, "retired-history", value)
            self.assertEqual(status, 400)
        result, status = api.dispatch_project_deliverables(self.root, "retired-history", {"offset": "50"})
        self.assertEqual(status, 200)
        self.assertEqual(result["data"], {"versions": [], "next_offset": None})

    def test_retired_history_pages_all_fifty_one_versions(self):
        for slot, count, content in (("products", 32, {"items": [], "notes": "Owner sources"}),
                                     ("steps", 19, {"steps": [], "notes": "Owner order"})):
            source = None
            for revision in range(count):
                saved = publish_owner_edit(self.root, "project_mentat", slot, content,
                                           expected_project_revision=1, expected_slot_revision=revision,
                                           source_version_id=source)
                source = saved["version_id"]
        service = self.fixture.deletion_service()
        service.finalize(service.preview("project", "project_mentat"))
        first, status = api.dispatch_project_deliverables(self.root, "retired-history", {})
        self.assertEqual(status, 200)
        self.assertEqual((len(first["data"]["versions"]), first["data"]["next_offset"]), (50, 50))
        second, status = api.dispatch_project_deliverables(self.root, "retired-history", {"offset": "50"})
        self.assertEqual(status, 200)
        self.assertEqual((len(second["data"]["versions"]), second["data"]["next_offset"]), (1, None))
        self.assertEqual(len({item["id"] for item in [*first["data"]["versions"], *second["data"]["versions"]]}), 51)


class DeliverableBridgeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = admission_tests.OwnerBridgeAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_owner_session_and_csrf_gate_fixed_bridge_paths(self):
        bridge, owner = self.fixture.bridge, self.fixture.owner
        with patch.object(api, "dispatch_project_deliverables", return_value=({"schema_version": 1, "status": "ready"}, 200)) as dispatch:
            status, _, _ = bridge.request(path="/bridge/v1/project-deliverables/retired-history")
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            headers = {"X-Mentat-Owner-Session": owner.cookie}
            status, _, _ = bridge.request(path="/bridge/v1/project-deliverables/retired-history", headers=headers)
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
            dispatch.reset_mock()
            status, _, _ = bridge.request(method="POST", path="/bridge/v1/project-deliverables/publish",
                                          headers={**headers, "Content-Type": "application/json"}, body=b"{}")
            self.assertEqual(status, 401)
            dispatch.assert_not_called()
            status, _, _ = bridge.request(method="POST", path="/bridge/v1/project-deliverables/publish",
                                          headers={**headers, "Content-Type": "application/json", "X-Mentat-Owner-Csrf": owner.csrf}, body=b"{}")
            self.assertEqual(status, 200)
            dispatch.assert_called_once()
            dispatch.reset_mock()
            status, _, _ = bridge.request(path="/bridge/v1/project-deliverables/project?project_id=x&project_id=y", headers=headers)
            self.assertEqual(status, 404)
            dispatch.assert_not_called()
