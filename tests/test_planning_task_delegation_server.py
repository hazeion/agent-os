from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server
from task_delegation_receipts import (
    DelegationReceiptUnavailable,
    idempotency_key_digest,
)
from task_repository import ensure_task_sqlite_authority


class _FakeKanban:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.connection_binding_id = "local-default"
        self.status = "running"

    def detect_capabilities(self):
        return {
            "status": "available",
            "capabilities": {"tasks.create": True, "boards.read": True},
        }

    def list_boards(self):
        return {"ok": True, "boards": [{"id": "default", "name": "Default"}]}

    def create_task(self, board, **payload):
        self.calls.append(("create", board, payload))
        return {"ok": True, "task": {"id": "private-kanban-id", "title": payload["title"]}}

    def get_task(self, board, task_id):
        self.calls.append(("get", board, task_id))
        created = next((item[2] for item in self.calls if item[0] == "create"), {})
        return {
            "ok": True,
            "revision": "private-remote-revision",
            "task": {
                "id": task_id,
                "title": created.get("title", "Research"),
                "body": created.get("body", ""),
                "assignee": created.get("assignee", "researcher"),
                "workspace_kind": created.get("workspace", "scratch"),
                "status": self.status,
                "session_id": "private-session",
            },
            "runs": [{"id": "private-run", "status": self.status, "summary": "Started"}],
            "comments": [],
            "latest_summary": "Started",
        }


class PlanningTaskDelegationServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "tasks.json").write_text(json.dumps([{
            "id": "task-1", "title": "Research", "project": "Mentat",
            "status": "todo", "priority": "high",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }]), encoding="utf-8")
        ensure_task_sqlite_authority(self.root, required_source_mode=None)
        self.adapter = _FakeKanban()
        self.patches = [
            patch.object(server, "DATA_DIR", self.root),
            patch.object(server, "CONFIGURED_DATA_DIR", self.root),
            patch.object(server, "kanban_adapter", return_value=self.adapter),
            patch.object(server, "hermes_profiles_payload", return_value={
                "status": "available", "profiles": [{"id": "researcher", "name": "Researcher"}],
            }),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    @staticmethod
    def _key() -> str:
        return "delegation-idempotency-key-0001"

    def _intent(self, revision: int) -> dict:
        return {
            "expected_revision": revision,
            "profile_id": "researcher",
            "board_id": "default",
            "workspace": "scratch",
            "instructions": "Cite primary sources.",
            "context_pack_id": "",
        }

    def test_options_are_bounded_and_do_not_expose_runtime_binding(self) -> None:
        result, status = server.mentat_planning_task_delegation_options_payload("task-1")

        self.assertEqual(status, 200)
        self.assertTrue(result["options"]["available"])
        self.assertEqual(result["options"]["profiles"], [{"id": "researcher", "name": "Researcher"}])
        self.assertNotIn("connection_binding_id", json.dumps(result))

    def test_delegate_requires_exact_revision_and_replays_one_receipt(self) -> None:
        current, status = server.mentat_planning_task_delegation_preview("task-1", self._intent(1))
        self.assertEqual(status, 200)
        confirm = {
            **self._intent(1),
            "confirmation_id": current["confirmation_id"],
            "idempotency_key": self._key(),
        }

        first, first_status = server.mentat_planning_task_delegate("task-1", confirm)
        second, second_status = server.mentat_planning_task_delegate("task-1", confirm)

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 200)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len([item for item in self.adapter.calls if item[0] == "create"]), 1)
        exposed = json.dumps(first)
        for secret in ("private-kanban-id", "private-session", "private-run", "connection_binding_id"):
            self.assertNotIn(secret, exposed)

    def test_delegate_rejects_stale_task_revision_before_adapter_call(self) -> None:
        result, status = server.mentat_planning_task_delegation_preview("task-1", self._intent(2))

        self.assertEqual(status, 409)
        self.assertEqual(result["error_code"], "planning_delegation.conflict")
        self.assertEqual(self.adapter.calls, [])

    def test_reused_key_with_changed_request_conflicts_without_adapter_call(self) -> None:
        preview, status = server.mentat_planning_task_delegation_preview("task-1", self._intent(1))
        self.assertEqual(status, 200)
        confirmed = {
            **self._intent(1), "confirmation_id": preview["confirmation_id"], "idempotency_key": self._key(),
        }
        result, status = server.mentat_planning_task_delegate("task-1", confirmed)
        self.assertEqual(status, 201)
        changed = {**confirmed, "instructions": "Different instruction"}

        conflict, conflict_status = server.mentat_planning_task_delegate("task-1", changed)

        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict["error_code"], "planning_delegation.conflict")
        self.assertEqual(len([item for item in self.adapter.calls if item[0] == "create"]), 1)

    def test_uncertain_receipt_blocks_retry_without_adapter_call(self) -> None:
        preview, status = server.mentat_planning_task_delegation_preview("task-1", self._intent(1))
        self.assertEqual(status, 200)
        confirmed = {
            **self._intent(1), "confirmation_id": preview["confirmation_id"], "idempotency_key": self._key(),
        }
        intent = {key: confirmed[key] for key in (
            "profile_id", "board_id", "workspace", "instructions", "context_pack_id"
        )}
        receipt = server._planning_delegation_receipt_reserve(
            task_id="task-1", task_revision=1, action="delegate",
            idempotency_key=confirmed["idempotency_key"],
            confirmation_id=confirmed["confirmation_id"],
            request={"action": "delegate", "revision": 1, "intent": intent},
            binding={"target": preview["target"], "connection": self.adapter.connection_binding_id},
            remote_revision={"kind": "delegate"},
        )
        server._planning_delegation_receipt_submitting(receipt.key_digest)
        server._planning_delegation_receipt_mark(receipt.key_digest, "unknown")

        result, result_status = server.mentat_planning_task_delegate("task-1", confirmed)

        self.assertEqual(result_status, 409)
        self.assertEqual(result["error_code"], "planning_delegation.unknown")
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(idempotency_key_digest(confirmed["idempotency_key"]), receipt.key_digest)

    def test_accept_action_replays_without_a_second_remote_effect(self) -> None:
        preview, status = server.mentat_planning_task_delegation_preview("task-1", self._intent(1))
        self.assertEqual(status, 200)
        created, status = server.mentat_planning_task_delegate("task-1", {
            **self._intent(1), "confirmation_id": preview["confirmation_id"], "idempotency_key": self._key(),
        })
        self.assertEqual(status, 201)
        self.adapter.status = "review"
        revision = created["task"]["revision"]
        action_preview, status = server.mentat_planning_task_delegation_action_preview(
            "task-1", {"expected_revision": revision, "action": "accept"}
        )
        self.assertEqual(status, 200)
        action = {
            "expected_revision": revision,
            "action": "accept",
            "confirmation_id": action_preview["confirmation_id"],
            "idempotency_key": "delegation-idempotency-key-0002",
        }

        first, first_status = server.mentat_planning_task_delegation_action("task-1", action)
        second, second_status = server.mentat_planning_task_delegation_action("task-1", action)

        self.assertEqual((first_status, second_status), (200, 200))
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["delegation"]["review_state"], "accepted")

    def test_indeterminate_delivery_can_reconcile_persisted_effect_without_retry(self) -> None:
        preview, status = server.mentat_planning_task_delegation_preview(
            "task-1", self._intent(1)
        )
        self.assertEqual(status, 200)
        confirmed = {
            **self._intent(1),
            "confirmation_id": preview["confirmation_id"],
            "idempotency_key": self._key(),
        }
        with patch.object(
            server,
            "_planning_delegation_receipt_mark",
            side_effect=DelegationReceiptUnavailable("test.persistence_failure"),
        ):
            indeterminate, indeterminate_status = (
                server.mentat_planning_task_delegate("task-1", confirmed)
            )

        self.assertEqual(indeterminate_status, 409)
        self.assertEqual(
            indeterminate["error_code"], "planning_delegation.unknown"
        )
        self.assertEqual(
            len([item for item in self.adapter.calls if item[0] == "create"]), 1
        )

        recovered, recovered_status = server.mentat_planning_task_delegation_recover(
            "task-1",
            {
                "confirmation_id": confirmed["confirmation_id"],
                "idempotency_key": confirmed["idempotency_key"],
            },
        )

        self.assertEqual(recovered_status, 200)
        self.assertTrue(recovered["recovered"])
        self.assertTrue(recovered["delegation"]["available"])
        self.assertEqual(
            len([item for item in self.adapter.calls if item[0] == "create"]), 1
        )

    def test_invalid_action_is_not_reported_as_an_outage(self) -> None:
        result, status = server.mentat_planning_task_delegation_action_preview(
            "task-1", {"expected_revision": 1, "action": "not-real"}
        )

        self.assertEqual(status, 409)
        self.assertEqual(result["error_code"], "planning_delegation.conflict")


if __name__ == "__main__":
    unittest.main()
