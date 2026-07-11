from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

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
        self.assertEqual(config.data_dir, (root / "runtime" / "data").resolve())
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
