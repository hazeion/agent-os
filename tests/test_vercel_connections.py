from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_registry import AgentRegistry
from agent_registry_migration import preview_agent_registry_migration
from mentat.cli import main as mentat_cli_main
from mentat_db import SCHEMA_VERSION, connect, database_path
from vercel_connections import (
    VERCEL_AGENT_CAPABILITIES,
    VERCEL_CONNECTION_ID,
    VercelConnectionError,
    confirm_configure_vercel,
    confirm_create_vercel_agent,
    confirm_disconnect_vercel,
    load_vercel_connection,
    preview_configure_vercel,
    preview_create_vercel_agent,
    preview_disconnect_vercel,
    public_vercel_connections,
    validate_provider_connections,
)


class VercelConnectionTests(unittest.TestCase):
    def cli(self, arguments: list[str]) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with redirect_stdout(output), patch("mentat.cli.sys.stdin", io.StringIO()):
            exit_code = mentat_cli_main(arguments)
        return exit_code, json.loads(output.getvalue())

    def configure(self, root: Path, **overrides):
        values = {
            "label": "Vercel",
            "auth_kind": "api_key",
            "model": "openai/gpt-5.4",
            "team_id": "team_mentat",
            "project_id": "prj_mentat",
            "connector": "github/mentat",
            "connect_scopes": ("contents:read",),
        }
        values.update(overrides)
        preview = preview_configure_vercel(root, **values)
        return confirm_configure_vercel(root, preview, preview.confirmation_token)

    def test_schema_nine_stores_one_validated_private_connection_without_credentials(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = self.configure(root)
            self.assertEqual(SCHEMA_VERSION, 11)
            self.assertEqual(record.id, VERCEL_CONNECTION_ID)
            self.assertEqual(record.revision, 1)

            connection = connect(root)
            try:
                self.assertEqual(
                    [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")],
                list(range(1, 12)),
                )
                self.assertEqual(validate_provider_connections(connection), (record,))
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(provider_connections)")
                }
                self.assertTrue({"auth_kind", "model", "team_id", "project_id"}.issubset(columns))
                self.assertFalse(
                    {"credential", "token", "secret", "api_key"}.intersection(columns)
                )
            finally:
                connection.close()

            raw = database_path(root).read_bytes()
            self.assertNotIn(b"secret-canary", raw)

    def test_preview_is_exact_and_changed_state_invalidates_confirmation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = preview_configure_vercel(
                root,
                label="Vercel",
                auth_kind="oidc",
                model="anthropic/claude-sonnet-4.6",
            )
            self.assertFalse(database_path(root).exists())
            self.assertEqual(first.public_summary()["status"], "preview")
            self.assertNotIn("credential", json.dumps(first.public_summary()))
            confirm_configure_vercel(root, first, first.confirmation_token)

            changed = preview_configure_vercel(
                root,
                label="Vercel updated",
                auth_kind="oidc",
                model="anthropic/claude-sonnet-4.6",
            )
            other = preview_configure_vercel(
                root,
                label="Vercel",
                auth_kind="oidc",
                model="openai/gpt-5.4",
            )
            confirm_configure_vercel(root, other, other.confirmation_token)
            with self.assertRaisesRegex(VercelConnectionError, "vercel.confirmation_stale"):
                confirm_configure_vercel(root, changed, changed.confirmation_token)

    def test_empty_status_is_read_only(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(
                public_vercel_connections(root, {}),
                {"schema_version": 1, "connections": [], "count": 0},
            )
            self.assertFalse(database_path(root).exists())

    def test_public_projection_is_secret_free_and_reports_configuration_state(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.configure(root)
            payload = public_vercel_connections(
                root,
                {
                    "AI_GATEWAY_API_KEY": "secret-canary-gateway",  # pragma: allowlist secret
                    "VERCEL_TOKEN": "secret-canary-management",  # pragma: allowlist secret
                    "VERCEL_OIDC_TOKEN": "secret-canary-connect",  # pragma: allowlist secret
                },
            )
            self.assertEqual(payload["count"], 1)
            public = payload["connections"][0]
            self.assertEqual(
                set(public),
                {"id", "provider", "label", "state", "model", "capabilities"},
            )
            self.assertEqual(public["state"], "configured")
            self.assertEqual(
                [item["status"] for item in public["capabilities"]],
                ["credential_present", "credential_present", "credential_present"],
            )
            encoded = json.dumps(payload)
            for canary in (
                "secret-canary-gateway",
                "secret-canary-management",
                "secret-canary-connect",
                "team_mentat",
                "prj_mentat",
                "github/mentat",
            ):
                self.assertNotIn(canary, encoded)

            needs_auth = public_vercel_connections(root, {})["connections"][0]
            self.assertEqual(needs_auth["state"], "needs_auth")
            self.assertEqual(
                [item["status"] for item in needs_auth["capabilities"]],
                ["needs_auth", "needs_auth", "needs_auth"],
            )
            unsafe = public_vercel_connections(
                root,
                {
                    "AI_GATEWAY_API_KEY": "token\nheader-injection",  # pragma: allowlist secret
                    "VERCEL_TOKEN": "tökén",  # pragma: allowlist secret
                    "VERCEL_OIDC_TOKEN": " token ",  # pragma: allowlist secret
                },
            )["connections"][0]
            self.assertEqual(unsafe["state"], "needs_auth")
            self.assertTrue(
                all(item["status"] == "needs_auth" for item in unsafe["capabilities"])
            )

    def test_create_agent_is_bound_to_connection_and_disconnect_is_isolated(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.configure(root)
            preview = preview_create_vercel_agent(root, name="Vercel Builder")
            agent = confirm_create_vercel_agent(root, preview, preview.confirmation_token)
            self.assertEqual(agent.runtime_type, "vercel")
            self.assertEqual(agent.capabilities, VERCEL_AGENT_CAPABILITIES)
            registry = AgentRegistry(
                root, supported_runtime_types=("codex", "hermes", "vercel")
            )
            binding = registry.get_runtime_binding(agent.id)
            self.assertEqual(binding.runtime_agent_ref, VERCEL_CONNECTION_ID)
            migration = preview_agent_registry_migration(root)
            self.assertEqual(migration.status, "already_converged")
            self.assertEqual(migration.destination.agent_count, 1)

            disconnect = preview_disconnect_vercel(root)
            record = confirm_disconnect_vercel(
                root, disconnect, disconnect.confirmation_token
            )
            self.assertEqual(record.state, "disconnected")
            self.assertEqual(registry.list_agents(), (agent,))
            self.assertEqual(
                public_vercel_connections(root, {})["connections"][0]["state"],
                "disconnected",
            )

    def test_disconnect_refuses_active_vercel_run_and_leaves_other_rows_unchanged(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.configure(root)
            connection = connect(root)
            try:
                connection.execute(
                    "INSERT INTO mentat_runs (id, source, runtime_type, status, "
                    "dispatch_state, created_at, updated_at) VALUES "
                    "('run_vercel_active', 'task_dispatch', 'vercel', 'running', "
                    "'accepted', '2026-08-23T00:00:00Z', '2026-08-23T00:00:00Z'), "
                    "('run_hermes_active', 'task_dispatch', 'hermes', 'running', "
                    "'accepted', '2026-08-23T00:00:00Z', '2026-08-23T00:00:00Z')"
                )
                connection.commit()
            finally:
                connection.close()
            preview = preview_disconnect_vercel(root)
            with self.assertRaisesRegex(VercelConnectionError, "vercel.active_run"):
                confirm_disconnect_vercel(root, preview, preview.confirmation_token)
            self.assertEqual(load_vercel_connection(root).state, "configured")
            connection = connect(root)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT status FROM mentat_runs WHERE id = 'run_hermes_active'"
                    ).fetchone()[0],
                    "running",
                )
            finally:
                connection.close()

    def test_validation_rejects_private_row_corruption(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.configure(root)
            connection = sqlite3.connect(database_path(root))
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA ignore_check_constraints = ON")
                connection.execute(
                    "UPDATE provider_connections SET connect_scopes_json = '[\"z\",\"a\"]'"
                )
                connection.commit()
                with self.assertRaisesRegex(VercelConnectionError, "vercel.connection_corrupt"):
                    validate_provider_connections(connection)
            finally:
                connection.close()

    def test_confirmation_is_bound_to_root_and_rechecks_stopped_server_under_lock(self):
        with TemporaryDirectory() as temporary:
            first_root = Path(temporary) / "first"
            second_root = Path(temporary) / "second"
            first_root.mkdir()
            second_root.mkdir()
            first = preview_configure_vercel(
                first_root,
                label="Vercel",
                auth_kind="oidc",
                model="openai/gpt-5.4",
            )
            second = preview_configure_vercel(
                second_root,
                label="Vercel",
                auth_kind="oidc",
                model="openai/gpt-5.4",
            )
            self.assertNotEqual(first.confirmation_token, second.confirmation_token)
            with self.assertRaisesRegex(
                VercelConnectionError,
                "vercel.confirmation_stale",
            ):
                confirm_configure_vercel(
                    second_root,
                    first,
                    first.confirmation_token,
                )
            self.assertFalse(database_path(second_root).exists())

            with patch(
                "vercel_connections.mentat_server_active",
                return_value=True,
            ):
                with self.assertRaisesRegex(
                    VercelConnectionError,
                    "vercel.server_running",
                ):
                    confirm_configure_vercel(
                        first_root,
                        first,
                        first.confirmation_token,
                    )
            self.assertFalse(database_path(first_root).exists())

            self.configure(first_root)
            agent_preview = preview_create_vercel_agent(
                first_root,
                name="Race-safe Agent",
            )
            disconnect_preview = preview_disconnect_vercel(first_root)
            for operation in (
                lambda: confirm_create_vercel_agent(
                    first_root,
                    agent_preview,
                    agent_preview.confirmation_token,
                ),
                lambda: confirm_disconnect_vercel(
                    first_root,
                    disconnect_preview,
                    disconnect_preview.confirmation_token,
                ),
            ):
                with patch(
                    "vercel_connections.mentat_server_active",
                    return_value=True,
                ):
                    with self.assertRaisesRegex(
                        VercelConnectionError,
                        "vercel.server_running",
                    ):
                        operation()
            self.assertEqual(load_vercel_connection(first_root).state, "configured")

    def test_cli_status_preview_confirm_create_and_disconnect_are_exact(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = ["--data-dir", str(root)]

            exit_code, status = self.cli(["vercel", "status", *runtime])
            self.assertEqual(exit_code, 0)
            self.assertEqual(status["connections"], [])
            self.assertFalse(database_path(root).exists())

            configure = [
                "vercel",
                "configure",
                "--auth",
                "oidc",
                "--model",
                "openai/gpt-5.4",
                *runtime,
            ]
            exit_code, preview = self.cli(configure)
            self.assertEqual(exit_code, 3)
            self.assertEqual(preview["action"], "configure")
            self.assertFalse(database_path(root).exists())
            with patch("mentat.cli._connection_server_running", return_value=False):
                exit_code, configured = self.cli(
                    [*configure, "--confirm", str(preview["confirmation_token"])]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(configured["status"], "configured")
            self.assertEqual(
                set(configured["connection"]),
                {"id", "provider", "label", "state", "model", "capabilities"},
            )

            create = [
                "vercel",
                "create-agent",
                "--name",
                "CLI Vercel Agent",
                *runtime,
            ]
            exit_code, agent_preview = self.cli(create)
            self.assertEqual(exit_code, 3)
            with patch("mentat.cli._connection_server_running", return_value=False):
                exit_code, created = self.cli(
                    [*create, "--confirm", str(agent_preview["confirmation_token"])]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(created["agent"]["runtime_type"], "vercel")

            disconnect = ["vercel", "disconnect", *runtime]
            exit_code, disconnect_preview = self.cli(disconnect)
            self.assertEqual(exit_code, 3)
            token = str(disconnect_preview["confirmation_token"])
            with patch("mentat.cli._connection_server_running", return_value=True):
                exit_code, blocked = self.cli([*disconnect, "--confirm", token])
            self.assertEqual(exit_code, 2)
            self.assertEqual(blocked["error_code"], "vercel.server_running")
            self.assertEqual(load_vercel_connection(root).state, "configured")
            with patch("mentat.cli._connection_server_running", return_value=False):
                exit_code, disconnected = self.cli([*disconnect, "--confirm", token])
            self.assertEqual(exit_code, 0)
            self.assertEqual(disconnected["status"], "disconnected")

    def test_cli_readiness_test_runs_only_after_confirmation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.configure(root, auth_kind="oidc")
            command = [
                "vercel",
                "test",
                "gateway",
                "--data-dir",
                str(root),
            ]
            exit_code, preview = self.cli(command)
            self.assertEqual(exit_code, 3)
            with (
                patch("mentat.cli._connection_server_running", return_value=False),
                patch(
                    "vercel_runtime.VercelRuntime.test_readiness",
                    return_value={
                        "schema_version": 1,
                        "status": "ready",
                        "capability": "gateway",
                    },
                ) as readiness,
            ):
                exit_code, result = self.cli(
                    [*command, "--confirm", str(preview["confirmation_token"])]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(result["capability"], "gateway")
            readiness.assert_called_once_with()

            with (
                patch("mentat.cli._connection_server_running", return_value=False),
                patch(
                    "vercel_connections.mentat_server_active",
                    return_value=True,
                ),
                patch("vercel_runtime.VercelRuntime.test_readiness") as raced,
            ):
                exit_code, blocked = self.cli(
                    [*command, "--confirm", str(preview["confirmation_token"])]
                )
            self.assertEqual(exit_code, 2)
            self.assertEqual(blocked["error_code"], "vercel.server_running")
            raced.assert_not_called()


if __name__ == "__main__":
    unittest.main()
