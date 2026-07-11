from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server


class DashboardBehaviorTests(unittest.TestCase):
    def write_json(self, root: Path, name: str, payload) -> None:
        (root / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def test_agent_console_only_accepts_hermes_and_requires_a_prompt(self):
        invalid_agent, invalid_agent_status = server.start_agent_console_run({"agent_id": "shell", "prompt": "hello"})
        missing_prompt, missing_prompt_status = server.start_agent_console_run({"agent_id": "hermes", "prompt": "  "})

        self.assertEqual(invalid_agent_status, 400)
        self.assertIn("Unknown or unavailable Hermes profile", invalid_agent["error"])
        self.assertEqual(missing_prompt_status, 400)
        self.assertEqual(missing_prompt["error"], "Prompt is required")

    def test_agent_console_starts_a_managed_hermes_run(self):
        server.AGENT_CONSOLE_RUNS.clear()
        try:
            with patch.object(server, "hermes_command_path", return_value="/tmp/hermes"), patch.object(
                server, "agent_console_model", return_value="test/model"
            ), patch.object(server.threading, "Thread") as worker:
                payload, status = server.start_agent_console_run({"agent_id": "hermes", "prompt": "Inspect the queue"})

            self.assertEqual(status, 202)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["run"]["agent_id"], "default")
            self.assertEqual(payload["run"]["status"], "queued")
            self.assertEqual(payload["run"]["prompt"], "Inspect the queue")
            self.assertNotIn("command", payload["run"])
            worker.return_value.start.assert_called_once_with()
        finally:
            server.AGENT_CONSOLE_RUNS.clear()

    def test_agent_console_runner_captures_response_and_resumable_session(self):
        class CompletedHermesProcess:
            returncode = 0

            def communicate(self, timeout=None):
                return "Hermes response", "\nsession_id: session_test_123\n"

        run_id = "run_test_console"
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "prompt": "Continue this work",
            "session_id": "session_previous",
            "status": "queued",
            "events": [],
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        try:
            with patch.object(server.subprocess, "Popen", return_value=CompletedHermesProcess()) as popen:
                server.run_hermes_agent(run_id, "/tmp/hermes")

            command = popen.call_args.args[0]
            self.assertEqual(command[:6], ["/tmp/hermes", "-p", "default", "chat", "-q", "Continue this work"])
            self.assertIn("--resume", command)
            self.assertEqual(command[command.index("--resume") + 1], "session_previous")
            self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["status"], "completed")
            self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["response"], "Hermes response")
            self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["session_id"], "session_test_123")
        finally:
            server.AGENT_CONSOLE_RUNS.clear()
            server.AGENT_CONSOLE_PROCESSES.clear()

    def test_agent_console_provider_change_requires_a_bound_preview(self):
        inventory = {
            "profile_id": "default",
            "current_provider": "openai-codex",
            "current_model": "gpt-5.5",
            "providers": [
                {
                    "id": "openrouter",
                    "name": "OpenRouter",
                    "authenticated": True,
                    "models": ["anthropic/claude-sonnet-4"],
                }
            ],
            "capabilities": {"providers.switch": True},
        }
        with patch.object(
            server, "agent_console_profile", return_value={"id": "default", "name": "default"}
        ), patch.object(server, "agent_console_provider_inventory", return_value=inventory):
            payload, status = server.preview_agent_console_provider_switch(
                {
                    "agent_id": "default",
                    "provider": "openrouter",
                    "model": "anthropic/claude-sonnet-4",
                }
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload["requires_confirmation"])
        self.assertTrue(payload["confirmation_id"].startswith("provider_switch_"))
        self.assertEqual(payload["current"], {"provider": "openai-codex", "model": "gpt-5.5"})
        self.assertEqual(payload["target"]["provider"], "openrouter")

    def test_agent_console_provider_preview_rejects_unlisted_models(self):
        inventory = {
            "current_provider": "openai-codex",
            "current_model": "gpt-5.5",
            "providers": [
                {
                    "id": "openrouter",
                    "name": "OpenRouter",
                    "authenticated": True,
                    "models": ["openai/gpt-5.5"],
                }
            ],
            "capabilities": {"providers.switch": True},
        }
        with patch.object(
            server, "agent_console_profile", return_value={"id": "default", "name": "default"}
        ), patch.object(server, "agent_console_provider_inventory", return_value=inventory):
            payload, status = server.preview_agent_console_provider_switch(
                {"provider": "openrouter", "model": "anthropic/claude-sonnet-4"}
            )

        self.assertEqual(status, 400)
        self.assertIn("Choose a model", payload["error"])

    def test_agent_console_model_catalog_uses_hermes_inventory_payload(self):
        server.AGENT_MODEL_CATALOG_CACHE.update({"key": None, "payload": None, "fetched_at": 0})
        inventory = {
            "provider": "openrouter",
            "provider_label": "OpenRouter",
            "models": ["openai/gpt-5.5", "anthropic/claude-sonnet-4"],
            "current_model": "openai/gpt-5.5",
            "source": "built-in",
        }
        try:
            with patch.object(server, "hermes_profiles_payload", return_value={"profiles": [{"id": "default", "provider": "openrouter", "model": "openai/gpt-5.5"}]}), patch.object(server, "hermes_python_path", return_value="/tmp/hermes-python"), patch.object(
                server.subprocess, "run"
            ) as run:
                run.return_value.returncode = 0
                run.return_value.stdout = json.dumps(inventory)
                run.return_value.stderr = ""
                catalog = server.agent_console_model_catalog(refresh=True)

            self.assertEqual(catalog["provider"], "openrouter")
            self.assertEqual(catalog["models"], inventory["models"])
            self.assertEqual(run.call_args.args[0][0], "/tmp/hermes-python")
            self.assertIn("build_models_payload", run.call_args.args[0][2])
            self.assertEqual(run.call_args.args[0][-1], "default")
        finally:
            server.AGENT_MODEL_CATALOG_CACHE.update({"key": None, "payload": None, "fetched_at": 0})

    def test_calendar_fallback_payload_is_read_only_and_event_shaped(self):
        tomorrow = (datetime.now().astimezone() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        fallback_events = [
            {
                "id": "cal_demo",
                "title": "Behavior test calendar event",
                "start": tomorrow.isoformat(timespec="seconds"),
                "end": (tomorrow + timedelta(hours=1)).isoformat(timespec="seconds"),
                "type": "local_fallback",
                "description": "Used to verify calendar fallback behavior.",
            }
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "calendar.json", fallback_events)
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "google_credentials", return_value=(None, "Google OAuth token not found")
            ):
                server.CALENDAR_CACHE.update({"key": None, "payload": None, "fetched_at": None})
                payload = server.google_calendar_events(days=7)

        self.assertEqual(payload["source"], "local")
        self.assertEqual(payload["auth"], "not_connected")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["summary"]["count"], 1)
        self.assertTrue(payload["summary"]["fallback_available"])
        self.assertFalse(payload["summary"]["stale"])
        self.assertEqual(payload["summary"]["next_event"]["title"], "Behavior test calendar event")
        self.assertEqual(payload["window"]["label"], "Today + next 6 days")

    def test_resolve_attention_item_updates_json_and_keeps_task_attention_open(self):
        attention = [
            {
                "id": "attn_manual",
                "title": "Manual review item",
                "description": "Resolve me",
                "status": "open",
            }
        ]
        tasks = [
            {
                "id": "task_review_api",
                "title": "Review API payloads",
                "description": "Still needs human review",
                "project": "Mentat",
                "status": "todo",
                "priority": "high",
                "review_required": True,
            },
            {
                "id": "task_done",
                "title": "Already done",
                "status": "completed",
                "project": "Mentat",
            },
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "attention.json", attention)
            self.write_json(root, "tasks.json", tasks)
            with patch.object(server, "DATA_DIR", root):
                payload, status = server.resolve_attention_item("attn_manual")
                follow_up = server.attention_payload()
                stored_attention = json.loads((root / "attention.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["resolved"]["status"], "resolved")
        self.assertIn("resolved_at", payload["resolved"])
        self.assertEqual(payload["open_count"], 1)
        self.assertEqual(stored_attention[0]["status"], "resolved")
        self.assertEqual([item["id"] for item in follow_up["attention"]], ["task:task_review_api"])
        self.assertEqual(follow_up["attention"][0]["source"], "task")

    def test_overview_cards_track_real_dashboard_counts(self):
        now = datetime.now().astimezone()
        tasks = [
            {
                "id": "task_active",
                "title": "Active task",
                "status": "todo",
                "project": "Mentat",
                "created_at": now.isoformat(timespec="seconds"),
            },
            {
                "id": "task_attention",
                "title": "Needs attention task",
                "status": "in progress",
                "project": "Mentat",
                "needs_attention": True,
                "updated_at": now.isoformat(timespec="seconds"),
            },
            {
                "id": "task_recent_done",
                "title": "Recently completed",
                "status": "completed",
                "project": "Mentat",
                "completed_at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
            },
            {
                "id": "task_old_done",
                "title": "Older completed",
                "status": "completed",
                "project": "Mentat",
                "completed_at": (now - timedelta(days=10)).isoformat(timespec="seconds"),
            },
        ]
        projects = [
            {"id": "project_mentat", "name": "Mentat", "status": "active"},
            {"id": "project_archive", "name": "Archive", "status": "paused"},
        ]
        dashboard = {"display_name": "Operator", "greeting_prefix": "Hello"}
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "tasks.json", tasks)
            self.write_json(root, "projects.json", projects)
            self.write_json(root, "attention.json", [])
            self.write_json(root, "dashboard.json", dashboard)
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "CONFIG_DISPLAY_NAME", None
            ), patch.object(server, "CONFIG_GREETING_PREFIX", "Hello"
            ), patch.object(
                server, "read_cron_jobs", return_value={"count": 2, "jobs": []}
            ), patch.object(server, "recent_sessions", return_value={"sessions": [{}, {}, {}]}):
                payload = server.overview()

        self.assertEqual(payload["identity"]["display_name"], "Operator")
        self.assertEqual(payload["identity"]["greeting_prefix"], "Hello")
        self.assertEqual(payload["cards"]["needs_attention"], 1)
        self.assertEqual(payload["cards"]["active_tasks"], 2)
        self.assertEqual(payload["cards"]["completed_this_week"], 1)
        self.assertEqual(payload["cards"]["scheduled_crons"], 2)
        self.assertEqual(payload["cards"]["recent_sessions"], 3)
        self.assertEqual(payload["cards"]["active_projects"], 1)

    def test_projects_endpoint_returns_plain_list_for_ui_hydration(self):
        projects = [
            {
                "id": "project_mentat",
                "name": "Mentat",
                "status": "active",
                "obsidian_note": "",
            }
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", projects)
            with patch.object(server, "DATA_DIR", root):
                payload = server.API_ROUTES["/api/projects"]()

        self.assertEqual(payload["projects"], projects)
        self.assertEqual(payload["projects"][0]["name"], "Mentat")
        self.assertEqual(payload["projects"][0]["obsidian_note"], "")

    def test_agents_endpoint_returns_live_summary_for_agent_pulse(self):
        now = datetime.now().astimezone().replace(microsecond=0)
        agents = [
            {
                "id": "agent_hermes",
                "name": "Hermes",
                "status": "running",
                "current_task": "Review dashboard task queue",
                "project": "Mentat",
                "cwd": "C:/Projects/mentat",
                "model": "gpt-5.4-mini",
                "source": "dashboard",
                "latest_output": "Working through task creation and edit",
                "needs_user_input": False,
                "created_at": (now - timedelta(minutes=3)).isoformat(timespec="seconds"),
                "started_at": (now - timedelta(minutes=3)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(seconds=20)).isoformat(timespec="seconds"),
                "last_heartbeat": (now - timedelta(seconds=20)).isoformat(timespec="seconds"),
            },
            {
                "id": "agent_helper",
                "name": "Helper",
                "status": "blocked",
                "current_task": "Waiting on operator input",
                "project": "Mentat",
                "source": "agent",
                "latest_output": "Need a decision on the next feature slice",
                "needs_user_input": True,
                "created_at": (now - timedelta(minutes=4)).isoformat(timespec="seconds"),
                "started_at": (now - timedelta(minutes=4)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(minutes=2)).isoformat(timespec="seconds"),
                "last_heartbeat": (now - timedelta(minutes=2)).isoformat(timespec="seconds"),
            },
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_db = root / "state.db"
            self.write_json(root, "agents.json", agents)
            with patch.object(server, "DATA_DIR", root), patch.object(server, "STATE_DB", state_db):
                payload = server.agents_payload()

        self.assertEqual([agent["id"] for agent in payload["agents"]], ["agent_hermes", "agent_helper"])
        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["running"], 1)
        self.assertEqual(payload["summary"]["blocked"], 1)
        self.assertEqual(payload["summary"]["live"], 1)
        self.assertEqual(payload["summary"]["stale"], 1)
        self.assertEqual(payload["summary"]["needs_user_input"], 1)
        self.assertFalse(payload["agents"][0]["stale"])
        self.assertTrue(payload["agents"][1]["stale"])
        self.assertEqual(payload["agents"][1]["freshness"], "stale")
        self.assertGreaterEqual(payload["agents"][1]["heartbeat_age_seconds"], 120)
        self.assertIn("agent_heartbeat.py run", payload["guidance"]["run_command"])
        self.assertEqual(payload["sessions"], [])

    def test_agents_payload_derives_live_agents_from_active_hermes_sessions(self):
        now = datetime.now().astimezone().replace(microsecond=0)
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_db = root / "state.db"
            con = sqlite3.connect(state_db)
            con.execute(
                """
                create table sessions (
                    id text primary key, title text, source text, model text,
                    started_at real, ended_at real, message_count integer,
                    tool_call_count integer, input_tokens integer, output_tokens integer,
                    estimated_cost_usd real, archived integer default 0
                )
                """
            )
            con.execute(
                "insert into sessions values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "session_active",
                    "Build Agent Pulse listener",
                    "hermes",
                    "gpt-5",
                    now.timestamp(),
                    None,
                    4,
                    2,
                    220,
                    110,
                    0.0,
                    0,
                ),
            )
            con.commit()
            con.close()

            with patch.object(server, "DATA_DIR", root), patch.object(server, "STATE_DB", state_db):
                payload = server.agents_payload()

        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(payload["summary"]["running"], 1)
        self.assertEqual(payload["summary"]["live"], 1)
        self.assertEqual(payload["summary"]["stale"], 0)
        self.assertEqual(len(payload["agents"]), 1)
        self.assertEqual(payload["agents"][0]["id"], "session_session_active")
        self.assertEqual(payload["agents"][0]["source"], "hermes-session")
        self.assertEqual(payload["agents"][0]["status"], "running")
        self.assertFalse(payload["agents"][0]["stale"])
        self.assertEqual(payload["agents"][0]["session_id"], "session_active")
        self.assertEqual(payload["sessions"][0]["id"], "session_active")

    def test_agent_heartbeat_route_upserts_live_registry_records(self):
        request = {
            "name": "Hermes",
            "status": "running",
            "current_task": "Implement Agent Pulse 2.0",
            "project": "Mentat",
            "cwd": "C:/Projects/mentat",
            "model": "gpt-5.4-mini",
            "source": "dashboard",
            "latest_output": "Streaming a fresh heartbeat",
            "needs_user_input": False,
        }
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "agents.json", [])
            with patch.object(server, "DATA_DIR", root):
                payload, status = server.handle_post_route("/api/agents/heartbeat", request)
                updated_payload, updated_status = server.handle_post_route(
                    "/api/agents/heartbeat",
                    {
                        **request,
                        "id": payload["agent"]["id"],
                        "status": "blocked",
                        "latest_output": "Waiting for a decision",
                        "needs_user_input": True,
                    },
                )
                stored_agents = json.loads((root / "agents.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 201)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["agent"]["name"], "Hermes")
        self.assertEqual(payload["agent"]["status"], "running")
        self.assertEqual(payload["summary"]["running"], 1)
        self.assertEqual(updated_status, 200)
        self.assertEqual(updated_payload["agent"]["id"], payload["agent"]["id"])
        self.assertEqual(updated_payload["agent"]["created_at"], payload["agent"]["created_at"])
        self.assertNotEqual(updated_payload["agent"]["updated_at"], payload["agent"]["updated_at"])
        self.assertEqual(updated_payload["agent"]["status"], "blocked")
        self.assertTrue(updated_payload["agent"]["needs_user_input"])
        self.assertEqual(stored_agents, [updated_payload["agent"]])

    def test_session_replay_builds_structured_trace_from_read_only_state_db(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "tasks.json", [
                {
                    "id": "task_run_replay_trace_view",
                    "title": "Build structured run replay / trace view for sessions",
                    "status": "in_progress",
                    "priority": "high",
                }
            ])
            db_path = root / "state.db"
            con = sqlite3.connect(db_path)
            con.execute(
                """
                create table sessions (
                    id text primary key, title text, source text, model text,
                    started_at real, ended_at real, message_count integer,
                    tool_call_count integer, input_tokens integer, output_tokens integer,
                    estimated_cost_usd real, archived integer default 0
                )
                """
            )
            con.execute(
                """
                create table messages (
                    id integer primary key, session_id text, role text, content text,
                    tool_name text, tool_call_id text, tool_calls text,
                    timestamp real, finish_reason text, active integer default 1
                )
                """
            )
            con.execute(
                "insert into sessions values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("session_trace", "Replay trace test", "telegram", "gpt-test", 1000.0, 1300.0, 5, 2, 100, 50, 0.01, 0),
            )
            terminal_call = {
                "id": "call_tests",
                "call_id": "call_tests",
                "type": "function",
                "function": {"name": "terminal", "arguments": json.dumps({"command": "python -m unittest discover -s tests"})},
            }
            write_call = {
                "id": "call_write",
                "call_id": "call_write",
                "type": "function",
                "function": {"name": "write_file", "arguments": json.dumps({"path": "public/app.js"})},
            }
            con.executemany(
                "insert into messages (id, session_id, role, content, tool_name, tool_call_id, tool_calls, timestamp, finish_reason, active) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                [
                    (1, "session_trace", "user", "Build structured run replay / trace view for sessions", None, None, None, 1000.0, None),
                    (2, "session_trace", "assistant", "", None, None, json.dumps([terminal_call, write_call]), 1010.0, "tool_calls"),
                    (3, "session_trace", "tool", json.dumps({"output": "Ran 2 tests in 0.1s\nOK", "exit_code": 0}), "terminal", "call_tests", None, 1020.0, None),
                    (4, "session_trace", "tool", json.dumps({"success": True, "path": "public/app.js"}), "write_file", "call_write", None, 1030.0, None),
                    (5, "session_trace", "assistant", "Done — completed and verified. Tests passed.", None, None, None, 1300.0, None),
                ],
            )
            con.commit()
            con.close()

            with patch.object(server, "DATA_DIR", root), patch.object(server, "STATE_DB", db_path):
                payload, status = server.session_replay("session_trace")

        replay = payload["replay"]
        self.assertEqual(status, 200)
        self.assertEqual(replay["status"], "completed")
        self.assertTrue(replay["read_only"])
        self.assertIn("structured run replay", replay["user_intent"]["initial"])
        self.assertEqual(replay["summary"]["actions_detected"], 2)
        self.assertEqual(replay["summary"]["usage"]["input_tokens"], 100)
        self.assertEqual(replay["summary"]["usage"]["output_tokens"], 50)
        self.assertEqual(replay["summary"]["usage"]["total_tokens"], 150)
        self.assertEqual(replay["summary"]["usage"]["estimated_cost_usd"], 0.01)
        self.assertEqual(replay["action_counts"]["verification"], 1)
        self.assertEqual(replay["verification"][0]["status"], "ok")
        self.assertEqual(replay["files"][0]["path"], "public/app.js")
        self.assertEqual(replay["related_tasks"][0]["id"], "task_run_replay_trace_view")

    def test_create_task_persists_validated_dashboard_task(self):
        projects = [
            {
                "id": "project_mentat",
                "name": "Mentat",
                "status": "active",
            }
        ]
        request = {
            "title": "Ship dashboard-native task creation",
            "description": "Add the first project-owned create flow.",
            "project": "Mentat",
            "status": "todo",
            "priority": "high",
            "assignee": "Operator",
            "due_date": "2026-07-01",
            "tags": ["phase-3", " write-back ", ""],
            "review_required": True,
            "needs_attention": False,
        }
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", projects)
            self.write_json(root, "tasks.json", [])
            with patch.object(server, "DATA_DIR", root):
                payload, status = server.create_task(request)
                stored_tasks = json.loads((root / "tasks.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 201)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["task"]["title"], request["title"])
        self.assertEqual(payload["task"]["project"], "Mentat")
        self.assertEqual(payload["task"]["status"], "todo")
        self.assertEqual(payload["task"]["priority"], "high")
        self.assertEqual(payload["task"]["assignee"], "Operator")
        self.assertEqual(payload["task"]["due_date"], "2026-07-01")
        self.assertEqual(payload["task"]["tags"], ["phase-3", "write-back"])
        self.assertTrue(payload["task"]["review_required"])
        self.assertFalse(payload["task"]["needs_attention"])
        self.assertEqual(payload["task"]["source"], "dashboard")
        self.assertIsNone(payload["task"]["completed_at"])
        self.assertEqual(payload["task"]["created_at"], payload["task"]["updated_at"])
        self.assertRegex(payload["task"]["id"], r"^task_[a-z0-9_-]+$")
        self.assertEqual(stored_tasks, [payload["task"]])

    def test_update_task_preserves_identity_and_sets_completed_at(self):
        projects = [
            {
                "id": "project_mentat",
                "name": "Mentat",
                "status": "active",
            }
        ]
        existing = {
            "id": "task_existing",
            "title": "Old title",
            "description": "Old description",
            "project": "Mentat",
            "status": "todo",
            "priority": "low",
            "assignee": None,
            "due_date": "2026-07-01",
            "source": "agent",
            "tags": ["legacy"],
            "review_required": True,
            "needs_attention": True,
            "created_at": "2026-06-20T10:00:00-07:00",
            "updated_at": "2026-06-20T10:00:00-07:00",
            "completed_at": None,
        }
        request = {
            "title": "Updated title",
            "description": "Updated description",
            "project": "Mentat",
            "status": "completed",
            "priority": "high",
            "assignee": "Operator",
            "due_date": "",
            "tags": ["phase-3", " write-back "],
            "review_required": False,
            "needs_attention": False,
        }
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", projects)
            self.write_json(root, "tasks.json", [existing])
            with patch.object(server, "DATA_DIR", root):
                payload, status = server.update_task("task_existing", request)
                stored_tasks = json.loads((root / "tasks.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["task"]["id"], "task_existing")
        self.assertEqual(payload["task"]["title"], "Updated title")
        self.assertEqual(payload["task"]["status"], "completed")
        self.assertEqual(payload["task"]["priority"], "high")
        self.assertEqual(payload["task"]["assignee"], "Operator")
        self.assertIsNone(payload["task"]["due_date"])
        self.assertEqual(payload["task"]["tags"], ["phase-3", "write-back"])
        self.assertFalse(payload["task"]["review_required"])
        self.assertFalse(payload["task"]["needs_attention"])
        self.assertEqual(payload["task"]["source"], "agent")
        self.assertEqual(payload["task"]["created_at"], existing["created_at"])
        self.assertNotEqual(payload["task"]["updated_at"], existing["updated_at"])
        self.assertIsNotNone(payload["task"]["completed_at"])
        self.assertEqual(stored_tasks, [payload["task"]])

    def test_post_route_dispatches_task_create_with_json_payload(self):
        projects = [{"id": "project_mentat", "name": "Mentat", "status": "active"}]
        request = {
            "title": "Create through API route",
            "description": "This should flow through the POST route dispatcher.",
            "project": "Mentat",
            "status": "todo",
            "priority": "medium",
            "assignee": "Hermes",
            "due_date": "2026-07-02",
            "tags": ["api", "write-back"],
        }
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", projects)
            self.write_json(root, "tasks.json", [])
            with patch.object(server, "DATA_DIR", root):
                payload, status = server.handle_post_route("/api/tasks", request)
                stored_tasks = json.loads((root / "tasks.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 201)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["task"]["title"], "Create through API route")
        self.assertEqual(stored_tasks[0]["title"], "Create through API route")

    def test_post_route_dispatches_task_update_with_json_payload(self):
        projects = [{"id": "project_mentat", "name": "Mentat", "status": "active"}]
        existing = {
            "id": "task_existing",
            "title": "Existing title",
            "description": "Before update",
            "project": "Mentat",
            "status": "todo",
            "priority": "medium",
            "assignee": "Hermes",
            "due_date": "2026-07-02",
            "source": "agent",
            "tags": ["api"],
            "review_required": False,
            "needs_attention": False,
            "created_at": "2026-06-20T10:00:00-07:00",
            "updated_at": "2026-06-20T10:00:00-07:00",
            "completed_at": None,
        }
        request = {
            "title": "Updated through API route",
            "description": "After update",
            "project": "Mentat",
            "status": "in progress",
            "priority": "high",
            "assignee": "Operator",
            "due_date": "2026-07-03",
            "tags": ["api", "edited"],
            "review_required": True,
            "needs_attention": True,
        }
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", projects)
            self.write_json(root, "tasks.json", [existing])
            with patch.object(server, "DATA_DIR", root):
                payload, status = server.handle_post_route("/api/tasks/task_existing", request)
                stored_tasks = json.loads((root / "tasks.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["task"]["title"], "Updated through API route")
        self.assertEqual(payload["task"]["status"], "in progress")
        self.assertTrue(payload["task"]["review_required"])
        self.assertTrue(payload["task"]["needs_attention"])
        self.assertEqual(stored_tasks[0]["title"], "Updated through API route")

    def test_projects_tasks_view_wires_task_editor_controls_to_shared_writeback_api(self):
        index_html = Path("public/index.html").read_text(encoding="utf-8")
        app_js = Path("public/app.js").read_text(encoding="utf-8")
        core_js = Path("public/core.js").read_text(encoding="utf-8")

        self.assertIn('id="create-task-button"', index_html)
        self.assertIn('id="selected-task-edit"', index_html)
        self.assertIn('id="selected-task-cancel"', index_html)
        self.assertIn('id="selected-task-detail"', index_html)
        self.assertIn('async function createTask(payload)', core_js)
        self.assertIn('async function saveTaskEdits(id, payload)', core_js)
        self.assertIn("document.addEventListener('click'", app_js)
        self.assertIn("event.target.closest('#create-task-button')", app_js)
        self.assertIn("event.target.closest('#selected-task-edit')", app_js)
        self.assertIn("event.target.closest('#selected-task-cancel')", app_js)
        self.assertIn("event.target.closest('[data-task-editor-cancel]')", app_js)
        self.assertIn("state.taskEditorDraft = taskPayloadFromForm(form);", app_js)


if __name__ == "__main__":
    unittest.main()
