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
from mentat_db import MentatDatabaseError
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
            path = Path(tmpdir) / "history.json"
            with self.assertRaisesRegex(ValueError, "transport binding"):
                agent_run_history.save_run_summaries(
                    path,
                    [
                        sample_run(
                            "run_invalid_binding",
                            "2026-07-10T12:00:00-07:00",
                            transport_mode="remote",
                            connection_binding_id="local-default",
                        )
                    ],
                )
            self.assertFalse(path.exists())

    def test_persisted_summaries_are_bounded_and_redact_common_secrets(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            prompt = "api_key=very-secret-value " + ("p" * 800)
            response = "Authorization: Bearer hidden-token\n" + ("r" * 2_500)
            agent_run_history.save_run_summaries(
                path,
                [sample_run("run_private", "2026-07-10T12:00:00-07:00", prompt=prompt, response=response)],
            )

            raw = path.read_text(encoding="utf-8")
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
            path = Path(tmpdir) / "runtime" / "history.json"
            agent_run_history.save_run_summaries(
                path,
                [
                    sample_run(
                        "run_secrets",
                        "2026-07-10T12:00:00-07:00",
                        prompt=secrets,
                        response=secrets,
                    )
                ],
            )
            raw = path.read_text(encoding="utf-8")
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
            path = Path(tmpdir) / "history.json"
            agent_run_history.save_run_summaries(path, runs, retention=2)
            stored = json.loads(path.read_text(encoding="utf-8"))["runs"]

        self.assertEqual([item["id"] for item in stored], ["run_b", "run_c"])

    def test_load_marks_previously_active_run_interrupted(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            agent_run_history.save_run_summaries(
                path,
                [sample_run("run_active", "2026-07-10T12:00:00-07:00", status="running")],
            )
            runs, recovered = agent_run_history.load_run_summaries(
                path, now=lambda: "2026-07-10T14:00:00-07:00"
            )

        self.assertTrue(recovered)
        self.assertEqual(runs[0]["status"], "interrupted")
        self.assertEqual(runs[0]["completed_at"], "2026-07-10T14:00:00-07:00")
        self.assertIn("restarted", runs[0]["error"])

    def test_corrupt_and_unknown_schema_history_fall_back_to_empty(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(agent_run_history.load_run_summaries(path), ([], False))
            path.write_text(json.dumps({"schema_version": 99, "runs": []}), encoding="utf-8")
            self.assertEqual(agent_run_history.load_run_summaries(path), ([], False))

    def test_server_load_cuts_over_recovered_status_without_rewriting_legacy_source(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            path = data_dir / "private" / "console" / "agent-console-runs.json"
            agent_run_history.save_run_summaries(
                path,
                [sample_run("run_queued", "2026-07-10T12:00:00-07:00", status="queued")],
            )
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

    def test_server_load_migrates_completed_history_to_current_redaction_and_modes(self):
        legacy_secret = "github_" + "pat_1234567890abcdefghijklmnop"
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            path = data_dir / "private" / "console" / "agent-console-runs.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": agent_run_history.SCHEMA_VERSION,
                        "runs": [
                            {
                                "id": "run_completed",
                                "agent_id": "default",
                                "agent_name": "default",
                                "model": "test/model",
                                "status": "completed",
                                "session_id": None,
                                "created_at": "2026-07-10T12:00:00-07:00",
                                "updated_at": "2026-07-10T12:01:00-07:00",
                                "completed_at": "2026-07-10T12:01:00-07:00",
                                "prompt_excerpt": legacy_secret,
                                "response_excerpt": legacy_secret,
                                "error_excerpt": "",
                                "events": [],
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            path.parent.chmod(0o755)
            path.chmod(0o644)

            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ):
                self.load_runs(data_dir)
                legacy_raw = path.read_text(encoding="utf-8")
                stored = load_authoritative_run_summaries(data_dir)[0]
                file_mode = stat.S_IMODE(path.stat().st_mode)
                directory_mode = stat.S_IMODE(path.parent.stat().st_mode)

        self.assertIn(legacy_secret, legacy_raw)
        self.assertNotIn(legacy_secret, json.dumps(stored))
        self.assertIn("[REDACTED]", json.dumps(stored))
        if os.name != "nt":
            self.assertEqual(file_mode, 0o600)
            self.assertEqual(directory_mode, 0o700)
        server.AGENT_CONSOLE_RUNS.clear()

    def test_server_load_restricts_corrupt_history_without_overwriting_it(self):
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
            self.assertEqual(file_mode, 0o600)
            self.assertEqual(directory_mode, 0o700)
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
                    self.load_runs(data_dir)
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
    def test_permission_repair_rejects_hardlink_replacement_before_chmod(self):
        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as outside_dir:
            root = Path(tmpdir)
            path = root / "private" / "console" / "agent-console-runs.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}\n", encoding="utf-8")
            path.chmod(0o600)
            outside = Path(outside_dir) / "outside.json"
            outside.write_text("outside\n", encoding="utf-8")
            outside.chmod(0o644)
            real_open = agent_run_history.os.open
            replaced = False

            def racing_open(candidate, flags, *args, **kwargs):
                nonlocal replaced
                if Path(candidate) == path and not replaced:
                    replaced = True
                    path.unlink()
                    os.link(outside, path)
                return real_open(candidate, flags, *args, **kwargs)

            with patch.object(agent_run_history.os, "open", side_effect=racing_open):
                safe = agent_run_history.secure_history_permissions(
                    path, data_root=root
                )
            outside_mode = stat.S_IMODE(outside.stat().st_mode)

        self.assertFalse(safe)
        self.assertEqual(outside_mode, 0o644)

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
