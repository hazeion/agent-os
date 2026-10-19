from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import agent_run_history
import run_repository
import server
from mentat_db import MentatDatabaseError, connect, database_path
from private_console_unit import capture_private_console_unit
from private_state import fresh_console_storage_issue
from tests.test_private_console_state import save_current_run_summaries, initialize_current_run_store
from run_repository import RunRepositoryUnavailable, load_authoritative_run_summaries
from task_repository import ensure_task_sqlite_authority


def sample_run(run_id: str, created_at: str, **overrides) -> dict:
    run = {
        "id": run_id,
        "agent_id": "hermes",
        "agent_name": "Hermes",
        "model": "test/model",
        "status": "completed",
        "session_id": None,
        "prompt": "short prompt",
        "response": "short response",
        "error": "",
        "created_at": created_at,
        "updated_at": created_at,
        "started_at": created_at,
        "completed_at": created_at,
        "duration_seconds": 1.5,
    }
    run.update(overrides)
    return run


class AgentRunHistoryTests(unittest.TestCase):
    def load_runs(self, data_dir: Path) -> None:
        source = data_dir / "tasks.json"
        if not source.exists():
            source.write_text("[]\n", encoding="utf-8")
            source.chmod(0o600)
        ensure_task_sqlite_authority(data_dir, required_source_mode=None)
        server.load_agent_console_runs()

    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PERSISTENCE_DEGRADED = False
        server.AGENT_CONSOLE_PERSISTENCE_DEGRADED_DATA_DIR = None

    def test_retained_media_names_reject_posix_and_windows_paths(self):
        base = {
            "id": "attachment_" + ("a" * 32),
            "mime_type": "text/plain",
            "kind": "text",
            "byte_size": 1,
            "state": "attached",
            "created_at": "2026-08-18T12:00:00+00:00",
            "expires_at": None,
        }
        for name in ("/Users/Alice/secret.txt", r"C:\Users\Alice\secret.txt"):
            with self.subTest(name=name):
                self.assertEqual(
                    agent_run_history.normalize_attachments([{**base, "name": name}]),
                    [],
                )

    def test_save_rejects_explicitly_malformed_transport_binding(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            initialize_current_run_store(root)
            with self.assertRaisesRegex(ValueError, "transport binding"):
                save_current_run_summaries(root, [sample_run(
                    "run_invalid_binding", "2026-07-10T12:00:00-07:00",
                    transport_mode="remote", connection_binding_id="local-default",
                )])
            self.assertEqual(load_authoritative_run_summaries(root), [])

    def test_persisted_summaries_are_bounded_and_redact_common_secrets(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt = "api_key=very-secret-value " + ("p" * 800)
            response = "Authorization: Bearer hidden-token\n" + ("r" * 2_500)
            save_current_run_summaries(
                root,
                [sample_run("run_private", "2026-07-10T12:00:00-07:00", prompt=prompt, response=response)],
            )

            raw = capture_private_console_unit(root).history_raw.decode("utf-8")
            payload = json.loads(raw)
            stored = payload["runs"][0]

        self.assertEqual(payload["schema_version"], agent_run_history.SCHEMA_VERSION)
        self.assertNotIn("very-secret-value", raw)
        self.assertNotIn("hidden-token", raw)
        self.assertNotIn("prompt\"", raw)
        self.assertLessEqual(len(stored["prompt_excerpt"]), agent_run_history.PROMPT_EXCERPT_LIMIT)
        self.assertLessEqual(len(stored["response_excerpt"]), agent_run_history.RESPONSE_EXCERPT_LIMIT)
        self.assertTrue(stored["prompt_truncated"])
        self.assertTrue(stored["response_truncated"])

    def test_private_history_redacts_extended_credentials_and_uses_private_modes(self):
        private_key = """-----BEGIN TEST PRIVATE KEY-----
super-private-material
-----END TEST PRIVATE KEY-----"""
        github_token = "github_" + "pat_1234567890abcdefghijklmnop"
        slack_token = "xox" + "b-123456789012-abcdefghijklmnop"
        secrets = " ".join(
            [
                github_token,
                slack_token,
                "abcdefghij.klmnopqrst.uvwxyz1234",
                private_key,
            ]
        )
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_current_run_summaries(
                root,
                [
                    sample_run(
                        "run_secrets",
                        "2026-07-10T12:00:00-07:00",
                        prompt=secrets,
                        response=secrets,
                    )
                ],
            )
            raw = capture_private_console_unit(root).history_raw.decode("utf-8")
            path = database_path(root)
            file_mode = stat.S_IMODE(path.stat().st_mode)
            directory_mode = stat.S_IMODE(path.parent.stat().st_mode)

        self.assertNotIn("github_" + "pat_", raw)
        self.assertNotIn("xox" + "b-", raw)
        self.assertNotIn("abcdefghij.klmnopqrst.uvwxyz1234", raw)
        self.assertNotIn("super-private-material", raw)
        if os.name != "nt":
            self.assertEqual(file_mode, 0o600)
            self.assertEqual(directory_mode, 0o700)

    def test_truncated_legacy_private_key_is_redacted_through_end_of_input(self):
        fragment = (
            "before\n-----BEGIN RSA PRIVATE KEY-----\n"
            "legacy-private-material-without-an-end-marker"
        )

        redacted, _ = agent_run_history.bounded_excerpt(fragment, 500)

        self.assertEqual(redacted, "before\n[REDACTED]")
        self.assertNotIn("legacy-private-material", redacted)

    def test_retention_is_newest_first_with_id_as_deterministic_tiebreaker(self):
        runs = [
            sample_run("run_a", "2026-07-10T12:00:00-07:00"),
            sample_run("run_c", "2026-07-10T12:00:00-07:00"),
            sample_run("run_b", "2026-07-10T13:00:00-07:00"),
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_current_run_summaries(root, runs)
            stored = load_authoritative_run_summaries(root, limit=2)

        self.assertEqual([item["id"] for item in stored], ["run_b", "run_c"])

    def test_current_sql_load_marks_unattached_console_run_interrupted(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_current_run_summaries(root, [sample_run(
                "run_active", "2026-07-10T12:00:00-07:00", status="running", completed_at=None,
            )])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                self.load_runs(root)
            runs = load_authoritative_run_summaries(root)
            self.assertEqual(runs[0]["status"], "interrupted")
            self.assertTrue(runs[0]["partial"])
            self.assertIsNotNone(runs[0]["completed_at"])
            self.assertTrue(any(e["type"] == "run.interrupted" for e in runs[0]["events"]))

    def test_corrupt_and_future_sql_refuse_without_rewriting_or_empty_fallback(self):
        for kind in ("corrupt", "future"):
            with self.subTest(kind=kind), TemporaryDirectory() as temporary:
                root = Path(temporary)
                initialize_current_run_store(root)
                path = database_path(root)
                if kind == "corrupt":
                    path.write_bytes(b"invalid database")
                else:
                    connection = connect(root)
                    try:
                        connection.execute("INSERT INTO schema_migrations VALUES(47,0)")
                        connection.commit()
                    finally:
                        connection.close()
                before = path.read_bytes()
                with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                    with self.assertRaises(RunRepositoryUnavailable):
                        server.load_agent_console_runs()
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse(server.AGENT_CONSOLE_HISTORY_LOADED)
                self.assertTrue(server.AGENT_CONSOLE_PERSISTENCE_DEGRADED)

    def test_server_recovers_current_sql_without_reading_stale_history(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            path = data_dir / "private" / "console" / "agent-console-runs.json"
            save_current_run_summaries(
                data_dir,
                [sample_run("run_queued", "2026-07-10T12:00:00-07:00", status="queued", completed_at=None)],
            )
            path.write_text(json.dumps({"schema_version": 3, "runs": [{"id": "run_queued", "status": "queued"}]}))
            path.chmod(0o600)
            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ):
                self.load_runs(data_dir)
                legacy = json.loads(path.read_text(encoding="utf-8"))["runs"]
                stored = load_authoritative_run_summaries(data_dir)

        self.assertEqual(server.AGENT_CONSOLE_RUNS["run_queued"]["status"], "interrupted")
        self.assertEqual(stored[0]["status"], "interrupted")
        self.assertEqual(legacy[0]["status"], "queued")
        server.AGENT_CONSOLE_RUNS.clear()

    def test_server_current_sql_preserves_redaction_and_private_modes(self):
        secret = "github_" + "pat_1234567890abcdefghijklmnop"
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_current_run_summaries(root, [sample_run(
                "run_completed", "2026-07-10T12:00:00-07:00", prompt=secret, response=secret,
            )])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                self.load_runs(root)
            stored = load_authoritative_run_summaries(root)[0]
            self.assertNotIn(secret, json.dumps(stored))
            self.assertIn("[REDACTED]", json.dumps(stored))
            self.assertNotIn(secret.encode(), capture_private_console_unit(root).history_raw)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(database_path(root).stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(database_path(root).parent.stat().st_mode), 0o700)

    def test_server_refuses_corrupt_unclaimed_history_without_hardening_it(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            path = data_dir / "private" / "console" / "agent-console-runs.json"
            path.parent.mkdir(parents=True)
            path.write_text("{broken", encoding="utf-8")
            path.parent.chmod(0o755)
            path.chmod(0o644)

            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ):
                with self.assertRaises(RunRepositoryUnavailable):
                    server.load_agent_console_runs()
                self.assertFalse(server.AGENT_CONSOLE_HISTORY_LOADED)
                raw = path.read_text(encoding="utf-8")
                file_mode = stat.S_IMODE(path.stat().st_mode)
                directory_mode = stat.S_IMODE(path.parent.stat().st_mode)

        self.assertEqual(raw, "{broken")
        if os.name != "nt":
            self.assertEqual(file_mode, 0o644)
            self.assertEqual(directory_mode, 0o755)
        self.assertEqual(server.AGENT_CONSOLE_RUNS, {})

    @unittest.skipIf(os.name == "nt", "Symlink creation is not reliably available on Windows")
    def test_server_skips_history_file_symlink_without_changing_external_target(self):
        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as outside_dir:
            data_dir = Path(tmpdir)
            private_dir = data_dir / "private" / "console"
            private_dir.mkdir(parents=True)
            outside = Path(outside_dir) / "external-history.json"
            outside.write_text(
                json.dumps(
                    {
                        "schema_version": agent_run_history.SCHEMA_VERSION,
                        "runs": [
                            {
                                "id": "external_run",
                                "status": "completed",
                                "created_at": "2026-07-11T12:00:00-07:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            outside.chmod(0o644)
            (private_dir / "agent-console-runs.json").symlink_to(outside)

            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ):
                server.AGENT_CONSOLE_RUNS["existing"] = {"id": "existing"}
                with self.assertRaises(RunRepositoryUnavailable):
                    server.load_agent_console_runs()
                self.assertFalse(server.AGENT_CONSOLE_HISTORY_LOADED)

            self.assertEqual(server.AGENT_CONSOLE_RUNS, {})
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o644)
            self.assertIn("external_run", outside.read_text(encoding="utf-8"))

    @unittest.skipIf(os.name == "nt", "Symlink creation is not reliably available on Windows")
    def test_server_skips_symlinked_private_directory_outside_data_root(self):
        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as outside_dir:
            data_dir = Path(tmpdir)
            outside = Path(outside_dir)
            outside_history = outside / "agent-console-runs.json"
            outside_history.write_text(
                json.dumps({"schema_version": agent_run_history.SCHEMA_VERSION, "runs": []}),
                encoding="utf-8",
            )
            outside.chmod(0o755)
            outside_history.chmod(0o644)
            (data_dir / "private").symlink_to(outside, target_is_directory=True)

            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ):
                with self.assertRaises(RunRepositoryUnavailable):
                    server.load_agent_console_runs()
                self.assertFalse(server.AGENT_CONSOLE_HISTORY_LOADED)

            self.assertEqual(server.AGENT_CONSOLE_RUNS, {})
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(outside_history.stat().st_mode), 0o644)

    def test_starting_console_run_persists_summary_without_full_prompt(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ), patch.object(
                server,
                "hermes_profiles_payload",
                return_value={"status": "available", "profiles": [{"id": "default"}]},
            ), patch.object(server, "hermes_command_path", return_value="/tmp/hermes"), patch.object(
                server, "agent_console_model", return_value="test/model"
            ), patch.object(server.threading, "Thread"):
                self.load_runs(data_dir)
                payload, status = server.start_agent_console_run({
                    "agent_id": "hermes",
                    "prompt": "x" * (agent_run_history.PROMPT_EXCERPT_LIMIT + 25),
                })
                stored = load_authoritative_run_summaries(data_dir)[0]
                legacy_path = data_dir / "private" / "console" / "agent-console-runs.json"

        self.assertEqual(status, 202)
        self.assertEqual(stored["id"], payload["run"]["id"])
        self.assertEqual(len(stored["prompt"]), agent_run_history.PROMPT_EXCERPT_LIMIT)
        self.assertTrue(stored["prompt_truncated"])
        self.assertFalse(legacy_path.exists())
        server.AGENT_CONSOLE_RUNS.clear()

    def test_console_does_not_start_worker_when_initial_sqlite_write_fails(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with patch.object(server, "DATA_DIR", data_dir), patch.object(
                server, "CONFIGURED_DATA_DIR", data_dir
            ), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ), patch.object(
                server,
                "hermes_profiles_payload",
                return_value={"status": "available", "profiles": [{"id": "default"}]},
            ), patch.object(
                server, "hermes_command_path", return_value="/tmp/hermes"
            ), patch.object(
                server, "agent_console_model", return_value="test/model"
            ), patch.object(
                server.threading, "Thread"
            ) as thread_factory:
                self.load_runs(data_dir)
                with patch.object(
                    server,
                    "save_authoritative_run_summaries",
                    side_effect=RunRepositoryUnavailable("run_repository.unavailable"),
                ):
                    payload, status = server.start_agent_console_run(
                        {"agent_id": "hermes", "prompt": "Do not start"}
                    )

        self.assertEqual(status, 503)
        self.assertEqual(payload["error_code"], "run_repository_unavailable")
        thread_factory.assert_not_called()
        self.assertEqual(server.AGENT_CONSOLE_RUNS, {})

    def test_post_start_persistence_failure_reloads_sqlite_and_blocks_controls(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with patch.object(server, "DATA_DIR", data_dir), patch.object(
                server, "CONFIGURED_DATA_DIR", data_dir
            ), patch.object(server, "AGENT_CONSOLE_HISTORY_LOADED", False):
                self.load_runs(data_dir)
                authoritative = sample_run(
                    "run_authoritative",
                    "2026-08-18T12:00:00+00:00",
                )
                server.AGENT_CONSOLE_RUNS[authoritative["id"]] = authoritative
                self.assertTrue(server.persist_agent_console_runs())

                volatile = server.AGENT_CONSOLE_RUNS[authoritative["id"]]
                volatile["status"] = "failed"
                volatile["error"] = "This update must not be presented as durable."
                with patch.object(
                    server,
                    "save_authoritative_run_summaries",
                    side_effect=RunRepositoryUnavailable("run_repository.unavailable"),
                ):
                    self.assertFalse(server.persist_agent_console_runs())

                self.assertTrue(server.AGENT_CONSOLE_PERSISTENCE_DEGRADED)
                self.assertEqual(
                    server.AGENT_CONSOLE_RUNS[authoritative["id"]]["status"],
                    "completed",
                )
                self.assertEqual(server.agent_console_snapshot(volatile)["status"], "completed")
                payload, status = server.start_agent_console_run(
                    {"agent_id": "default", "prompt": "Do not launch"}
                )

        self.assertEqual(status, 503)
        self.assertEqual(payload["error_code"], "run_repository_unavailable")

    def test_terminal_snapshot_racing_steer_is_partial_before_queue_reservation(self):
        run = sample_run(
            "run_terminal_steer_race",
            "2026-08-18T12:00:00+00:00",
            runtime_type="hermes",
            partial=False,
            _steer_inflight=True,
        )
        server.AGENT_CONSOLE_RUNS[run["id"]] = run
        captured = []

        def save(_root, runs):
            captured.extend(runs)
            return run_repository.RetentionReport((), ())

        with patch.object(
            server,
            "agent_console_history_is_current",
            return_value=True,
        ), patch.object(
            server,
            "agent_console_storage_degraded",
            return_value=False,
        ), patch.object(
            server,
            "save_authoritative_run_summaries",
            side_effect=save,
        ):
            self.assertTrue(server.persist_agent_console_runs())

        self.assertTrue(run["partial"])
        self.assertTrue(captured[0]["partial"])

    def test_database_setup_failure_enters_scoped_degraded_state(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with patch.object(server, "DATA_DIR", data_dir), patch.object(
                server, "CONFIGURED_DATA_DIR", data_dir
            ), patch.object(server, "AGENT_CONSOLE_HISTORY_LOADED", False):
                self.load_runs(data_dir)
                server.AGENT_CONSOLE_RUNS["run_setup_failure"] = sample_run(
                    "run_setup_failure", "2026-08-18T12:00:00+00:00"
                )
                with patch.object(
                    run_repository,
                    "connect",
                    side_effect=MentatDatabaseError("database unavailable"),
                ):
                    self.assertFalse(server.persist_agent_console_runs())

                self.assertTrue(server.agent_console_storage_degraded())
                payload, status = server.start_agent_console_run(
                    {"agent_id": "default", "prompt": "Do not launch"}
                )

        self.assertEqual(status, 503)
        self.assertEqual(payload["error_code"], "run_repository_unavailable")

    def test_startup_database_open_failure_enters_scoped_degraded_state(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with patch.object(server, "DATA_DIR", data_dir), patch.object(
                server, "CONFIGURED_DATA_DIR", data_dir
            ), patch.object(server, "AGENT_CONSOLE_HISTORY_LOADED", False):
                self.load_runs(data_dir)
                with patch.object(
                    server,
                    "connect_mentat_database",
                    side_effect=MentatDatabaseError("database unavailable"),
                ):
                    with self.assertRaisesRegex(
                        RunRepositoryUnavailable, "run_repository.unavailable"
                    ):
                        self.load_runs(data_dir)
                self.assertTrue(server.agent_console_storage_degraded())

    @unittest.skipIf(os.name != "posix", "Descriptor identity race is POSIX-specific")
    def test_current_history_admission_rejects_hardlink_replacement_without_chmod(self):
        with TemporaryDirectory() as temporary, TemporaryDirectory() as outside_dir:
            root = Path(temporary)
            path = root / "private" / "console" / "agent-console-runs.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"schema_version":3,"runs":[]}')
            path.chmod(0o600)
            outside = Path(outside_dir) / "outside.json"
            outside.write_bytes(b"outside")
            outside.chmod(0o644)
            real_open = os.open
            replaced = False
            def racing_open(candidate, flags, *args, **kwargs):
                nonlocal replaced
                if candidate == path.name and not replaced:
                    replaced = True
                    path.unlink()
                    os.link(outside, path)
                return real_open(candidate, flags, *args, **kwargs)
            with patch("private_state.os.open", side_effect=racing_open):
                self.assertIsNotNone(fresh_console_storage_issue(root))
            self.assertTrue(replaced)
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o644)
            self.assertEqual(outside.read_bytes(), b"outside")
            self.assertFalse(database_path(root).exists())

    def test_schema_three_preserves_orchestration_binding_and_rejects_other_runtime(self):
        summary = agent_run_history.summarize_run(
            sample_run(
                "run_orchestrated",
                "2026-08-17T12:00:00+00:00",
                runtime_type="hermes",
                mentat_agent_id="agent_researcher",
                task_id="task_research",
            )
        )
        hydrated = agent_run_history._hydrate(summary)

        self.assertEqual(agent_run_history.SCHEMA_VERSION, 3)
        self.assertEqual(hydrated["runtime_type"], "hermes")
        self.assertEqual(hydrated["mentat_agent_id"], "agent_researcher")
        self.assertEqual(hydrated["task_id"], "task_research")
        self.assertIsNone(agent_run_history._hydrate({**summary, "runtime_type": "codex"}))

    def test_schema_three_preserves_maximum_length_task_binding(self):
        task_id = "task@" + ("h" * 155)
        summary = agent_run_history.summarize_run(
            sample_run(
                "run_wide_task_binding",
                "2026-08-17T12:00:00+00:00",
                runtime_type="hermes",
                mentat_agent_id="agent_researcher",
                task_id=task_id,
                events=[{
                    "id": "event_wide_binding",
                    "run_id": "run_wide_task_binding",
                    "sequence": 1,
                    "type": "runtime.bound",
                    "timestamp": "2026-08-17T12:00:00+00:00",
                    "display_text": "Mentat task bound",
                    "data": {
                        "mentat_agent_id": "agent_researcher",
                        "task_id": task_id,
                    },
                }],
            )
        )
        hydrated = agent_run_history._hydrate(summary)

        self.assertEqual(summary["task_id"], task_id)
        self.assertEqual(hydrated["task_id"], task_id)

    def test_runtime_binding_survives_a_prior_reader_dropping_top_level_fields(self):
        summary = agent_run_history.summarize_run(
            sample_run(
                "run_rollback",
                "2026-08-17T12:00:00+00:00",
                runtime_type="hermes",
                mentat_agent_id="agent_rollback",
                task_id="task_rollback",
                events=[{
                    "id": "event_binding",
                    "run_id": "run_rollback",
                    "sequence": 1,
                    "type": "runtime.bound",
                    "timestamp": "2026-08-17T12:00:00+00:00",
                    "display_text": "Mentat task bound",
                    "data": {
                        "mentat_agent_id": "agent_rollback",
                        "task_id": "task_rollback",
                    },
                }],
            )
        )
        prior_reader_rewrite = {
            key: value
            for key, value in summary.items()
            if key not in {"mentat_agent_id", "task_id"}
        }
        hydrated = agent_run_history._hydrate(prior_reader_rewrite)

        self.assertEqual(hydrated["mentat_agent_id"], "agent_rollback")
        self.assertEqual(hydrated["task_id"], "task_rollback")

    def test_runtime_binding_survives_more_than_event_retention_updates(self):
        events = [{
            "id": "event_binding",
            "run_id": "run_rollback_long",
            "sequence": 1,
            "type": "runtime.bound",
            "timestamp": "2026-08-17T12:00:00+00:00",
            "display_text": "Mentat task bound",
            "data": {
                "mentat_agent_id": "agent_rollback",
                "task_id": "task_rollback",
            },
        }]
        events.extend({
            "id": f"event_{sequence}",
            "run_id": "run_rollback_long",
            "sequence": sequence,
            "type": "status",
            "timestamp": "2026-08-17T12:00:01+00:00",
            "display_text": "Working",
        } for sequence in range(2, agent_run_history.EVENT_RETENTION + 20))

        retained = agent_run_history.normalize_events("run_rollback_long", events)
        prior_reader_summary = agent_run_history.summarize_run(sample_run(
            "run_rollback_long",
            "2026-08-17T12:00:00+00:00",
            events=retained,
        ))
        hydrated = agent_run_history._hydrate(prior_reader_summary)

        self.assertEqual(len(retained), agent_run_history.EVENT_RETENTION)
        self.assertEqual(retained[0]["type"], "runtime.bound")
        self.assertEqual(hydrated["mentat_agent_id"], "agent_rollback")
        self.assertEqual(hydrated["task_id"], "task_rollback")


if __name__ == "__main__":
    unittest.main()
