import json
import subprocess
import unittest
from types import SimpleNamespace

from hermes_kanban import CAPABILITY_KEYS, HermesKanbanAdapter


HELP = """usage: hermes kanban {boards,list,show,assignees,runs,create,assign,comment,promote,block,unblock,reclaim}"""


def completed(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


class FakeRunner:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response
        if argv[-1] == "--version":
            return completed("Hermes Agent v0.18.2 (2026.7.7.2)\nInstall directory: /private/install")
        if argv[-2:] == ["kanban", "--help"]:
            return completed(HELP)
        raise AssertionError(f"unexpected command: {argv}")


def available_adapter(*operation_responses):
    runner = FakeRunner([
        completed("Hermes Agent v0.18.2\nInstall directory: /private/install"),
        completed(HELP),
        *operation_responses,
    ])
    return HermesKanbanAdapter("/usr/local/bin/hermes", runner=runner, timeout=7), runner


class CapabilityTests(unittest.TestCase):
    def test_detects_supported_cli_without_returning_install_path(self):
        adapter, runner = available_adapter()
        payload = adapter.detect_capabilities()
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["hermes_version"], "0.18.2")
        self.assertTrue(all(payload["capabilities"][key] for key in CAPABILITY_KEYS))
        self.assertNotIn("private", json.dumps(payload))
        self.assertEqual(runner.calls[0][0], ["/usr/local/bin/hermes", "--version"])
        self.assertFalse(runner.calls[0][1]["check"])
        self.assertEqual(runner.calls[0][1]["timeout"], 7)

    def test_fails_closed_when_runtime_is_missing(self):
        payload = HermesKanbanAdapter(None).detect_capabilities()
        self.assertEqual(payload["status"], "unavailable")
        self.assertFalse(any(payload["capabilities"].values()))

    def test_fails_closed_when_help_does_not_advertise_command(self):
        runner = FakeRunner([completed("Hermes Agent v0.17.0"), completed("usage: hermes kanban list show")])
        adapter = HermesKanbanAdapter("hermes", runner=runner)
        payload = adapter.detect_capabilities()
        self.assertFalse(payload["capabilities"]["tasks.create"])
        response = adapter.create_task("default", title="Nope")
        self.assertEqual(response["error"]["code"], "capability_unavailable")


class ReadTests(unittest.TestCase):
    def test_lists_boards_and_omits_paths(self):
        raw = [{
            "slug": "work", "name": "Work", "description": "at /Users/alice/repo",
            "db_path": "/Users/alice/.hermes/kanban.db", "default_workdir": "/Users/alice/repo",
            "counts": {"ready": 2}, "is_current": True,
        }]
        adapter, runner = available_adapter(completed(json.dumps(raw)))
        payload = adapter.list_boards()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["boards"][0]["counts"], {"ready": 2})
        self.assertNotIn("db_path", json.dumps(payload))
        self.assertNotIn("/Users/", json.dumps(payload))
        self.assertEqual(runner.calls[-1][0], ["/usr/local/bin/hermes", "kanban", "boards", "list", "--json"])

    def test_list_tasks_uses_fixed_arguments_and_redacts_sensitive_text(self):
        raw = [{
            "id": "t-1", "title": "Inspect /Users/alice/repo", "body": "token=abc123secret",
            "status": "ready", "assignee": "coder", "workspace_path": "/Users/alice/repo",
            "priority": 4, "skills": ["github"],
        }]
        adapter, runner = available_adapter(completed(json.dumps(raw)))
        payload = adapter.list_tasks("daily", status="ready", assignee="coder")
        self.assertTrue(payload["ok"])
        encoded = json.dumps(payload)
        self.assertNotIn("/Users/alice", encoded)
        self.assertNotIn("abc123secret", encoded)
        self.assertNotIn("workspace_path", encoded)
        self.assertEqual(runner.calls[-1][0], [
            "/usr/local/bin/hermes", "kanban", "--board", "daily", "list", "--json",
            "--status", "ready", "--assignee", "coder",
        ])

    def test_show_normalizes_comments_and_runs_but_omits_events_and_metadata(self):
        raw = {
            "task": {"id": "t1", "title": "Task", "status": "running", "workspace_kind": "scratch"},
            "latest_summary": "Worked in /home/alice/project",
            "parents": ["t0"], "children": [],
            "comments": [{"author": "user", "body": "key sk-secretvalue", "created_at": 2}],
            "events": [{"payload": {"path": "/home/alice/project"}}],
            "runs": [{"id": 5, "profile": "coder", "status": "running", "started_at": 10,
                      "worker_pid": 4321, "metadata": {"path": "/home/alice"}}],
        }
        adapter, _ = available_adapter(completed(json.dumps(raw)))
        payload = adapter.get_task("default", "t1")
        self.assertTrue(payload["ok"])
        encoded = json.dumps(payload)
        self.assertNotIn("events", payload)
        self.assertNotIn("worker_pid", encoded)
        self.assertNotIn("metadata", encoded)
        self.assertNotIn("/home/alice", encoded)
        self.assertNotIn("sk-secretvalue", encoded)

    def test_runs_calculate_elapsed_and_omit_worker_details(self):
        raw = [{"id": 2, "profile": "coder", "status": "done", "outcome": "success",
                "started_at": 10, "ended_at": 18, "worker_pid": 99, "metadata": {"secret": "x"}}]
        adapter, _ = available_adapter(completed(json.dumps(raw)))
        payload = adapter.list_runs("default", "t1")
        self.assertEqual(payload["runs"][0]["elapsed_seconds"], 8)
        self.assertNotIn("worker_pid", json.dumps(payload))


class MutationTests(unittest.TestCase):
    def mutation_adapter(self, operation_response=None, *, status="ready", comments=None, assignee=None):
        task = {"task": {"id": "t1", "title": "Task", "status": status, "assignee": assignee, "workspace_kind": "scratch"},
                "comments": comments or [], "runs": []}
        return available_adapter(operation_response or completed("ok"), completed(json.dumps(task)))

    def test_create_is_json_and_shell_free(self):
        created = {"id": "t7", "title": "Write report", "status": "ready", "assignee": "writer", "workspace_kind": "scratch"}
        adapter, runner = available_adapter(completed(json.dumps(created)))
        payload = adapter.create_task("daily", title="Write report", body="Use notes", assignee="writer", idempotency_key="mentat-7")
        self.assertTrue(payload["ok"])
        self.assertEqual(runner.calls[-1][0], [
            "/usr/local/bin/hermes", "kanban", "--board", "daily", "create", "--json",
            "--created-by", "mentat", "--body", "Use notes", "--assignee", "writer",
            "--workspace", "scratch", "--priority", "0", "--idempotency-key", "mentat-7", "Write report",
        ])

    def test_comment_and_reply_are_task_level_comments(self):
        adapter, runner = self.mutation_adapter(comments=[{"author": "mentat", "body": "Approved"}])
        self.assertTrue(adapter.reply_task("default", "t1", "Approved")["ok"])
        self.assertEqual(runner.calls[2][0], [
            "/usr/local/bin/hermes", "kanban", "--board", "default", "comment", "t1",
            "Approved", "--author", "mentat", "--max-len", "20000",
        ])

    def test_promote_block_retry_and_terminate_map_to_supported_commands(self):
        cases = [
            (lambda a: a.promote_task("default", "t1", reason="Ready"), ["promote", "t1", "Ready"], "ready"),
            (lambda a: a.block_task("default", "t1", "Need input"), ["block", "t1", "Need input", "--kind", "needs_input"], "blocked"),
            (lambda a: a.retry_task("default", "t1"), ["unblock", "t1", "--reason", "Retried from Mentat"], "ready"),
            (lambda a: a.terminate_task("default", "t1"), ["reclaim", "t1", "--reason", "Stopped from Mentat"], "ready"),
        ]
        for invoke, tail, status in cases:
            with self.subTest(command=tail[0]):
                adapter, runner = self.mutation_adapter(status=status)
                self.assertTrue(invoke(adapter)["ok"])
                self.assertEqual(runner.calls[2][0][-len(tail):], tail)

    def test_mutation_fails_when_requested_state_is_not_observed(self):
        adapter, _ = self.mutation_adapter(status="running")
        payload = adapter.block_task("default", "t1", "Need input")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "verification_failed")
        self.assertTrue(payload["partial"])

    def test_update_fails_closed_for_fields_without_cli_support(self):
        adapter, runner = available_adapter()
        response = adapter.update_task("default", "t1", title="Changed")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "capability_unavailable")
        self.assertEqual(len(runner.calls), 0)

    def test_rejects_option_injection_before_invoking_hermes(self):
        adapter, runner = available_adapter()
        response = adapter.create_task("default", title="--help")
        self.assertEqual(response["error"]["code"], "invalid_request")
        self.assertEqual(len(runner.calls), 2)

    def test_timeout_is_redacted_and_partial(self):
        adapter, _ = available_adapter(subprocess.TimeoutExpired(["hermes"], 7))
        payload = adapter.list_tasks("default")
        self.assertEqual(payload["error"]["code"], "runtime_timeout")
        self.assertTrue(payload["partial"])


if __name__ == "__main__":
    unittest.main()
