from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from agent_registry import AgentRegistry, AgentRegistryUnavailableError, INTERACTIVE_AGENT_CAPABILITIES
from agent_setup import AgentSetupError, AgentSetupService, LocalHermesSetup
from mentat.local_bridge import bridge_agent_setup
from private_state import history_path
import server
from tests.sqlite_authority_support import ensure_run_sqlite_authority


class AgentSetupTests(unittest.TestCase):
    def service(self, root):
        ensure_run_sqlite_authority(root, history_path(root))
        registry = AgentRegistry(root, supported_runtime_types=("hermes", "codex", "vercel"))
        return AgentSetupService(root, registry, Mock(return_value=LocalHermesSetup("available", "private-configuration-digest")))

    def test_exact_creation_has_private_binding_safe_caps_and_honest_recovery(self):
        with TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            self.assertEqual(service.check(), {"schema_version": 1, "state": "available", "agent": None})
            preview = service.preview("Research")
            self.assertEqual(service.registry.list_agents(), ())
            result = service.confirm("Research", preview["confirmation_id"])
            stored = service.registry.list_agents()
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].capabilities, frozenset(INTERACTIVE_AGENT_CAPABILITIES))
            self.assertEqual(service.registry.get_runtime_binding(stored[0].id).runtime_agent_ref, "default")
            self.assertEqual(result["agent"], {"id": stored[0].id, "name": "Research"})
            with self.assertRaisesRegex(AgentSetupError, "conflict"):
                service.confirm("Research", preview["confirmation_id"])
            service.probe.side_effect = AssertionError("Existing binding requires no runtime probe")
            self.assertEqual(service.check()["agent"], result["agent"])
            self.assertEqual(service.check()["state"], "already_configured")

    def test_changed_name_configuration_and_registry_require_new_preview(self):
        with TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            preview = service.preview("Research")
            with self.assertRaisesRegex(AgentSetupError, "conflict"):
                service.confirm("Other", preview["confirmation_id"])
            service.probe.return_value = LocalHermesSetup("available", "changed")
            with self.assertRaisesRegex(AgentSetupError, "conflict"):
                service.confirm("Research", preview["confirmation_id"])
            preview = service.preview("Research")
            service.registry.create_agent(agent_id="agent_other", name="Other", runtime_config_id="config_other", runtime_type="hermes", runtime_agent_ref="other", capabilities=("run.start",))
            with self.assertRaisesRegex(AgentSetupError, "conflict"):
                service.confirm("Research", preview["confirmation_id"])

    def test_concurrent_confirmation_creates_at_most_one_canonical_identity(self):
        with TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            preview = service.preview("Research")
            def confirm():
                try:
                    return service.confirm("Research", preview["confirmation_id"])
                except AgentSetupError as exc:
                    return exc.code
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: confirm(), range(2)))
            self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
            self.assertIn("conflict", results)
            self.assertEqual(len(service.registry.list_agents()), 1)

    def test_missing_remote_unconfigured_and_unknown_never_create(self):
        with TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            for state in ("hermes_missing", "hermes_unconfigured", "remote_selected", "unavailable"):
                service.probe.return_value = LocalHermesSetup(state)
                self.assertEqual(service.check()["state"], state)
                with self.assertRaisesRegex(AgentSetupError, "unavailable"):
                    service.preview("Research")
            self.assertEqual(service.registry.list_agents(), ())
            for name in ("", " padded", "a\nname", "a\u202ename", "x" * 121, None):
                with self.assertRaisesRegex(AgentSetupError, "invalid"):
                    service.preview(name)

    def test_bridge_rejects_private_input_and_projects_only_fixed_shapes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.service(root)
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root), patch.object(server, "_local_hermes_agent_setup_target", return_value=LocalHermesSetup("available", "fixture")):
                for action, body in (("check", {"runtime_type": "codex"}), ("preview", {"name": "Test", "runtime_agent_ref": "other"}), ("confirm", {"name": "Test", "confirmation_id": "a" * 64, "confirmed": False})):
                    self.assertEqual(bridge_agent_setup(action, body)[1], 400)
                preview, code = bridge_agent_setup("preview", {"name": "Test"})
                self.assertEqual(code, 200)
                self.assertEqual(set(preview), {"schema_version", "runtime", "service", "status", "name", "confirmation_id"})
                result, code = bridge_agent_setup("confirm", {"name": "Test", "confirmation_id": preview["confirmation_id"], "confirmed": True})
                self.assertEqual(code, 200)
                self.assertEqual(set(result["agent"]), {"id", "name"})
        with patch.object(server, "mentat_agent_setup", return_value=({"schema_version": 1, "agent": {"id": "agent_test", "name": "Test", "runtime_agent_ref": "default"}}, 200)):
            self.assertEqual(bridge_agent_setup("confirm", {"name": "Test"})[1], 503)

    def test_check_and_preview_do_not_initialize_an_empty_data_root(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                self.assertEqual(server.mentat_agent_setup("check", {})[1], 503)
                self.assertEqual(server.mentat_agent_setup("preview", {"name": "Test"})[1], 503)
            self.assertEqual(list(root.rglob("*.sqlite3")), [])

    def test_post_commit_readback_failure_is_recovered_by_existing_binding_check(self):
        with TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            preview = service.preview("Research")
            with patch.object(service.registry, "list_agent_records", side_effect=AgentRegistryUnavailableError("unavailable")):
                with self.assertRaises(AgentRegistryUnavailableError):
                    service.confirm("Research", preview["confirmation_id"])
            self.assertEqual(service.check()["state"], "already_configured")
            self.assertEqual(len(service.registry.list_agents()), 1)

    def test_registry_capacity_stays_bounded_before_offering_creation(self):
        with TemporaryDirectory() as temporary:
            service = self.service(Path(temporary))
            for index in range(128):
                service.registry.create_agent(agent_id=f"agent_{index}", name=f"Agent {index}", runtime_config_id=f"config_{index}", runtime_type="hermes", runtime_agent_ref=f"profile_{index}", capabilities=("run.start",))
            self.assertEqual(service.check()["state"], "registry_full")
            with self.assertRaisesRegex(AgentSetupError, "unavailable"):
                service.preview("Research")
            service.probe.assert_not_called()

    def test_explicit_target_probe_is_local_fixed_and_excludes_codex_readiness(self):
        with patch.object(server, "load_remote_hermes_connection", return_value=Mock(mode="remote")), patch.object(server, "hermes_command_path") as command:
            self.assertEqual(server._local_hermes_agent_setup_target().state, "remote_selected")
            command.assert_not_called()
        with patch.object(server, "load_remote_hermes_connection", return_value=Mock(mode="local")), patch.object(server, "hermes_command_path", return_value=None):
            self.assertEqual(server._local_hermes_agent_setup_target().state, "hermes_missing")
        with patch.object(server, "load_remote_hermes_connection", return_value=Mock(mode="local")), patch.object(server, "hermes_command_path", return_value="private-command"), patch.object(server, "hermes_python_path", return_value="private-python"), patch.object(server, "discover_hermes_profiles", return_value={"status": "available", "profiles": [{"id": "default", "is_default": True, "provider": "configured", "model": "configured"}]}) as discover, patch.object(server.CODEX_RUNTIME, "validate_agent_binding", side_effect=AssertionError("Never probe Codex")):
            result = server._local_hermes_agent_setup_target()
            self.assertEqual(result.state, "available")
            self.assertEqual(len(result.fingerprint), 64)
            self.assertEqual(discover.call_args.kwargs["timeout"], 5)

    def test_remote_selection_is_explained_even_when_the_local_binding_exists(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self.service(root)
            preview = service.preview("Research")
            service.confirm("Research", preview["confirmation_id"])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root), patch.object(server, "load_remote_hermes_connection", return_value=Mock(mode="remote")):
                result, status = server.mentat_agent_setup("check", {})
                self.assertEqual((status, result["state"], result["agent"]), (200, "remote_selected", None))
