from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import agent_run_history
import server
from agent_console_artifacts import (
    SECURE_DIR_FD_DELETE,
    ArtifactValidationError,
    cleanup_run_input_directory,
)
from agent_console_telemetry import (
    MAX_PROGRESS_BYTES,
    ProgressTail,
    prepare_local_telemetry_paths,
    read_usage,
)
from hermes_transport import LocalHermesConsoleTransport, TransportBinding


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")


class AgentConsoleObservabilityTests(unittest.TestCase):
    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()

    def test_fresh_run_is_pending_until_hermes_accepts_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            transport = LocalHermesConsoleTransport(
                TransportBinding("local", "Local Hermes", "local-default"),
                command_path="/opt/hermes/bin/hermes",
                hermes_home=Path(temporary) / "hermes",
                cwd=ROOT,
            )
            profiles = {
                "status": "available",
                "profiles": [{"id": "default", "name": "default", "is_default": True}],
            }
            with patch.object(server, "DATA_DIR", data_dir), patch.object(
                server,
                "CONFIGURED_DATA_DIR",
                data_dir,
            ), patch.object(
                server,
                "hermes_console_transport",
                return_value=transport,
            ), patch.object(
                server,
                "hermes_profiles_payload",
                return_value=profiles,
            ), patch.object(
                transport,
                "revalidate",
            ), patch.object(
                server,
                "agent_console_model",
                return_value="test/model",
            ), patch.object(server.threading, "Thread") as worker:
                payload, status = server.start_agent_console_run({
                    "agent_id": "default",
                    "prompt": "Begin cleanly",
                    "start_new_session": True,
                })

            self.assertEqual(status, 202)
            self.assertFalse(payload["run"]["starts_new_session"])
            self.assertEqual(payload["run"]["new_session_state"], "pending")
            self.assertFalse(any(
                event["type"] == "session.started"
                for event in payload["run"]["events"]
            ))
            worker.return_value.start.assert_called_once_with()

            with patch.object(server, "DATA_DIR", data_dir), patch.object(
                server,
                "CONFIGURED_DATA_DIR",
                data_dir,
            ):
                rejected, rejected_status = server.start_agent_console_run({
                    "agent_id": "default",
                    "prompt": "Conflicting request",
                    "session_id": "session_existing",
                    "start_new_session": True,
                })
            self.assertEqual(rejected_status, 400)
            self.assertIn("cannot also resume", rejected["error"])

    def test_local_launch_uses_private_structured_telemetry_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary).resolve()
            usage_path = private_root / "run" / "usage.json"
            progress_path = private_root / "run" / "progress.jsonl"
            adapter = LocalHermesConsoleTransport(
                TransportBinding("local", "Local Hermes", "local-default"),
                command_path="/opt/hermes/bin/hermes",
                hermes_home=private_root / "hermes",
                cwd=ROOT,
            )
            launch = adapter.build_console_launch(
                profile_id="default",
                prompt="Inspect the project",
                session_id=None,
                image_path=None,
                usage_path=usage_path,
                progress_path=progress_path,
            )
            self.assertNotIn("--usage-file", launch.command)
            self.assertNotIn("--progress-file", launch.command)
            self.assertEqual(
                launch.env["MENTAT_HERMES_USAGE_FILE"],
                str(usage_path),
            )
            self.assertEqual(
                launch.env["MENTAT_HERMES_PROGRESS_FILE"],
                str(progress_path),
            )

    def test_progress_tail_waits_for_complete_lines_and_drops_unsafe_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            root.mkdir()
            progress_path, _usage_path = prepare_local_telemetry_paths(
                root,
                "run_1234567890abcd",
            )
            tail = ProgressTail(progress_path)
            progress_path.write_bytes(
                b'{"schema_version":1,"type":"tool.started","tool":"browser.search",'
                b'"summary":"Using browser.search","sequence":1}\n'
                b'{"schema_version":1,"type":"reasoning.available","summary":"Inspecting'
            )
            self.assertEqual(
                tail.poll(),
                [{
                    "type": "tool.started",
                    "tool": "browser.search",
                    "summary": "Using browser.search",
                    "sequence": 1,
                }],
            )
            with progress_path.open("ab") as handle:
                handle.write(b' relevant context","sequence":2}\n')
            self.assertEqual(
                tail.poll(),
                [{
                    "type": "reasoning.available",
                    "summary": "Inspecting relevant context",
                    "sequence": 2,
                }],
            )
            with progress_path.open("ab") as handle:
                handle.write(
                    b'{"schema_version":1,"type":"reasoning.available",'
                    b'"summary":"token=secret","sequence":3}\n'
                )
            self.assertEqual(tail.poll(), [])

    def test_progress_tail_rejects_symlinks_and_oversized_files(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            root.mkdir()
            progress_path, _usage_path = prepare_local_telemetry_paths(
                root,
                "run_1234567890abcd",
            )
            progress_path.unlink()
            target = progress_path.with_name("target")
            target.write_text("{}\n", encoding="utf-8")
            progress_path.symlink_to(target)
            with self.assertRaises(ValueError):
                ProgressTail(progress_path).poll()
            progress_path.unlink()
            progress_path.write_bytes(b"x" * (MAX_PROGRESS_BYTES + 1))
            with self.assertRaises(ValueError):
                ProgressTail(progress_path).poll()

    @unittest.skipUnless(
        SECURE_DIR_FD_DELETE,
        "secure POSIX directory descriptors required",
    )
    def test_cleanup_removes_unsafe_telemetry_symlink_without_following_it(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            root.mkdir()
            progress_path, _usage_path = prepare_local_telemetry_paths(
                root,
                "run_1234567890abcd",
            )
            outside = Path(temporary) / "outside"
            outside.write_text("keep", encoding="utf-8")
            progress_path.unlink()
            progress_path.symlink_to(outside)
            removed = cleanup_run_input_directory(
                root,
                "run_1234567890abcd",
            )
            self.assertEqual(removed, 2)
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep")

    def test_cleanup_fails_closed_without_secure_directory_descriptors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            root.mkdir()
            progress_path, _usage_path = prepare_local_telemetry_paths(
                root,
                "run_1234567890abcd",
            )
            with patch(
                "agent_console_artifacts.SECURE_DIR_FD_DELETE",
                False,
            ), self.assertRaises(ArtifactValidationError) as rejected:
                cleanup_run_input_directory(root, "run_1234567890abcd")
            self.assertEqual(rejected.exception.code, "unsafe_input_directory")
            self.assertTrue(progress_path.is_file())

    def test_progress_tail_fails_closed_on_duplicate_or_regressing_sequence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            root.mkdir()
            progress_path, _usage_path = prepare_local_telemetry_paths(
                root,
                "run_1234567890abcd",
            )
            progress_path.write_text(
                "\n".join([
                    '{"schema_version":1,"type":"tool.started","tool":"terminal",'
                    '"summary":"Using terminal","sequence":2}',
                    '{"schema_version":1,"type":"tool.completed","tool":"terminal",'
                    '"summary":"Finished terminal","sequence":2}',
                    "",
                ]),
                encoding="utf-8",
            )
            tail = ProgressTail(progress_path)
            with self.assertRaisesRegex(ValueError, "sequence"):
                tail.poll()
            self.assertEqual(tail.poll(), [])

    def test_usage_requires_exact_context_pair_and_never_uses_billing_total(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "usage.json"
            base = {
                "schema_version": 1,
                "input_tokens": 120,
                "output_tokens": 30,
                "total_tokens": 150,
            }
            path.write_text(
                json.dumps({**base, "context_tokens": 24000, "context_length": 128000}),
                encoding="utf-8",
            )
            self.assertEqual(
                read_usage(path),
                {
                    "input_tokens": 120,
                    "output_tokens": 30,
                    "total_tokens": 150,
                    "context_tokens": 24000,
                    "context_length": 128000,
                },
            )
            path.write_text(
                json.dumps({**base, "context_tokens": None, "context_length": None}),
                encoding="utf-8",
            )
            billing_usage = read_usage(path)
            self.assertEqual(
                billing_usage,
                {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
            )
            self.assertNotIn("context_tokens", billing_usage)

    def test_history_preserves_context_and_new_session_marker(self):
        run = {
            "id": "run_observability",
            "agent_id": "default",
            "agent_name": "default",
            "status": "completed",
            "prompt": "hello",
            "response": "done",
            "error": "",
            "events": [],
            "starts_new_session": True,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "context_tokens": 1000,
                "context_length": 32000,
            },
            "created_at": "2026-07-25T12:00:00-07:00",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runs.json"
            agent_run_history.save_run_summaries(path, [run])
            loaded, recovered = agent_run_history.load_run_summaries(path)
        self.assertFalse(recovered)
        self.assertTrue(loaded[0]["starts_new_session"])
        self.assertEqual(loaded[0]["usage"]["context_length"], 32000)

        run["usage"]["context_tokens"] = 64000
        run["usage"]["context_length"] = "invalid"
        summary = agent_run_history.summarize_run(run)
        self.assertEqual(
            summary["usage"],
            {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        run["usage"]["context_tokens"] = 0
        run["usage"]["context_length"] = 32000
        self.assertEqual(
            agent_run_history.summarize_run(run)["usage"],
            {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )

    def test_ui_renders_used_total_percent_progress_and_session_feedback(self):
        self.assertIn("context tokens used", APP_JS)
        self.assertIn("total context window", APP_JS)
        self.assertIn("contextPercent", APP_JS)
        self.assertIn("contextTokens > 0", APP_JS)
        self.assertIn("New Hermes session started", APP_JS)
        self.assertIn("Next prompt starts a new Hermes session.", APP_JS)
        self.assertIn(
            'role="separator" aria-label="New Hermes session started"',
            APP_JS,
        )
        self.assertIn(
            "Context window ${humanNumber(contextTokens)} of ${humanNumber(contextLength)} tokens used",
            APP_JS,
        )
        self.assertIn("start_new_session: startingFresh", APP_JS)
        self.assertIn("eventType.startsWith('tool.')", APP_JS)
        self.assertIn("eventType === 'reasoning.available'", APP_JS)
        self.assertIn('class="agent-console-reasoning-detail" open', APP_JS)
        self.assertIn("Collapse thinking", APP_JS)
        self.assertIn("Show thinking", APP_JS)
        self.assertIn(".agent-console-reasoning-detail", STYLES)
        self.assertIn(".agent-console-session-divider", STYLES)
        self.assertIn(".agent-console-context-usage", STYLES)
        self.assertIn('role="region" aria-live="off"', (ROOT / "public" / "index.html").read_text())
        self.assertNotIn('agent-console-working" role="status"', APP_JS)
