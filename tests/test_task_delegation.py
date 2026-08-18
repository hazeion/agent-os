from __future__ import annotations

import json
from copy import deepcopy
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import server
from hermes_kanban import RemoteHermesKanbanAdapter
from task_repository import ensure_task_sqlite_authority, normalize_legacy_task_collection


class FakeKanban:
    def __init__(self):
        self.calls = []
        self.remote_status = "running"
        self.connection_binding_id = "local"

    def detect_capabilities(self):
        return {"status": "available", "capabilities": {"tasks.create": True, "boards.read": True}}

    def list_boards(self):
        return {"ok": True, "boards": [{"id": "default", "name": "Default"}]}

    def create_task(self, board, **payload):
        self.calls.append(("create", board, payload))
        return {"ok": True, "task": {"id": "t-hermes-1", "title": payload["title"], "status": "ready"}}

    def get_task(self, board, task_id):
        self.calls.append(("show", board, task_id))
        create_payload = next((call[2] for call in reversed(self.calls) if call[0] == "create"), {})
        return {
            "ok": True,
            "task": {
                "id": task_id,
                "title": create_payload.get("title", "Research"),
                "body": create_payload.get("body", ""),
                "assignee": create_payload.get("assignee", "researcher"),
                "workspace_kind": create_payload.get("workspace", "scratch"),
                "status": self.remote_status,
                "session_id": "session-1",
            },
            "runs": [{"id": 7, "status": "running", "profile": "researcher", "summary": "Started"}],
            "comments": [],
            "latest_summary": "Started",
        }

    def reply_task(self, board, task_id, note):
        self.calls.append(("reply", board, task_id, note))
        return {"ok": True}

    def retry_task(self, board, task_id):
        self.calls.append(("retry", board, task_id))
        return {"ok": True}

    def terminate_task(self, board, task_id):
        self.calls.append(("stop", board, task_id))
        return {"ok": True}

    def block_task(self, board, task_id, note):
        self.calls.append(("block", board, task_id, note))
        return {"ok": True}

    def comment_task(self, board, task_id, note):
        self.calls.append(("comment", board, task_id, note))
        return {"ok": True}


class TaskDelegationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "tasks.json").write_text(json.dumps([{
            "id": "task-1",
            "title": "Research",
            "description": "Compare options",
            "project": "Mentat",
            "status": "todo",
            "priority": "high",
            "created_at": "2026-07-12T10:00:00-07:00",
            "updated_at": "2026-07-12T10:00:00-07:00",
        }]), encoding="utf-8")
        (self.root / "projects.json").write_text(json.dumps([{"id": "project-1", "name": "Mentat"}]), encoding="utf-8")
        ensure_task_sqlite_authority(self.root, required_source_mode=None)
        self.adapter = FakeKanban()
        self.patches = [
            patch.object(server, "DATA_DIR", self.root), patch.object(server, "CONFIGURED_DATA_DIR", self.root),
            patch.object(server, "kanban_adapter", return_value=self.adapter),
            patch.object(server, "hermes_profiles_payload", return_value={"status": "available", "profiles": [{"id": "researcher"}]}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def intent(self):
        return {"profile_id": "researcher", "board_id": "default", "workspace": "scratch", "instructions": "Cite sources"}

    def read_tasks(self):
        return server.read_json_file("tasks.json", [])

    def replace_tasks(self, tasks):
        normalized = list(normalize_legacy_task_collection(tasks))
        return server.update_json_file(
            "tasks.json",
            [],
            lambda _current: (normalized, None),
        )

    def test_preview_binds_exact_task_and_target(self):
        preview, status = server.preview_task_delegation("task-1", self.intent())
        self.assertEqual(status, 200)
        self.assertTrue(preview["requires_confirmation"])
        self.assertTrue(preview["confirmation_id"].startswith("task_delegate_"))
        self.assertIn("Cite sources", preview["context"])
        self.assertEqual(preview["target"]["profile_id"], "researcher")

    def test_confirmed_delegation_creates_verifies_and_persists_link(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        payload, status = server.delegate_confirmed_task("task-1", {
            **self.intent(), "confirmed": True, "confirmation_id": preview["confirmation_id"]
        })
        self.assertEqual(status, 201)
        self.assertEqual(payload["task"]["delegation"]["kanban_task_id"], "t-hermes-1")
        self.assertEqual(payload["task"]["delegation"]["run_id"], "7")
        self.assertEqual(payload["task"]["planning_state"], "waiting")
        self.assertEqual(self.adapter.calls[0][0], "create")
        self.assertTrue(self.adapter.calls[0][2]["idempotency_key"].startswith("mentat-task-1-"))
        self.assertEqual(self.adapter.calls[1], ("show", "default", "t-hermes-1"))
        duplicate, duplicate_status = server.preview_task_delegation("task-1", self.intent())
        self.assertEqual(duplicate_status, 409)
        self.assertIn("already has linked", duplicate["error"])

    def test_changed_task_invalidates_confirmation(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        tasks = self.read_tasks()
        tasks[0]["title"] = "Changed"
        self.replace_tasks(tasks)
        payload, status = server.delegate_confirmed_task("task-1", {
            **self.intent(), "confirmed": True, "confirmation_id": preview["confirmation_id"]
        })
        self.assertEqual(status, 409)
        self.assertIn("changed after preview", payload["error"])
        self.assertEqual(self.adapter.calls, [])

    def test_connection_switch_invalidates_delegation_confirmation(self):
        first = FakeKanban()
        first.connection_binding_id = "a" * 32
        second = FakeKanban()
        second.connection_binding_id = "b" * 32
        with patch.object(server, "kanban_adapter", return_value=first):
            preview, preview_status = server.preview_task_delegation(
                "task-1",
                self.intent(),
            )
        self.assertEqual(preview_status, 200)
        with patch.object(server, "kanban_adapter", return_value=second):
            payload, status = server.delegate_confirmed_task(
                "task-1",
                {
                    **self.intent(),
                    "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                },
            )
        self.assertEqual(status, 409)
        self.assertIn("changed after preview", payload["error"])
        self.assertEqual(second.calls, [])

    def test_accept_review_completes_mentat_task_without_extra_hermes_mutation(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        server.delegate_confirmed_task("task-1", {**self.intent(), "confirmed": True, "confirmation_id": preview["confirmation_id"]})
        tasks = self.read_tasks()
        tasks[0]["delegation"]["state"] = "ready_for_review"
        self.replace_tasks(tasks)
        self.adapter.remote_status = "review"
        timestamp_counter = [0]

        def advancing_timestamp():
            timestamp_counter[0] += 1
            return f"2026-07-24T17:40:{timestamp_counter[0]:02d}-07:00"

        with patch.object(server, "now_iso", side_effect=advancing_timestamp):
            action_preview, _ = server.preview_delegation_action(
                "task-1",
                {"action": "accept"},
            )
            payload, status = server.execute_confirmed_delegation_action(
                "task-1",
                {
                    "action": "accept",
                    "confirmed": True,
                    "confirmation_id": action_preview["confirmation_id"],
                },
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["status"], "completed")
        self.assertEqual(payload["delegation"]["review_state"], "accepted")

    def test_review_actions_reject_incompatible_remote_state(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        server.delegate_confirmed_task("task-1", {**self.intent(), "confirmed": True, "confirmation_id": preview["confirmation_id"]})

        payload, status = server.preview_delegation_action("task-1", {"action": "accept"})

        self.assertEqual(status, 409)
        self.assertIn("unavailable while delegated work is running", payload["error"])

    def test_remote_review_refresh_imports_artifacts_outside_kanban_lock(self):
        class RemoteClient:
            def kanban_request(self, operation, **kwargs):
                self.assertion = (operation, kwargs)
                return {
                    "object": "hermes.kanban.task_detail",
                    "version": 1,
                    "board": "default",
                    "revision": "kanbanrev_" + "b" * 64,
                    "task": {
                        "id": "t-hermes-1",
                        "object": "hermes.kanban.task",
                        "title": "Research",
                        "body": "Compare options",
                        "assignee": "researcher",
                        "status": "done",
                        "priority": 0,
                        "created_by": "api_server",
                        "created_at": 1,
                        "started_at": 2,
                        "completed_at": 3,
                        "result": "Report ready",
                        "block_kind": None,
                        "block_recurrences": 0,
                    },
                    "comments": [],
                    "runs": [],
                    "events": [],
                    "truncated": {
                        "comments": False,
                        "runs": False,
                        "events": False,
                    },
                    "parents": [],
                    "children": [],
                }

        tasks = self.read_tasks()
        tasks[0]["delegation"] = {
            "profile_id": "researcher",
            "board_id": "default",
            "connection_binding_id": "b" * 32,
            "kanban_task_id": "t-hermes-1",
            "state": "running",
            "sync_state": "pending",
            "review_state": "pending",
        }
        self.replace_tasks(tasks)
        adapter = RemoteHermesKanbanAdapter(
            RemoteClient(),
            connection_binding_id="b" * 32,
        )

        def import_files(*args, **kwargs):
            owned = getattr(server.HERMES_KANBAN_LOCK, "_is_owned", lambda: False)()
            self.assertFalse(owned)
            return {
                "state": "synced",
                "accepted_count": 2,
                "rejected_count": 0,
            }

        with (
            patch.object(server, "kanban_adapter", return_value=adapter),
            patch.object(
                server,
                "import_remote_task_artifacts",
                side_effect=import_files,
            ) as importer,
        ):
            payload, status = server.refresh_task_delegation("task-1")

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIsNotNone(payload["task"])
        self.assertEqual(payload["delegation"]["artifact_sync_state"], "synced")
        self.assertEqual(payload["delegation"]["artifact_count"], 2)
        stored = self.read_tasks()[0]
        self.assertEqual(stored["delegation"]["artifact_sync_state"], "synced")
        self.assertEqual(stored["delegation"]["artifact_count"], 2)
        importer.assert_called_once()

    def test_archived_remote_task_can_import_files_on_first_refresh(self):
        tasks = self.read_tasks()
        tasks[0]["delegation"] = {
            "profile_id": "researcher",
            "board_id": "default",
            "connection_binding_id": "b" * 32,
            "kanban_task_id": "t-hermes-1",
            "state": "running",
            "sync_state": "pending",
            "review_state": "pending",
        }
        self.replace_tasks(tasks)
        adapter = RemoteHermesKanbanAdapter(
            object(),
            connection_binding_id="b" * 32,
        )
        remote = {
            "ok": True,
            "revision": "rev-archived",
            "task": {
                "id": "t-hermes-1",
                "title": "Research",
                "assignee": "researcher",
                "status": "archived",
            },
            "runs": [],
            "comments": [],
        }
        synchronized = {
            **tasks[0]["delegation"],
            "state": "completed",
        }
        with (
            patch.object(server, "kanban_adapter", return_value=adapter),
            patch.object(adapter, "get_task", return_value=remote),
            patch.object(
                server,
                "synchronized_delegation",
                return_value=synchronized,
            ),
            patch.object(
                server,
                "import_remote_task_artifacts",
                return_value={
                    "state": "synced",
                    "accepted_count": 1,
                    "rejected_count": 0,
                },
            ) as importer,
        ):
            payload, status = server.refresh_task_delegation("task-1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["delegation"]["artifact_sync_state"], "synced")
        importer.assert_called_once()

    def test_explicit_refresh_resyncs_files_when_remote_completion_changes(self):
        first_remote = {
            "ok": True,
            "revision": "rev-1",
            "task": {
                "id": "t-hermes-1",
                "title": "Research",
                "assignee": "researcher",
                "status": "done",
                "completed_at": "2026-07-29T10:00:00+00:00",
            },
            "runs": [{"id": 7, "status": "done", "outcome": "completed"}],
            "comments": [],
        }
        second_remote = deepcopy(first_remote)
        second_remote["revision"] = "rev-2"
        second_remote["task"]["completed_at"] = "2026-07-29T11:00:00+00:00"
        second_remote["runs"] = [
            {"id": 8, "status": "done", "outcome": "completed"}
        ]
        tasks = self.read_tasks()
        tasks[0]["delegation"] = {
            "profile_id": "researcher",
            "board_id": "default",
            "connection_binding_id": "b" * 32,
            "kanban_task_id": "t-hermes-1",
            "run_id": "7",
            "state": "ready_for_review",
            "sync_state": "synced",
            "review_state": "pending",
            "artifact_sync_state": "synced",
            "artifact_sync_revision": server.artifact_sync_revision(first_remote),
            "artifact_count": 0,
            "artifact_rejected_count": 0,
        }
        self.replace_tasks(tasks)
        adapter = RemoteHermesKanbanAdapter(
            object(),
            connection_binding_id="b" * 32,
        )
        with (
            patch.object(server, "kanban_adapter", return_value=adapter),
            patch.object(adapter, "get_task", return_value=second_remote),
            patch.object(
                server,
                "import_remote_task_artifacts",
                return_value={
                    "state": "synced",
                    "accepted_count": 0,
                    "rejected_count": 0,
                },
            ) as importer,
        ):
            payload, status = server.refresh_task_delegation("task-1")

        self.assertEqual(status, 200)
        importer.assert_called_once()
        self.assertEqual(
            payload["delegation"]["artifact_sync_revision"],
            server.artifact_sync_revision(second_remote),
        )

    def test_preview_fails_closed_when_profile_inventory_is_unavailable(self):
        with patch.object(server, "hermes_profiles_payload", return_value={"status": "unavailable", "profiles": []}):
            payload, status = server.preview_task_delegation("task-1", self.intent())

        self.assertEqual(status, 409)
        self.assertIn("profiles are unavailable", payload["error"])

    def test_preview_blocks_incomplete_dependencies(self):
        tasks = self.read_tasks()
        tasks[0]["depends_on"] = ["task-dependency"]
        tasks.append({"id": "task-dependency", "title": "Dependency", "status": "todo"})
        self.replace_tasks(tasks)

        payload, status = server.preview_task_delegation("task-1", self.intent())

        self.assertEqual(status, 409)
        self.assertEqual(payload["dependency_task_ids"], ["task-dependency"])

    def test_action_rejects_live_hermes_state_change(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        server.delegate_confirmed_task("task-1", {**self.intent(), "confirmed": True, "confirmation_id": preview["confirmation_id"]})
        self.adapter.remote_status = "review"
        action_preview, status = server.preview_delegation_action("task-1", {"action": "accept"})
        self.assertEqual(status, 200)
        self.adapter.remote_status = "running"

        payload, action_status = server.execute_confirmed_delegation_action("task-1", {
            "action": "accept", "confirmed": True, "confirmation_id": action_preview["confirmation_id"]
        })

        self.assertEqual(action_status, 409)
        self.assertIn("unavailable while delegated work is running", payload["error"])

    def test_action_rechecks_stable_delegation_binding_inside_lock(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        server.delegate_confirmed_task(
            "task-1",
            {
                **self.intent(),
                "confirmed": True,
                "confirmation_id": preview["confirmation_id"],
            },
        )
        tasks = self.read_tasks()
        tasks[0]["delegation"].update(
            {
                "artifact_sync_state": "synced",
                "artifact_count": 1,
                "artifact_rejected_count": 0,
                "artifact_sync_revision": "artifactrev_old",
                "artifact_sync_attempts": 0,
            }
        )
        self.replace_tasks(tasks)
        self.adapter.remote_status = "review"
        action_preview, status = server.preview_delegation_action(
            "task-1",
            {"action": "accept"},
        )
        self.assertEqual(status, 200)
        current = self.read_tasks()[0]

        for changed_field, changed_value in (
            ("board_id", "changed-board"),
            ("profile_id", "changed-profile"),
        ):
            changed = deepcopy(current)
            changed["delegation"][changed_field] = changed_value
            with self.subTest(changed_field=changed_field), patch.object(
                server,
                "task_record",
                side_effect=[deepcopy(current), changed],
            ):
                payload, action_status = server.execute_confirmed_delegation_action(
                    "task-1",
                    {
                        "action": "accept",
                        "confirmed": True,
                        "confirmation_id": action_preview["confirmation_id"],
                    },
                )

            self.assertEqual(action_status, 409)
            self.assertIn("changed after preview", payload["error"])

    def test_request_revision_reconciles_prior_artifact_binding(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        server.delegate_confirmed_task(
            "task-1",
            {
                **self.intent(),
                "confirmed": True,
                "confirmation_id": preview["confirmation_id"],
            },
        )
        self.adapter.remote_status = "review"
        with patch.object(
            self.adapter,
            "detect_capabilities",
            return_value={
                "status": "available",
                "capabilities": {
                    "tasks.create": True,
                    "tasks.comment": True,
                },
            },
        ):
            action_preview, status = server.preview_delegation_action(
                "task-1",
                {"action": "request_revision", "note": "Please add sources."},
            )
        self.assertEqual(status, 200)

        def create_revision(board, **payload):
            self.adapter.calls.append(("create", board, payload))
            return {
                "ok": True,
                "task": {
                    "id": "t-hermes-2",
                    "title": payload["title"],
                    "status": "ready",
                },
            }

        with (
            patch.object(self.adapter, "create_task", side_effect=create_revision),
            patch.object(
                self.adapter,
                "detect_capabilities",
                return_value={
                    "status": "available",
                    "capabilities": {
                        "tasks.create": True,
                        "tasks.comment": True,
                    },
                },
            ),
            patch.object(
                server,
                "reconcile_task_artifact_bindings",
                return_value=(),
            ) as reconcile,
        ):
            result, action_status = server.execute_confirmed_delegation_action(
                "task-1",
                {
                    "action": "request_revision",
                    "note": "Please add sources.",
                    "confirmed": True,
                    "confirmation_id": action_preview["confirmation_id"],
                },
            )

        self.assertEqual(action_status, 200)
        self.assertEqual(result["delegation"]["kanban_task_id"], "t-hermes-2")
        for key in (
            "artifact_sync_state",
            "artifact_count",
            "artifact_rejected_count",
            "artifact_sync_revision",
            "artifact_sync_attempts",
        ):
            self.assertNotIn(key, result["delegation"])
        reconcile.assert_called_once()

    def test_activity_groups_linked_tasks_by_decision_state(self):
        tasks = self.read_tasks()
        tasks[0]["delegation"] = {"profile_id": "researcher", "state": "needs_input", "review_state": "pending"}
        self.replace_tasks(tasks)
        payload = server.agent_activity_payload()
        self.assertEqual(payload["counts"]["needs_input"], 1)
        self.assertEqual(payload["groups"]["needs_input"][0]["task_id"], "task-1")

    def test_home_refresh_is_current_connection_only_and_bounded(self):
        tasks = []
        for index in range(4):
            tasks.append(
                {
                    "id": f"task-{index}",
                    "title": f"Task {index}",
                    "delegation": {
                        "connection_binding_id": "b" * 32,
                        "board_id": "default",
                        "kanban_task_id": f"t_remote_{index}",
                        "state": "running",
                    },
                }
            )
        tasks.append(
            {
                "id": "legacy",
                "title": "Legacy",
                "delegation": {
                    "board_id": "default",
                    "kanban_task_id": "t_legacy",
                    "state": "running",
                },
            }
        )
        self.replace_tasks(tasks)
        with (
            patch.object(
                server,
                "load_remote_hermes_connection",
                return_value=SimpleNamespace(mode="remote", binding_id="b" * 32),
            ),
            patch.object(
                server,
                "refresh_task_delegation",
                return_value=({"ok": True}, 200),
            ) as refresh_task,
        ):
            payload, status = server.refresh_home_delegations()

        self.assertEqual(status, 200)
        self.assertEqual(payload["refreshed"], 3)
        self.assertEqual(payload["skipped"], 2)
        self.assertEqual(refresh_task.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in refresh_task.call_args_list],
            ["task-0", "task-1", "task-2"],
        )

    def test_home_refresh_includes_only_current_local_binding(self):
        tasks = [
            {
                "id": "local-task",
                "title": "Local work",
                "delegation": {
                    "connection_binding_id": "local-default",
                    "board_id": "default",
                    "kanban_task_id": "t_local",
                    "state": "running",
                },
            },
            {
                "id": "remote-task",
                "title": "Remote work",
                "delegation": {
                    "connection_binding_id": "b" * 32,
                    "board_id": "default",
                    "kanban_task_id": "t_remote",
                    "state": "running",
                },
            },
        ]
        self.replace_tasks(tasks)
        with (
            patch.object(
                server,
                "load_remote_hermes_connection",
                return_value=SimpleNamespace(
                    mode="local",
                    binding_id="local-default",
                ),
            ),
            patch.object(
                server,
                "refresh_task_delegation",
                return_value=({"ok": True}, 200),
            ) as refresh_task,
        ):
            payload, status = server.refresh_home_delegations()

        self.assertEqual(status, 200)
        self.assertEqual(payload["refreshed"], 1)
        self.assertEqual(payload["skipped"], 1)
        refresh_task.assert_called_once_with("local-task")

    def test_home_refresh_respects_terminal_and_retry_artifact_states(self):
        tasks = [
            {
                "id": "unsupported",
                "title": "Old Hermes",
                "delegation": {
                    "connection_binding_id": "b" * 32,
                    "board_id": "default",
                    "kanban_task_id": "t_unsupported",
                    "state": "ready_for_review",
                    "artifact_sync_state": "unsupported",
                },
            },
            {
                "id": "cooldown",
                "title": "Retry later",
                "delegation": {
                    "connection_binding_id": "b" * 32,
                    "board_id": "default",
                    "kanban_task_id": "t_cooldown",
                    "state": "ready_for_review",
                    "artifact_sync_state": "error",
                    "artifact_sync_retry_at": "2999-01-01T00:00:00+00:00",
                },
            },
            {
                "id": "due",
                "title": "Retry now",
                "delegation": {
                    "connection_binding_id": "b" * 32,
                    "board_id": "default",
                    "kanban_task_id": "t_due",
                    "state": "ready_for_review",
                    "artifact_sync_state": "partial",
                    "artifact_sync_retry_at": "2000-01-01T00:00:00+00:00",
                },
            },
        ]
        self.replace_tasks(tasks)
        with (
            patch.object(
                server,
                "load_remote_hermes_connection",
                return_value=SimpleNamespace(
                    mode="remote",
                    binding_id="b" * 32,
                ),
            ),
            patch.object(
                server,
                "refresh_task_delegation",
                return_value=({"ok": True}, 200),
            ) as refresh_task,
        ):
            payload, status = server.refresh_home_delegations()

        self.assertEqual(status, 200)
        self.assertEqual(payload["refreshed"], 1)
        refresh_task.assert_called_once_with("due")

    def test_legacy_remote_delegation_requires_verified_rebind(self):
        tasks = self.read_tasks()
        tasks[0]["delegation"] = {
            "profile_id": "researcher",
            "board_id": "default",
            "kanban_task_id": "t-hermes-1",
            "state": "running",
        }
        self.replace_tasks(tasks)
        adapter = RemoteHermesKanbanAdapter(
            object(),
            connection_binding_id="b" * 32,
        )
        remote = {
            "ok": True,
            "revision": "rev-1",
            "task": {
                "id": "t-hermes-1",
                "title": "Research",
                "assignee": "researcher",
                "status": "running",
            },
            "runs": [],
            "comments": [],
        }
        with (
            patch.object(server, "kanban_adapter", return_value=adapter),
            patch.object(adapter, "get_task", return_value=remote),
        ):
            preview, status = server.preview_delegation_rebind("task-1")
            self.assertEqual(status, 200)
            result, confirm_status = server.confirm_delegation_rebind(
                "task-1",
                {
                    "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                },
            )

        self.assertEqual(confirm_status, 200)
        self.assertTrue(result["ok"])
        stored = self.read_tasks()[0]
        self.assertEqual(
            stored["delegation"]["connection_binding_id"],
            "b" * 32,
        )

    def test_legacy_rebind_rejects_connection_swap_after_preview(self):
        tasks = self.read_tasks()
        tasks[0]["delegation"] = {
            "profile_id": "researcher",
            "board_id": "default",
            "kanban_task_id": "t-hermes-1",
            "state": "running",
        }
        self.replace_tasks(tasks)
        first = RemoteHermesKanbanAdapter(
            object(),
            connection_binding_id="a" * 32,
        )
        second = RemoteHermesKanbanAdapter(
            object(),
            connection_binding_id="b" * 32,
        )
        remote = {
            "ok": True,
            "revision": "rev-1",
            "task": {
                "id": "t-hermes-1",
                "title": "Research",
                "assignee": "researcher",
                "status": "running",
            },
            "runs": [],
            "comments": [],
        }
        with (
            patch.object(server, "kanban_adapter", return_value=first),
            patch.object(first, "get_task", return_value=remote),
        ):
            preview, status = server.preview_delegation_rebind("task-1")
        self.assertEqual(status, 200)

        with (
            patch.object(server, "kanban_adapter", return_value=second),
            patch.object(second, "get_task", return_value=remote),
        ):
            result, confirm_status = server.confirm_delegation_rebind(
                "task-1",
                {
                    "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                },
            )

        self.assertEqual(confirm_status, 409)
        self.assertIn("changed after preview", result["error"])
        stored = self.read_tasks()[0]
        self.assertNotIn("connection_binding_id", stored["delegation"])

    def test_legacy_rebind_expected_state_rejects_task_race(self):
        tasks = self.read_tasks()
        tasks[0]["delegation"] = {
            "profile_id": "researcher",
            "board_id": "default",
            "kanban_task_id": "t-hermes-1",
            "state": "running",
        }
        self.replace_tasks(tasks)
        adapter = RemoteHermesKanbanAdapter(
            object(),
            connection_binding_id="b" * 32,
        )
        remote = {
            "ok": True,
            "revision": "rev-1",
            "task": {
                "id": "t-hermes-1",
                "title": "Research",
                "assignee": "researcher",
                "status": "running",
            },
            "runs": [],
            "comments": [],
        }
        with (
            patch.object(server, "kanban_adapter", return_value=adapter),
            patch.object(adapter, "get_task", return_value=remote),
        ):
            preview, status = server.preview_delegation_rebind("task-1")
        self.assertEqual(status, 200)

        adapter_calls = 0

        def adapter_with_task_race():
            nonlocal adapter_calls
            adapter_calls += 1
            if adapter_calls == 2:
                changed = self.read_tasks()
                changed[0]["description"] = "Changed during confirmation"
                self.replace_tasks(changed)
            return adapter

        with (
            patch.object(
                server,
                "kanban_adapter",
                side_effect=adapter_with_task_race,
            ),
            patch.object(adapter, "get_task", return_value=remote),
        ):
            result, confirm_status = server.confirm_delegation_rebind(
                "task-1",
                {
                    "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                },
            )

        self.assertEqual(confirm_status, 409)
        self.assertIn("changed after preview", result["error"])


if __name__ == "__main__":
    unittest.main()
