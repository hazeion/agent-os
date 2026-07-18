from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import data_layout
import runtime_config
import server


class RuntimeConfigTests(unittest.TestCase):
    def test_ipv6_loopback_uses_ipv6_server_and_bracketed_browser_url(self):
        self.assertIs(server.server_class_for_host("::1"), server.IPv6ThreadingHTTPServer)
        self.assertEqual(server.IPv6ThreadingHTTPServer.address_family, socket.AF_INET6)
        self.assertEqual(server.browser_url("::1", 8888), "http://[::1]:8888")
        self.assertIs(server.server_class_for_host("127.0.0.1"), server.ThreadingHTTPServer)

    def test_repo_defaults_include_toml_runtime_config(self):
        original_local_config = runtime_config.LOCAL_CONFIG_FILE
        original_legacy_local_config = runtime_config.LEGACY_LOCAL_CONFIG_FILE
        try:
            runtime_config.LOCAL_CONFIG_FILE = runtime_config.BASE_DIR / "mentat.local.test-missing.toml"
            runtime_config.LEGACY_LOCAL_CONFIG_FILE = runtime_config.BASE_DIR / "mentat.previous-local.test-missing.toml"
            config = server.load_app_config()
        finally:
            runtime_config.LOCAL_CONFIG_FILE = original_local_config
            runtime_config.LEGACY_LOCAL_CONFIG_FILE = original_legacy_local_config
        self.assertTrue(any(path.name == "mentat.toml" for path in config.config_files))
        self.assertFalse(any(path.name == "mentat.local.toml" for path in config.config_files))
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 8888)
        self.assertEqual(config.app_name, "Mentat")
        self.assertEqual(config.data_dir_source, "toml")

    def test_explicit_config_file_resolves_relative_paths_from_its_own_directory(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "custom.toml"
            config_path.write_text(
                """
[server]
host = "0.0.0.0"
port = 8890

[paths]
data_dir = "runtime/data"
public_dir = "runtime/public"
hermes_home = "runtime/hermes"
obsidian_vault = "runtime/vault"

[dashboard]
display_name = "Casey"
greeting_prefix = "Welcome"
app_name = "CaseyOps"
""".strip() + "\n",
                encoding="utf-8",
            )
            original = os.environ.copy()
            try:
                os.environ.pop("HERMES_HOME", None)
                os.environ.pop("OBSIDIAN_VAULT_PATH", None)
                config = server.load_app_config(server.parse_cli_args(["--config", str(config_path)]))
            finally:
                os.environ.clear()
                os.environ.update(original)

        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 8890)
        self.assertEqual(config.data_dir, config_path.resolve().parent / "runtime" / "data")
        self.assertEqual(config.public_dir, (root / "runtime" / "public").resolve())
        self.assertEqual(config.hermes_home, (root / "runtime" / "hermes").resolve())
        self.assertEqual(config.obsidian_vault, (root / "runtime" / "vault").resolve())
        self.assertEqual(config.display_name, "Casey")
        self.assertEqual(config.greeting_prefix, "Welcome")
        self.assertEqual(config.app_name, "CaseyOps")

    def test_environment_overrides_file_values(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "env-base.toml"
            config_path.write_text(
                """
[server]
host = "127.0.0.1"
port = 8888

[paths]
obsidian_vault = "notes"
""".strip() + "\n",
                encoding="utf-8",
            )
            original = os.environ.copy()
            try:
                os.environ["MENTAT_CONFIG"] = str(config_path)
                os.environ["MENTAT_HOST"] = "0.0.0.0"
                os.environ["MENTAT_PORT"] = "9001"
                os.environ["OBSIDIAN_VAULT_PATH"] = str(root / "env-vault")
                config = server.load_app_config()
            finally:
                os.environ.clear()
                os.environ.update(original)

        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 9001)
        self.assertEqual(config.obsidian_vault, (root / "env-vault").resolve())

    def test_mentat_environment_overrides_previous_environment_aliases(self):
        original = os.environ.copy()
        try:
            os.environ[runtime_config.env_name("HOST", legacy=True)] = "0.0.0.0"
            os.environ[runtime_config.env_name("PORT", legacy=True)] = "9001"
            os.environ["MENTAT_HOST"] = "127.0.0.1"
            os.environ["MENTAT_PORT"] = "7777"
            config = server.load_app_config()
        finally:
            os.environ.clear()
            os.environ.update(original)

        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 7777)

    def test_previous_local_config_file_loads_below_mentat_local_config(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            previous_path = root / ("agent" "-os.local.toml")
            mentat_path = root / "mentat.local.toml"
            previous_path.write_text("[server]\nhost = \"0.0.0.0\"\nport = 9001\n", encoding="utf-8")
            mentat_path.write_text("[server]\nport = 7777\n", encoding="utf-8")
            original_default = runtime_config.DEFAULT_CONFIG_FILE
            original_local = runtime_config.LOCAL_CONFIG_FILE
            original_previous_default = runtime_config.LEGACY_DEFAULT_CONFIG_FILE
            original_previous_local = runtime_config.LEGACY_LOCAL_CONFIG_FILE
            try:
                runtime_config.DEFAULT_CONFIG_FILE = root / "mentat.missing.toml"
                runtime_config.LOCAL_CONFIG_FILE = mentat_path
                runtime_config.LEGACY_DEFAULT_CONFIG_FILE = root / "previous-shared.missing.toml"
                runtime_config.LEGACY_LOCAL_CONFIG_FILE = previous_path
                config = server.load_app_config()
            finally:
                runtime_config.DEFAULT_CONFIG_FILE = original_default
                runtime_config.LOCAL_CONFIG_FILE = original_local
                runtime_config.LEGACY_DEFAULT_CONFIG_FILE = original_previous_default
                runtime_config.LEGACY_LOCAL_CONFIG_FILE = original_previous_local

        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 7777)

    def test_cli_overrides_environment_and_file_values(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "cli-base.toml"
            config_path.write_text(
                """
[server]
host = "127.0.0.1"
port = 8888

[dashboard]
display_name = "File Name"
greeting_prefix = "Hi"
""".strip() + "\n",
                encoding="utf-8",
            )
            original = os.environ.copy()
            try:
                os.environ["MENTAT_CONFIG"] = str(config_path)
                os.environ["MENTAT_HOST"] = "0.0.0.0"
                os.environ["MENTAT_PORT"] = "9001"
                os.environ["MENTAT_DISPLAY_NAME"] = "Env Name"
                cli = server.parse_cli_args(["--host", "127.0.0.1", "--port", "7777", "--display-name", "CLI Name", "--greeting-prefix", "Howdy", "--app-name", "CLI App"])
                config = server.load_app_config(cli)
            finally:
                os.environ.clear()
                os.environ.update(original)

        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 7777)
        self.assertEqual(config.display_name, "CLI Name")
        self.assertEqual(config.greeting_prefix, "Howdy")
        self.assertEqual(config.app_name, "CLI App")

    def test_data_dir_source_distinguishes_cli_current_and_legacy_environment(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            original = os.environ.copy()
            try:
                os.environ["MENTAT_DATA_DIR"] = str(root / "mentat")
                os.environ["AGENT_OS_DATA_DIR"] = str(root / "legacy")
                mentat = server.load_app_config()
                del os.environ["MENTAT_DATA_DIR"]
                legacy = server.load_app_config()
                cli = server.load_app_config(server.parse_cli_args(["--data-dir", str(root / "cli")]))
            finally:
                os.environ.clear()
                os.environ.update(original)

        self.assertEqual(mentat.data_dir_source, "environment")
        self.assertEqual(
            mentat.data_dir,
            runtime_config.resolve_explicit_data_root(root / "mentat", base_dir=root),
        )
        self.assertEqual(legacy.data_dir_source, "legacy_environment")
        self.assertEqual(
            legacy.data_dir,
            runtime_config.resolve_explicit_data_root(root / "legacy", base_dir=root),
        )
        self.assertEqual(cli.data_dir_source, "cli")
        self.assertEqual(
            cli.data_dir,
            runtime_config.resolve_explicit_data_root(root / "cli", base_dir=root),
        )

    def test_configless_data_root_uses_platform_default_without_creating_it(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Simulate a Linux process input even when this test runs on a
            # Windows host; native Windows temp paths are not valid XDG paths.
            xdg_value = f"/mentat-test-{root.name}-xdg"
            xdg_root = Path(xdg_value)
            missing = root / "missing.toml"
            original = os.environ.copy()
            original_paths = (
                runtime_config.DEFAULT_CONFIG_FILE,
                runtime_config.LOCAL_CONFIG_FILE,
                runtime_config.LEGACY_DEFAULT_CONFIG_FILE,
                runtime_config.LEGACY_LOCAL_CONFIG_FILE,
            )
            original_platform = runtime_config.sys.platform
            try:
                runtime_config.DEFAULT_CONFIG_FILE = missing
                runtime_config.LOCAL_CONFIG_FILE = missing
                runtime_config.LEGACY_DEFAULT_CONFIG_FILE = missing
                runtime_config.LEGACY_LOCAL_CONFIG_FILE = missing
                runtime_config.sys.platform = "linux"
                os.environ.pop("MENTAT_DATA_DIR", None)
                os.environ.pop("AGENT_OS_DATA_DIR", None)
                os.environ["XDG_DATA_HOME"] = xdg_value
                config = server.load_app_config()
            finally:
                (
                    runtime_config.DEFAULT_CONFIG_FILE,
                    runtime_config.LOCAL_CONFIG_FILE,
                    runtime_config.LEGACY_DEFAULT_CONFIG_FILE,
                    runtime_config.LEGACY_LOCAL_CONFIG_FILE,
                ) = original_paths
                runtime_config.sys.platform = original_platform
                os.environ.clear()
                os.environ.update(original)

        self.assertEqual(config.data_dir, xdg_root / "Mentat")
        self.assertEqual(config.data_dir_source, "platform_default")
        self.assertFalse(xdg_root.exists())

    def test_installed_startup_initializes_configless_root_from_packaged_seeds(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "packaged-seeds"
            target = root / "platform-data"
            seeds.mkdir()
            for name in data_layout.SEED_FILE_NAMES:
                payload = {} if name == "dashboard.json" else []
                (seeds / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            config = server.AppConfig(
                config_files=tuple(),
                host="127.0.0.1",
                port=8888,
                data_dir=target,
                public_dir=server.PUBLIC_DIR,
                hermes_home=server.HERMES_HOME,
                obsidian_vault=server.OBSIDIAN_VAULT,
                data_dir_source="platform_default",
            )
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds), patch.object(
                runtime_config,
                "DEFAULT_CONFIG_FILE",
                root / "not-a-source-checkout.toml",
            ):
                error = runtime_config.prepare_data_root_for_startup(config)

            self.assertIsNone(error)
            self.assertEqual(
                sorted(path.name for path in target.glob("*.json")),
                sorted(data_layout.SEED_FILE_NAMES),
            )

    def test_source_checkout_platform_default_requires_legacy_migration(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds_and_legacy = root / "source-data"
            target = root / "platform-data"
            seeds_and_legacy.mkdir()
            for name in data_layout.SEED_FILE_NAMES:
                payload = {} if name == "dashboard.json" else []
                (seeds_and_legacy / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            source_config = root / "mentat.toml"
            source_config.write_text('[paths]\ndata_dir = "data"\n', encoding="utf-8")
            config = server.AppConfig(
                config_files=tuple(),
                host="127.0.0.1",
                port=8888,
                data_dir=target,
                public_dir=server.PUBLIC_DIR,
                hermes_home=server.HERMES_HOME,
                obsidian_vault=server.OBSIDIAN_VAULT,
                data_dir_source="platform_default",
            )
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds_and_legacy), patch.object(
                runtime_config,
                "DEFAULT_CONFIG_FILE",
                source_config,
            ):
                error = runtime_config.prepare_data_root_for_startup(config)

            self.assertIn("migration_required", error)
            self.assertFalse(target.exists())

    def test_startup_rejects_a_data_root_overlapping_packaged_seeds(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "package" / "data"
            seeds.mkdir(parents=True)
            for name in data_layout.SEED_FILE_NAMES:
                payload = {} if name == "dashboard.json" else []
                (seeds / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            config = server.AppConfig(
                config_files=tuple(),
                host="127.0.0.1",
                port=8888,
                data_dir=seeds.parent,
                public_dir=server.PUBLIC_DIR,
                hermes_home=server.HERMES_HOME,
                obsidian_vault=server.OBSIDIAN_VAULT,
                data_dir_source="cli",
            )
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                error = runtime_config.prepare_data_root_for_startup(config)

            self.assertIn("data_root_overlaps_seed_root", error)
            self.assertEqual(
                sorted(str(path.relative_to(root)) for path in root.rglob("*")),
                before,
            )

    def test_print_config_summary_includes_only_the_data_dir_source_label(self):
        with TemporaryDirectory() as tmpdir:
            config = server.AppConfig(
                config_files=tuple(),
                host="127.0.0.1",
                port=8888,
                data_dir=Path(tmpdir),
                public_dir=server.PUBLIC_DIR,
                hermes_home=server.HERMES_HOME,
                obsidian_vault=server.OBSIDIAN_VAULT,
                app_name="Mentat",
                data_dir_source="cli",
            )
            original = server.APP_CONFIG
            try:
                server.apply_runtime_config(config)
                summary = server.runtime_config_summary()
            finally:
                server.apply_runtime_config(original)

        self.assertEqual(summary["paths"]["data_dir_source"], "cli")
        self.assertNotIn("preflight", summary)

    def test_overview_uses_config_identity_when_dashboard_json_is_missing(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tasks.json").write_text(json.dumps([], indent=2) + "\n", encoding="utf-8")
            (root / "projects.json").write_text(json.dumps([], indent=2) + "\n", encoding="utf-8")
            (root / "attention.json").write_text(json.dumps([], indent=2) + "\n", encoding="utf-8")
            config = server.AppConfig(
                config_files=tuple(),
                host="127.0.0.1",
                port=8888,
                data_dir=root,
                public_dir=server.PUBLIC_DIR,
                hermes_home=server.HERMES_HOME,
                obsidian_vault=server.OBSIDIAN_VAULT,
                display_name="Config Name",
                greeting_prefix="Welcome",
                app_name="Config App",
            )
            original = server.APP_CONFIG
            try:
                server.apply_runtime_config(config)
                payload = server.overview()
            finally:
                server.apply_runtime_config(original)

        self.assertEqual(payload["identity"]["display_name"], "Config Name")
        self.assertEqual(payload["identity"]["greeting_prefix"], "Welcome")
        self.assertEqual(payload["identity"]["app_name"], "Config App")


if __name__ == "__main__":
    unittest.main()
