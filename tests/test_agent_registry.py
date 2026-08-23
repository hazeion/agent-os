from __future__ import annotations

import json
import os
from dataclasses import replace
from email.message import Message
from io import BytesIO
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import agent_registry
from agent_registry import (
    AgentRegistry,
    AgentRegistryConflict,
    AgentRegistryError,
    AgentRegistryLimitError,
    AgentRegistryUnavailableError,
    AgentRegistryValidationError,
    MAX_AGENTS,
    connect_registry,
    public_agent_record,
    registry_database_path,
)
from mentat_db import SCHEMA_VERSION, connect, database_path
from private_console_unit import (
    PrivateConsoleUnitError,
    capture_private_console_unit,
    materialize_private_console_unit,
    validate_private_console_unit,
)
import server


class AgentRegistryTests(unittest.TestCase):
    def registry(self, root: Path) -> AgentRegistry:
        return AgentRegistry(root, supported_runtime_types={"hermes"})

    def create_researcher(self, registry: AgentRegistry):
        return registry.create_agent(
            agent_id="agent_researcher",
            name="Researcher",
            runtime_config_id="runtime_config_researcher",
            runtime_type="hermes",
            runtime_agent_ref="researcher-main",
            capabilities=("research.web", "browser-use"),
        )

    def test_registry_uses_current_core_database_with_fresh_authority(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            connection = connect_registry(root)
            try:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                version = int(
                    connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                )
                foreign_keys = connection.execute(
                    "PRAGMA foreign_key_list(mentat_agents)"
                ).fetchall()
                connected_path = Path(
                    connection.execute("PRAGMA database_list").fetchone()[2]
                )
            finally:
                connection.close()

            self.assertEqual(version, SCHEMA_VERSION)
            self.assertIn("mentat_agents", tables)
            self.assertIn("agent_runtime_configs", tables)
            self.assertTrue(
                any(
                    row[2] == "agent_runtime_configs"
                    and row[3] == "runtime_config_id"
                    for row in foreign_keys
                )
            )
            self.assertFalse(registry_database_path(root).exists())
            self.assertEqual(connected_path.resolve(), database_path(root).resolve())

    @unittest.skipIf(os.name == "nt", "POSIX link and mode contract")
    def test_registry_rejects_unsafe_core_database_sidecars(self):
        cases = ("symlink", "hardlink", "wrong_mode")
        for kind in cases:
            with self.subTest(kind=kind), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                connection = connect_registry(root)
                connection.close()
                path = database_path(root)
                sidecar = Path(f"{path}-wal" if kind != "wrong_mode" else f"{path}-shm")
                decoy = root / "decoy"
                decoy.write_bytes(b"decoy")
                decoy.chmod(0o600)
                if kind == "symlink":
                    sidecar.symlink_to(decoy)
                elif kind == "hardlink":
                    os.link(decoy, sidecar)
                else:
                    sidecar.write_bytes(b"cache")
                    sidecar.chmod(0o644)
                with self.assertRaises(AgentRegistryUnavailableError):
                    connect_registry(root)

    def test_registry_identity_continuity_ignores_transient_sidecar_identity(self):
        path = Path("agent-registry.sqlite3")
        wal_path = Path(f"{path}-wal")

        self.assertTrue(
            agent_registry._same_primary_database(
                {path: (1, 10), wal_path: (1, 11)},
                {path: (1, 10), wal_path: (1, 12)},
                path=path,
            )
        )
        self.assertFalse(
            agent_registry._same_primary_database(
                {path: (1, 10)},
                {path: (1, 12)},
                path=path,
            )
        )


    def test_create_reopen_and_private_snapshot_preserve_agent_binding(self):
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            agent = self.create_researcher(self.registry(source))

            reopened = self.registry(source)
            self.assertEqual(reopened.list_agents(), (agent,))
            binding = reopened.get_runtime_binding(agent.id)
            self.assertEqual(binding.runtime_type, "hermes")
            self.assertEqual(binding.runtime_agent_ref, "researcher-main")

            unit = capture_private_console_unit(source)
            restored = Path(tmpdir) / "restored"
            (restored / "private").mkdir(parents=True, mode=0o700)
            stage = materialize_private_console_unit(
                restored,
                unit,
                restored / "private" / "restore-stage",
            )
            stage.rename(restored / "private" / "console")

            restored_registry = self.registry(restored)
            self.assertEqual(restored_registry.list_agents(), (agent,))
            self.assertEqual(
                restored_registry.get_runtime_binding(agent.id).runtime_agent_ref,
                "researcher-main",
            )

    def test_conflicts_and_invalid_values_leave_no_partial_rows(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            registry = self.registry(root)
            self.create_researcher(registry)

            attempts = (
                {
                    "agent_id": "agent_researcher",
                    "name": "Duplicate ID",
                    "runtime_config_id": "runtime_config_unused_1",
                    "runtime_type": "hermes",
                    "runtime_agent_ref": "other-profile",
                    "capabilities": (),
                },
                {
                    "agent_id": "agent_other",
                    "name": "Duplicate binding",
                    "runtime_config_id": "runtime_config_unused_2",
                    "runtime_type": "hermes",
                    "runtime_agent_ref": "researcher-main",
                    "capabilities": (),
                },
            )
            for values in attempts:
                with self.subTest(values=values):
                    with self.assertRaises(AgentRegistryConflict):
                        registry.create_agent(**values)

            invalid_attempts = (
                {"runtime_type": "codex", "runtime_agent_ref": "codex-main"},
                {"runtime_type": "hermes", "runtime_agent_ref": "../../profile"},
                {"runtime_type": "hermes", "runtime_agent_ref": "profile", "capabilities": "git"},
            )
            for index, override in enumerate(invalid_attempts, start=1):
                values = {
                    "agent_id": f"agent_invalid_{index}",
                    "name": "Invalid",
                    "runtime_config_id": f"runtime_config_invalid_{index}",
                    "runtime_type": "hermes",
                    "runtime_agent_ref": "profile",
                    "capabilities": (),
                    **override,
                }
                with self.subTest(values=values):
                    with self.assertRaises(AgentRegistryValidationError):
                        registry.create_agent(**values)

            connection = sqlite3.connect(database_path(root))
            try:
                agent_count = connection.execute(
                    "SELECT COUNT(*) FROM mentat_agents"
                ).fetchone()[0]
                config_count = connection.execute(
                    "SELECT COUNT(*) FROM agent_runtime_configs"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual((agent_count, config_count), (1, 1))

    def test_transactional_agent_limit_bounds_create_and_list_under_concurrency(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for index in range(MAX_AGENTS - 1):
                self.registry(root).create_agent(
                    agent_id=f"agent_{index}",
                    name=f"Agent {index}",
                    runtime_config_id=f"runtime_config_{index}",
                    runtime_type="hermes",
                    runtime_agent_ref=f"profile_{index}",
                    capabilities=(),
                )

            outcomes: list[str] = []
            outcome_lock = Lock()

            def create_last(index: int) -> None:
                try:
                    self.registry(root).create_agent(
                        agent_id=f"agent_final_{index}",
                        name=f"Final {index}",
                        runtime_config_id=f"runtime_config_final_{index}",
                        runtime_type="hermes",
                        runtime_agent_ref=f"profile_final_{index}",
                        capabilities=(),
                    )
                    result = "created"
                except AgentRegistryLimitError:
                    result = "limited"
                with outcome_lock:
                    outcomes.append(result)

            workers = [Thread(target=create_last, args=(index,)) for index in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)

            self.assertEqual(sorted(outcomes), ["created", "limited"])
            self.assertEqual(len(self.registry(root).list_agents()), MAX_AGENTS)

    def test_public_record_omits_private_runtime_reference(self):
        with TemporaryDirectory() as tmpdir:
            registry = self.registry(Path(tmpdir))
            agent = self.create_researcher(registry)
            record = public_agent_record(agent)
            encoded = json.dumps(record, sort_keys=True)

            self.assertEqual(
                record,
                {
                    "id": "agent_researcher",
                    "name": "Researcher",
                    "runtime_type": "hermes",
                    "runtime_config_id": "runtime_config_researcher",
                    "capabilities": ["browser-use", "research.web"],
                },
            )
            self.assertNotIn("researcher-main", encoded)
            self.assertNotIn("runtime_agent_ref", encoded)

    def test_create_and_list_api_are_separate_from_heartbeat_agents(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            heartbeat = root / "agents.json"
            heartbeat.write_text(
                json.dumps([{"id": "heartbeat-only", "status": "working"}]),
                encoding="utf-8",
            )
            payload = {
                "name": "Researcher",
                "runtime_type": "hermes",
                "runtime_agent_ref": "private-profile-canary",
                "capabilities": ["research.web"],
            }
            with patch.object(server, "DATA_DIR", root):
                created, created_status = server.create_mentat_agent(payload)
                listed = server.mentat_agents_payload()

            self.assertEqual(created_status, 201)
            self.assertTrue(created["ok"])
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["agents"], [created["agent"]])
            self.assertNotIn("private-profile-canary", json.dumps(created))
            self.assertNotIn("private-profile-canary", json.dumps(listed))
            self.assertEqual(
                json.loads(heartbeat.read_text(encoding="utf-8")),
                [{"id": "heartbeat-only", "status": "working"}],
            )

    def test_api_rejects_unknown_fields_unsupported_runtime_and_duplicate_binding(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            valid = {
                "name": "Researcher",
                "runtime_type": "hermes",
                "runtime_agent_ref": "researcher-main",
                "capabilities": ["research.web"],
            }
            attempts = (
                ({**valid, "api_key": "must-not-be-accepted"}, 400),  # pragma: allowlist secret
                ({**valid, "runtime_type": "unsupported"}, 400),
                ({**valid, "runtime_type": "codex"}, 400),
                (
                    {
                        **valid,
                        "runtime_type": "vercel",
                        "runtime_agent_ref": "connection_vercel",
                    },
                    400,
                ),
                ({**valid, "runtime_agent_ref": "../profile"}, 400),
            )
            with patch.object(server, "DATA_DIR", root):
                for payload, expected_status in attempts:
                    with self.subTest(payload=payload):
                        response, status = server.create_mentat_agent(payload)
                        self.assertEqual(status, expected_status)
                        self.assertIn("error", response)

                created, status = server.create_mentat_agent(valid)
                duplicate, duplicate_status = server.create_mentat_agent(valid)
                listed = server.mentat_agents_payload()

            self.assertEqual(status, 201)
            self.assertEqual(duplicate_status, 409)
            self.assertIn("error", duplicate)
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["agents"], [created["agent"]])

    def test_codex_agent_requires_the_fixed_available_binding(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = server.CodexRuntime(
                workspace_root=root,
                command=server.codex_app_server_command(
                    str((root / "codex.exe").resolve())
                ),
                client=Mock(
                    request=Mock(
                        return_value={
                            "account": {"type": "chatgpt"},
                            "requiresOpenaiAuth": True,
                        }
                    ),
                    close=Mock(),
                ),
            )
            registry = server.AgentRuntimeRegistry((server.HERMES_RUNTIME, runtime))
            payload = {
                "name": "Local Codex",
                "runtime_type": "codex",
                "runtime_agent_ref": "default",
                "capabilities": ["run.start", "run.status"],
            }
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "AGENT_RUNTIME_REGISTRY", registry
            ):
                created, status = server.create_mentat_agent(payload)
                listed = server.mentat_agents_payload()

        self.assertEqual(status, 201)
        self.assertEqual(created["agent"]["runtime_type"], "codex")
        self.assertEqual(listed["agents"], [created["agent"]])
        self.assertNotIn("runtime_agent_ref", json.dumps(created))

    def test_signed_out_codex_blocks_creation_without_mutating_the_registry(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            client = Mock(
                request=Mock(
                    return_value={"account": None, "requiresOpenaiAuth": True}
                ),
                close=Mock(),
            )
            runtime = server.CodexRuntime(
                workspace_root=root,
                command=server.codex_app_server_command(
                    str((root / "codex.exe").resolve())
                ),
                client=client,
            )
            runtimes = server.AgentRuntimeRegistry(
                (server.HERMES_RUNTIME, runtime)
            )
            payload = {
                "name": "Signed-out Codex",
                "runtime_type": "codex",
                "runtime_agent_ref": "default",
                "capabilities": ["run.start"],
            }
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "AGENT_RUNTIME_REGISTRY", runtimes
            ):
                rejected, status = server.create_mentat_agent(payload)
                listed = server.mentat_agents_payload()

        self.assertEqual(status, 400)
        self.assertIn("error", rejected)
        self.assertEqual(listed["agents"], [])

    def test_agent_registry_reads_do_not_probe_the_optional_codex_runtime(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            client = Mock(request=Mock(side_effect=AssertionError("unexpected probe")))
            runtime = server.CodexRuntime(
                workspace_root=root,
                command=server.codex_app_server_command(
                    str((root / "codex.exe").resolve())
                ),
                client=client,
            )
            runtimes = server.AgentRuntimeRegistry(
                (server.HERMES_RUNTIME, runtime)
            )
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "AGENT_RUNTIME_REGISTRY", runtimes
            ):
                listed = server.mentat_agents_payload()

        self.assertEqual(listed["agents"], [])
        client.request.assert_not_called()

    def test_unavailable_codex_blocks_creation_but_preserves_registry_reads(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stored = AgentRegistry(
                root, supported_runtime_types={"codex", "hermes"}
            ).create_agent(
                agent_id="agent_existing_codex",
                name="Existing Codex",
                runtime_config_id="runtime_config_existing_codex",
                runtime_type="codex",
                runtime_agent_ref="default",
                capabilities=(),
            )
            unavailable = server.CodexRuntime(
                workspace_root=root,
                command=None,
            )
            runtimes = server.AgentRuntimeRegistry(
                (server.HERMES_RUNTIME, unavailable)
            )
            payload = {
                "name": "Unavailable Codex",
                "runtime_type": "codex",
                "runtime_agent_ref": "default",
                "capabilities": [],
            }
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "AGENT_RUNTIME_REGISTRY", runtimes
            ):
                listed = server.mentat_agents_payload()
                rejected, status = server.create_mentat_agent(payload)

        self.assertEqual(listed["agents"], [public_agent_record(stored)])
        self.assertEqual(status, 400)
        self.assertIn("error", rejected)

    def test_private_snapshot_round_trips_a_codex_binding(self):
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            registry = AgentRegistry(
                source, supported_runtime_types={"codex", "hermes"}
            )
            agent = registry.create_agent(
                agent_id="agent_codex",
                name="Local Codex",
                runtime_config_id="runtime_config_codex",
                runtime_type="codex",
                runtime_agent_ref="default",
                capabilities=("run.start", "run.status"),
            )
            unit = capture_private_console_unit(source)
            restored = Path(tmpdir) / "restored"
            (restored / "private").mkdir(parents=True, mode=0o700)
            stage = materialize_private_console_unit(
                restored,
                unit,
                restored / "private" / "restore-stage",
            )
            stage.rename(restored / "private" / "console")
            reopened = AgentRegistry(
                restored, supported_runtime_types={"codex", "hermes"}
            )
            restored_agents = reopened.list_agents()
            binding = reopened.get_runtime_binding(agent.id)

        self.assertEqual(restored_agents, (agent,))
        self.assertEqual(binding.runtime_type, "codex")
        self.assertEqual(binding.runtime_agent_ref, "default")

    def test_private_snapshot_rejects_unusable_codex_bindings(self):
        corruptions = (
            "UPDATE agent_runtime_configs SET runtime_agent_ref = 'other'",
            "UPDATE mentat_agents SET capabilities_json = "
            "'[\"provider.login\",\"run.start\"]'",
        )
        for index, statement in enumerate(corruptions):
            with self.subTest(statement=statement), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir) / "source"
                registry = AgentRegistry(
                    root, supported_runtime_types={"codex", "hermes"}
                )
                registry.create_agent(
                    agent_id="agent_codex",
                    name="Local Codex",
                    runtime_config_id="runtime_config_codex",
                    runtime_type="codex",
                    runtime_agent_ref="default",
                    capabilities=("run.start", "run.status"),
                )
                unit = capture_private_console_unit(root)

                live = sqlite3.connect(database_path(root))
                try:
                    live.execute(statement)
                    live.commit()
                finally:
                    live.close()
                with self.assertRaises(PrivateConsoleUnitError):
                    capture_private_console_unit(root)

                snapshot = Path(tmpdir) / f"snapshot-{index}.sqlite3"
                snapshot.write_bytes(unit.database_raw)
                saved = sqlite3.connect(snapshot)
                try:
                    saved.execute(statement)
                    saved.commit()
                finally:
                    saved.close()
                with self.assertRaises(PrivateConsoleUnitError):
                    validate_private_console_unit(
                        replace(unit, database_raw=snapshot.read_bytes())
                    )

    def test_api_blocks_creation_while_private_restore_is_reserved(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload = {
                "name": "Researcher",
                "runtime_type": "hermes",
                "runtime_agent_ref": "researcher-main",
                "capabilities": [],
            }
            with patch.object(server, "DATA_DIR", root), patch.object(
                server,
                "restore_status_under_lock",
                return_value="invalid",
            ):
                response, status = server.create_mentat_agent(payload)

            self.assertEqual(status, 503)
            self.assertIn("unavailable", response["error"])
            self.assertFalse(database_path(root).exists())

    def test_routes_use_new_orchestration_path_without_replacing_legacy_agents(self):
        self.assertNotIn("/api/orchestration/agents", server.API_ROUTES)
        self.assertIs(server.API_ROUTES["/api/agents"], server.agents_payload)
        matches = [
            (pattern, handler, accepts_payload)
            for pattern, handler, accepts_payload in server.POST_ROUTES
            if pattern.fullmatch("/api/orchestration/agents")
        ]
        self.assertEqual(len(matches), 1)
        self.assertIs(matches[0][1], server.create_mentat_agent)
        self.assertTrue(matches[0][2])

    def _handler(self, *, body: bytes = b"", origin: str | None = None):
        instance = object.__new__(server.Handler)
        instance.client_address = ("127.0.0.1", 54123)
        instance.server = SimpleNamespace(server_port=8890)
        headers = Message()
        headers["Host"] = "127.0.0.1:8890"
        headers["Origin"] = origin or "http://127.0.0.1:8890"
        headers["Sec-Fetch-Site"] = "same-origin"
        if body:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        instance.headers = headers
        instance.rfile = BytesIO(body)
        instance.wfile = BytesIO()
        instance.send_response = Mock()
        instance.send_header = Mock()
        instance.end_headers = Mock()
        instance.log_internal_error = Mock()
        return instance

    def test_http_create_and_list_compose_routing_status_and_private_projection(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            body = json.dumps(
                {
                    "name": "Researcher",
                    "runtime_type": "hermes",
                    "runtime_agent_ref": "private-http-canary",
                    "capabilities": ["research.web"],
                }
            ).encode("utf-8")
            post = self._handler(body=body)
            post.path = "/api/orchestration/agents"
            with patch.object(server, "DATA_DIR", root):
                post.do_POST()
            self.assertEqual(post.send_response.call_args.args, (201,))
            created = json.loads(post.wfile.getvalue())
            self.assertTrue(created["ok"])
            self.assertNotIn("private-http-canary", post.wfile.getvalue().decode())

            get = self._handler()
            get.path = "/api/orchestration/agents"
            with patch.object(server, "DATA_DIR", root):
                get.do_GET()
            self.assertEqual(get.send_response.call_args.args, (200,))
            listed = json.loads(get.wfile.getvalue())
            self.assertEqual(listed["count"], 1)
            self.assertNotIn("private-http-canary", get.wfile.getvalue().decode())

    def test_http_boundary_rejects_malformed_cross_origin_and_duplicate_requests(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            malformed = self._handler(body=b"{")
            malformed.path = "/api/orchestration/agents"
            with patch.object(server, "DATA_DIR", root):
                malformed.do_POST()
            self.assertEqual(malformed.send_response.call_args.args, (400,))

            payload = json.dumps(
                {
                    "name": "Researcher",
                    "runtime_type": "hermes",
                    "runtime_agent_ref": "researcher-main",
                }
            ).encode("utf-8")
            rejected = self._handler(body=payload, origin="https://attacker.example")
            rejected.path = "/api/orchestration/agents"
            with patch.object(server, "DATA_DIR", root):
                rejected.do_POST()
            self.assertEqual(rejected.send_response.call_args.args, (403,))
            self.assertFalse(registry_database_path(root).exists())
            self.assertFalse(database_path(root).exists())

            statuses = []
            for _ in range(2):
                request = self._handler(body=payload)
                request.path = "/api/orchestration/agents"
                with patch.object(server, "DATA_DIR", root):
                    request.do_POST()
                statuses.append(request.send_response.call_args.args[0])
            self.assertEqual(statuses, [201, 409])

    def test_http_create_and_list_report_restore_unavailability(self):
        payload = json.dumps(
            {
                "name": "Researcher",
                "runtime_type": "hermes",
                "runtime_agent_ref": "researcher-main",
            }
        ).encode("utf-8")
        post = self._handler(body=payload)
        post.path = "/api/orchestration/agents"
        get = self._handler()
        get.path = "/api/orchestration/agents"
        with patch.object(server, "restore_status_under_lock", return_value="reserved"):
            post.do_POST()
            get.do_GET()
        self.assertEqual(post.send_response.call_args.args, (503,))
        self.assertEqual(get.send_response.call_args.args, (503,))

    def test_http_list_maps_malformed_registry_to_one_redacted_500_response(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            connection = connect_registry(root)
            connection.close()
            path = database_path(root)
            path.write_bytes(b"not a sqlite database")
            if os.name != "nt":
                path.chmod(0o600)
            request = self._handler()
            request.path = "/api/orchestration/agents"
            with patch.object(server, "DATA_DIR", root):
                request.do_GET()
            self.assertEqual(request.send_response.call_args.args, (500,))
            self.assertEqual(request.send_response.call_count, 1)
            self.assertNotIn("sqlite", request.wfile.getvalue().decode().lower())

    def test_http_list_maps_sqlite_operational_failure_to_503(self):
        request = self._handler()
        request.path = "/api/orchestration/agents"
        with patch.object(
            agent_registry.sqlite3,
            "connect",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            request.do_GET()
        self.assertEqual(request.send_response.call_args.args, (503,))
        self.assertEqual(request.send_response.call_count, 1)
        self.assertNotIn("locked", request.wfile.getvalue().decode().lower())

    def test_registry_translates_operational_errors_to_unavailable(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            agent_registry.sqlite3,
            "connect",
            side_effect=sqlite3.OperationalError("database is busy"),
        ):
            with self.assertRaises(AgentRegistryUnavailableError):
                connect_registry(Path(tmpdir))

    def test_list_fails_closed_for_semantically_corrupt_registry(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.create_researcher(self.registry(root))
            connection = sqlite3.connect(database_path(root))
            try:
                connection.execute(
                    "UPDATE mentat_agents SET capabilities_json = '{}' WHERE id = 'agent_researcher'"
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(AgentRegistryError):
                self.registry(root).list_agents()

    def test_list_fails_closed_for_changed_embedded_agent_schema(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.create_researcher(self.registry(root))
            connection = sqlite3.connect(database_path(root))
            try:
                connection.execute("DROP INDEX idx_mentat_agents_name")
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(
                AgentRegistryError,
                "agent_registry.schema_invalid",
            ):
                self.registry(root).list_agents()

    def test_private_snapshot_rejects_registry_relationship_and_value_corruption(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "source"
            self.create_researcher(self.registry(root))
            unit = capture_private_console_unit(root)
            corruptions = (
                "DELETE FROM agent_runtime_configs WHERE id = 'runtime_config_researcher'",
                "INSERT INTO agent_runtime_configs VALUES "
                "('runtime_config_orphan','hermes','orphan',1,1)",
                "UPDATE mentat_agents SET capabilities_json = '{}'",
                "UPDATE agent_runtime_configs SET runtime_type = 'unsupported'",
                "UPDATE mentat_agents SET updated_at = 'not-a-number'",
                "CREATE TABLE unexpected_private_values (value TEXT)",
            )
            for index, statement in enumerate(corruptions):
                with self.subTest(statement=statement):
                    path = Path(tmpdir) / f"corrupt-{index}.sqlite3"
                    path.write_bytes(unit.database_raw)
                    connection = sqlite3.connect(path)
                    try:
                        connection.execute(statement)
                        connection.commit()
                    finally:
                        connection.close()
                    with self.assertRaises(PrivateConsoleUnitError):
                        validate_private_console_unit(
                            replace(unit, database_raw=path.read_bytes())
                        )


if __name__ == "__main__":
    unittest.main()
