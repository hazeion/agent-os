import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import server
from hermes_event_refresh import (
    EVENT_PROJECTIONS,
    HermesRefreshCoordinator,
    projection_kinds_for_event,
)
from hermes_webhooks import VerifiedHermesEvent


def event(name="on_session_end", delivery="delivery-1", binding="local-default"):
    now = datetime.now(timezone.utc)
    return VerifiedHermesEvent(
        binding_id=binding,
        event_name=name,
        delivery_digest=delivery,
        occurred_at=now,
        received_at=now,
        completed=None,
        interrupted=None,
        platform="cli",
    )


class HermesEventRefreshTests(unittest.TestCase):
    def test_event_matrix_is_exact_and_read_only(self):
        self.assertEqual(
            EVENT_PROJECTIONS,
            {
                "on_session_start": frozenset({"sessions", "agents"}),
                "on_session_end": frozenset({"sessions", "agents", "attention"}),
                "subagent_start": frozenset({"agents"}),
                "subagent_stop": frozenset({"agents", "attention", "kanban"}),
            },
        )
        for name, expected in EVENT_PROJECTIONS.items():
            self.assertEqual(projection_kinds_for_event(name), expected)
        self.assertEqual(projection_kinds_for_event("post_tool_call"), frozenset())

    def test_one_thousand_hints_stay_bounded_and_coalesce(self):
        calls = []
        coordinator = HermesRefreshCoordinator(
            {"agents": lambda binding: calls.append(binding) or {"ok": True}},
            capacity=256,
            coalesce_window=0.01,
            reconciliation_interval=60,
        )
        accepted = sum(
            coordinator.enqueue(event("subagent_start", f"delivery-{index}"))
            for index in range(1000)
        )
        self.assertEqual(accepted, 256)
        self.assertEqual(coordinator.pending_count, 256)
        coordinator.start()
        self.assertTrue(coordinator.wait_idle(2))
        self.assertLessEqual(len(calls), 2)
        health = coordinator.health_snapshot("local-default")
        self.assertEqual(health["queue_drop_count"], 744)
        self.assertGreaterEqual(health["coalesced_hint_count"], 254)
        self.assertTrue(coordinator.stop(timeout=1))

    def test_adapter_failure_is_isolated_and_backed_off(self):
        attempts = []

        def fail(_binding):
            attempts.append("called")
            raise RuntimeError("private adapter detail")

        coordinator = HermesRefreshCoordinator(
            {"sessions": fail},
            coalesce_window=0,
            reconciliation_interval=60,
            base_backoff=10,
        )
        coordinator.start()
        self.assertTrue(coordinator.enqueue(event("on_session_start", "first")))
        self.assertTrue(coordinator.wait_idle(1))
        self.assertTrue(coordinator.enqueue(event("on_session_start", "second")))
        self.assertTrue(coordinator.wait_idle(1))
        self.assertEqual(attempts, ["called"])
        health = coordinator.health_snapshot("local-default")
        self.assertEqual(health["refresh_failure_count"], 1)
        self.assertEqual(health["backoff_skip_count"], 1)
        self.assertEqual(health["last_error_code"], "webhook_refresh_failed")
        self.assertIsNone(coordinator.projection_snapshot("local-default", "sessions"))
        self.assertTrue(coordinator.stop(timeout=1))

    def test_successful_peer_projection_does_not_clear_degraded_health(self):
        coordinator = HermesRefreshCoordinator(
            {
                "agents": lambda _binding: (_ for _ in ()).throw(RuntimeError("failed")),
                "attention": lambda _binding: {"attention": []},
                "kanban": lambda _binding: {"tasks": []},
            },
            coalesce_window=0,
            reconciliation_interval=60,
        )
        coordinator.start()
        self.assertTrue(coordinator.enqueue(event("subagent_stop")))
        self.assertTrue(coordinator.wait_idle(1))
        health = coordinator.health_snapshot("local-default")
        self.assertEqual(health["degraded_projection_count"], 1)
        self.assertEqual(health["last_error_code"], "webhook_refresh_failed")
        self.assertTrue(coordinator.stop(timeout=1))

    def test_reconciliation_repairs_a_dropped_hint(self):
        reconciled = threading.Event()
        coordinator = HermesRefreshCoordinator(
            {"sessions": lambda _binding: reconciled.set() or {"sessions": []}},
            binding_ids=("local-default",),
            capacity=1,
            coalesce_window=0,
            reconciliation_interval=0.03,
        )
        self.assertTrue(coordinator.enqueue(event("on_session_start", "queued")))
        self.assertFalse(coordinator.enqueue(event("on_session_start", "dropped")))
        coordinator.start()
        self.assertTrue(reconciled.wait(1))
        deadline = time.monotonic() + 1
        while coordinator.health_snapshot("local-default")["reconciliation_count"] < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertGreaterEqual(
            coordinator.health_snapshot("local-default")["reconciliation_count"],
            1,
        )
        self.assertEqual(
            coordinator.projection_snapshot("local-default", "sessions"),
            {"sessions": []},
        )
        self.assertTrue(coordinator.stop(timeout=1))

    def test_out_of_order_events_never_become_authoritative_state(self):
        snapshots = []
        coordinator = HermesRefreshCoordinator(
            {"sessions": lambda _binding: snapshots.append("read") or {"status": "authoritative"}},
            coalesce_window=0.01,
            reconciliation_interval=60,
        )
        self.assertTrue(coordinator.enqueue(event("on_session_end", "end")))
        self.assertTrue(coordinator.enqueue(event("on_session_start", "start")))
        coordinator.start()
        self.assertTrue(coordinator.wait_idle(1))
        self.assertEqual(snapshots, ["read"])
        self.assertEqual(
            coordinator.projection_snapshot("local-default", "sessions"),
            {"status": "authoritative"},
        )
        self.assertNotIn(
            "completed",
            coordinator.health_snapshot("local-default"),
        )
        self.assertTrue(coordinator.stop(timeout=1))

    def test_shutdown_is_bounded_and_restart_reconciles_without_old_hints(self):
        entered = threading.Event()
        release = threading.Event()

        def blocking(_binding):
            entered.set()
            release.wait(2)
            return {"ok": True}

        first = HermesRefreshCoordinator(
            {"sessions": blocking},
            coalesce_window=0,
            reconciliation_interval=60,
        )
        first.start()
        self.assertTrue(first.enqueue(event("on_session_start")))
        self.assertTrue(entered.wait(1))
        started = time.monotonic()
        self.assertFalse(first.stop(timeout=0.05))
        self.assertLess(time.monotonic() - started, 0.25)
        release.set()
        self.assertTrue(first.stop(timeout=1))

        restarted = threading.Event()
        second = HermesRefreshCoordinator(
            {"sessions": lambda _binding: restarted.set() or {"ok": True}},
            binding_ids=("local-default",),
            reconciliation_interval=0.02,
            coalesce_window=0,
        )
        second.start()
        self.assertTrue(restarted.wait(1))
        self.assertTrue(second.stop(timeout=1))


class HermesEventRefreshServerAdapterTests(unittest.TestCase):
    @staticmethod
    def remote_task(status="running", task_id="remote-1"):
        return {
            "ok": True,
            "task": {"id": task_id, "status": status},
            "runs": [],
            "comments": [],
        }

    def test_local_kanban_refresh_is_bounded_to_three_verified_readbacks(self):
        tasks = [
            {
                "id": f"task-{index}",
                "updated_at": f"2026-08-14T00:00:0{index}+00:00",
                "delegation": {
                    "kanban_task_id": f"remote-{index}",
                    "connection_binding_id": "local-default",
                    "state": "running",
                },
            }
            for index in range(5)
        ]
        adapter = MagicMock()
        adapter.get_task.side_effect = (
            lambda _board, task_id: self.remote_task(task_id=task_id)
        )
        with (
            patch("server.HermesKanbanAdapter", return_value=adapter),
            patch("server.read_json_file", return_value=tasks),
            patch("server.persist_task_delegation") as persist,
        ):
            result = server._refresh_webhook_kanban("local-default")
        self.assertEqual(result["refreshed"], 3)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(len(result["tasks"]), 3)
        self.assertEqual(adapter.get_task.call_count, 3)
        persist.assert_not_called()

    def test_local_kanban_refresh_uses_configured_hermes_home(self):
        adapter = MagicMock()
        configured_home = Path("/configured/hermes-home")
        with (
            patch("server.HERMES_HOME", configured_home),
            patch("server.HermesKanbanAdapter", return_value=adapter) as adapter_type,
            patch("server.read_json_file", return_value=[]),
            patch.dict("server.os.environ", {"HERMES_HOME": "/ambient/hermes-home"}),
        ):
            server._refresh_webhook_kanban("local-default")
        constructor_env = adapter_type.call_args.kwargs["env"]
        self.assertEqual(constructor_env["HERMES_HOME"], str(configured_home))

    def test_local_kanban_refresh_fails_closed_on_unverified_readback(self):
        tasks = [
            {
                "id": "task-1",
                "delegation": {
                    "kanban_task_id": "remote-1",
                    "connection_binding_id": "local-default",
                    "state": "running",
                },
            }
        ]
        adapter = MagicMock()
        adapter.get_task.return_value = {"ok": False, "error": {"code": "timeout"}}
        with (
            patch("server.HermesKanbanAdapter", return_value=adapter),
            patch("server.read_json_file", return_value=tasks),
            patch("server.persist_task_delegation") as persist,
        ):
            with self.assertRaisesRegex(RuntimeError, "webhook_refresh_failed"):
                server._refresh_webhook_kanban("local-default")
        persist.assert_not_called()

    def test_local_webhook_never_refreshes_remote_bound_or_terminal_kanban(self):
        tasks = [
            {
                "id": "remote-bound",
                "delegation": {
                    "kanban_task_id": "remote-1",
                    "connection_binding_id": "remote-connection",
                    "state": "running",
                },
            },
            {
                "id": "terminal-local",
                "delegation": {
                    "kanban_task_id": "remote-2",
                    "connection_binding_id": "local-default",
                    "state": "completed",
                },
            },
        ]
        adapter = MagicMock()
        with (
            patch("server.HermesKanbanAdapter", return_value=adapter),
            patch("server.read_json_file", return_value=tasks),
        ):
            result = server._refresh_webhook_kanban("local-default")
        self.assertEqual(result, {"tasks": [], "refreshed": 0, "skipped": 0})
        adapter.get_task.assert_not_called()

    def test_local_session_and_agent_adapters_ignore_selected_remote_transport(self):
        local_sessions = {"exists": True, "source": "local", "sessions": []}
        with (
            patch("server.recent_sessions", return_value=local_sessions) as recent,
            patch("server.sessions_payload") as selected_sessions,
            patch("server.read_json_file", return_value=[]),
        ):
            self.assertEqual(server._refresh_webhook_sessions("local-default"), local_sessions)
            agents = server._refresh_webhook_agents("local-default")
        self.assertEqual(recent.call_count, 2)
        selected_sessions.assert_not_called()
        self.assertEqual(agents["sessions"], [])

    def test_error_shaped_local_projection_fails_without_replacing_snapshot(self):
        with patch(
            "server.recent_sessions",
            return_value={"exists": None, "sessions": [], "error": "private path"},
        ):
            with self.assertRaisesRegex(RuntimeError, "webhook_refresh_failed"):
                server._refresh_webhook_sessions("local-default")
            with self.assertRaisesRegex(RuntimeError, "webhook_refresh_failed"):
                server._refresh_webhook_agents("local-default")

    def test_malformed_local_session_and_agent_projections_fail_closed(self):
        for malformed in ({}, {"exists": True, "sessions": "bad"}):
            with self.subTest(malformed=malformed), patch(
                "server.recent_sessions", return_value=malformed
            ):
                with self.assertRaisesRegex(RuntimeError, "webhook_refresh_failed"):
                    server._refresh_webhook_sessions("local-default")

        valid_sessions = {"exists": True, "sessions": []}
        with (
            patch("server.recent_sessions", return_value=valid_sessions),
            patch("server.agents_payload", return_value={"agents": []}),
        ):
            with self.assertRaisesRegex(RuntimeError, "webhook_refresh_failed"):
                server._refresh_webhook_agents("local-default")

    def test_attention_refresh_rejects_malformed_source_files(self):
        malformed_pairs = [
            ({"error": "broken"}, []),
            ([], {"error": "broken"}),
            (["not-an-object"], []),
            ([], ["not-an-object"]),
        ]
        for attention, tasks in malformed_pairs:
            with self.subTest(attention=attention, tasks=tasks), patch(
                "server.read_json_file", side_effect=[attention, tasks]
            ):
                with self.assertRaisesRegex(RuntimeError, "webhook_refresh_failed"):
                    server._refresh_webhook_attention("local-default")

    def test_kanban_refresh_rejects_mismatched_or_unknown_task_state(self):
        tasks = [
            {
                "id": "task-1",
                "delegation": {
                    "kanban_task_id": "remote-1",
                    "connection_binding_id": "local-default",
                    "state": "running",
                },
            }
        ]
        malformed = [
            self.remote_task(task_id="different-task"),
            self.remote_task(status=None),
            self.remote_task(status="future-state"),
        ]
        for remote in malformed:
            adapter = MagicMock()
            adapter.get_task.return_value = remote
            with (
                self.subTest(remote=remote),
                patch("server.HermesKanbanAdapter", return_value=adapter),
                patch("server.read_json_file", return_value=tasks),
            ):
                with self.assertRaisesRegex(RuntimeError, "webhook_refresh_failed"):
                    server._refresh_webhook_kanban("local-default")


if __name__ == "__main__":
    unittest.main()
