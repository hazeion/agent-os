from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch

import data_layout
import data_migration
import json_store
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

    def test_verified_migration_receipt_allows_normal_mutation_and_blocks_invalid_data(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds_and_legacy = root / "source-data"
            target = root / "platform-data"
            seeds_and_legacy.mkdir()
            for name in data_layout.SEED_FILE_NAMES:
                payload = {} if name == "dashboard.json" else []
                if name == "tasks.json":
                    payload = [{"id": "legacy-task"}]
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
            preview = data_migration.preview_legacy_migration(
                seeds_and_legacy,
                seeds_and_legacy,
                target,
                home=root / "home",
            )
            result = data_migration.migrate_legacy_data(
                seeds_and_legacy,
                seeds_and_legacy,
                target,
                confirmation_token=preview.confirmation_token or "",
                home=root / "home",
            )
            self.assertEqual(result.status, "migrated")

            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds_and_legacy), patch.object(
                runtime_config,
                "DEFAULT_CONFIG_FILE",
                source_config,
            ):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                json_store.update_json(
                    target / "tasks.json",
                    [],
                    lambda _current: (
                        [{"id": "legitimate-post-migration-task"}],
                        None,
                    ),
                )
                if os.name == "posix":
                    self.assertEqual((target / "tasks.json").stat().st_mode & 0o777, 0o600)
                self.assertTrue(data_migration.migration_receipt_valid(target))
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                orphan = target / (".tasks.json." + "a" * 32 + ".tmp")
                orphan.write_bytes(b'[{"id":"interrupted-write"}')
                if os.name == "posix":
                    orphan.chmod(0o600)
                self.assertTrue(data_migration.migration_receipt_valid(target))
                self.assertEqual(
                    data_migration.preview_legacy_migration(
                        seeds_and_legacy,
                        seeds_and_legacy,
                        target,
                        home=root / "home",
                    ).status,
                    "already_migrated",
                )
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                if os.name == "posix":
                    orphan.chmod(0o644)
                    self.assertFalse(data_migration.migration_receipt_valid(target))
                    self.assertIsNotNone(runtime_config.prepare_data_root_for_startup(config))
                    orphan.chmod(0o600)
                    self.assertTrue(data_migration.migration_receipt_valid(target))

            explicit_config = server.AppConfig(
                config_files=config.config_files,
                host=config.host,
                port=config.port,
                data_dir=config.data_dir,
                public_dir=config.public_dir,
                hermes_home=config.hermes_home,
                obsidian_vault=config.obsidian_vault,
                data_dir_source="cli",
            )
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds_and_legacy):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(explicit_config))
                (target / "tasks.json").write_text("{}\n", encoding="utf-8")
                self.assertFalse(data_migration.migration_receipt_valid(target))
                self.assertIsNotNone(runtime_config.prepare_data_root_for_startup(explicit_config))

    def test_interrupted_migration_blocks_startup_for_every_data_root_source(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            seeds.mkdir()
            legacy.mkdir()
            for name in data_layout.SEED_FILE_NAMES:
                payload = {} if name == "dashboard.json" else []
                (seeds / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
                if name == "tasks.json":
                    payload = [{"id": "legacy-task"}]
                (legacy / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            preview = data_migration.preview_legacy_migration(
                seeds,
                legacy,
                target,
                home=root / "home",
            )
            original_publish = data_migration._publish_destination
            calls = 0

            def interrupt_after_one(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated interruption")
                return original_publish(*args, **kwargs)

            with patch.object(
                data_migration,
                "_publish_destination",
                side_effect=interrupt_after_one,
            ):
                result = data_migration.migrate_legacy_data(
                    seeds,
                    legacy,
                    target,
                    confirmation_token=preview.confirmation_token or "",
                    home=root / "home",
                )
            self.assertEqual(result.status, "partial_failure")
            before_names = {path.name for path in target.glob("*.json")}

            for source in ("cli", "environment", "legacy_environment", "toml", "platform_default"):
                with self.subTest(source=source):
                    config = server.AppConfig(
                        config_files=tuple(),
                        host="127.0.0.1",
                        port=8888,
                        data_dir=target,
                        public_dir=server.PUBLIC_DIR,
                        hermes_home=server.HERMES_HOME,
                        obsidian_vault=server.OBSIDIAN_VAULT,
                        data_dir_source=source,
                    )
                    with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                        error = runtime_config.prepare_data_root_for_startup(config)
                    self.assertIn("incomplete or invalid legacy migration", error)
                    self.assertEqual(
                        {path.name for path in target.glob("*.json")},
                        before_names,
                    )

    def test_startup_rechecks_migration_artifacts_under_the_shared_lock(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            seeds.mkdir()
            legacy.mkdir()
            for name in data_layout.SEED_FILE_NAMES:
                seed_payload = {} if name == "dashboard.json" else []
                legacy_payload = seed_payload
                if name == "tasks.json":
                    legacy_payload = [{"id": "legacy-task"}]
                (seeds / name).write_text(json.dumps(seed_payload) + "\n", encoding="utf-8")
                (legacy / name).write_text(json.dumps(legacy_payload) + "\n", encoding="utf-8")

            preview = data_migration.preview_legacy_migration(
                seeds,
                legacy,
                target,
                home=root / "home",
            )
            checked = Event()
            migration_finished = Event()
            startup_result: list[str | None] = []
            real_startup_status = data_migration.migration_startup_status

            def pause_after_unlocked_check(data_root):
                status = real_startup_status(data_root)
                checked.set()
                self.assertTrue(migration_finished.wait(10))
                return status

            config = server.AppConfig(
                config_files=tuple(),
                host="127.0.0.1",
                port=8888,
                data_dir=target,
                public_dir=server.PUBLIC_DIR,
                hermes_home=server.HERMES_HOME,
                obsidian_vault=server.OBSIDIAN_VAULT,
                data_dir_source="cli",
            )

            def run_startup():
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds), patch.object(
                    runtime_config,
                    "migration_startup_status",
                    side_effect=pause_after_unlocked_check,
                ):
                    startup_result.append(runtime_config.prepare_data_root_for_startup(config))

            startup_thread = Thread(target=run_startup)
            startup_thread.start()
            self.assertTrue(checked.wait(10))
            original_publish = data_migration._publish_destination
            calls = 0

            def interrupt_after_one(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated interruption")
                return original_publish(*args, **kwargs)

            try:
                with patch.object(
                    data_migration,
                    "_publish_destination",
                    side_effect=interrupt_after_one,
                ):
                    migrated = data_migration.migrate_legacy_data(
                        seeds,
                        legacy,
                        target,
                        confirmation_token=preview.confirmation_token or "",
                        home=root / "home",
                    )
                self.assertEqual(migrated.status, "partial_failure")
            finally:
                migration_finished.set()
                startup_thread.join(10)

            self.assertFalse(startup_thread.is_alive())
            self.assertEqual(len(startup_result), 1)
            self.assertIn("migration_incomplete_or_invalid", startup_result[0] or "")
            self.assertLess(
                len(list(target.glob("*.json"))),
                len(data_layout.SEED_FILE_NAMES),
            )

    def test_startup_rejects_root_substitution_during_receipt_validation(self):
        if os.name == "nt":
            self.skipTest("Windows target guards prevent the injected rename natively")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            displaced = root / "displaced-target"
            seeds.mkdir()
            for name in data_layout.SEED_FILE_NAMES:
                payload = {} if name == "dashboard.json" else []
                (seeds / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            preview = data_migration.preview_legacy_migration(
                seeds,
                seeds,
                target,
                home=root / "home",
            )
            migrated = data_migration.migrate_legacy_data(
                seeds,
                seeds,
                target,
                confirmation_token=preview.confirmation_token or "",
                home=root / "home",
            )
            self.assertEqual(migrated.status, "migrated")
            config = server.AppConfig(
                config_files=tuple(),
                host="127.0.0.1",
                port=8888,
                data_dir=target,
                public_dir=server.PUBLIC_DIR,
                hermes_home=server.HERMES_HOME,
                obsidian_vault=server.OBSIDIAN_VAULT,
                data_dir_source="cli",
            )
            real_receipt_valid = data_migration.migration_receipt_valid
            substituted = False

            def substitute_after_validation(data_root):
                nonlocal substituted
                valid = real_receipt_valid(data_root)
                if valid and not substituted:
                    substituted = True
                    target.rename(displaced)
                    target.mkdir()
                return valid

            with patch.object(
                data_migration,
                "migration_receipt_valid",
                side_effect=substitute_after_validation,
            ), patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                error = runtime_config.prepare_data_root_for_startup(config)

            self.assertTrue(substituted)
            self.assertIsNotNone(error)
            self.assertFalse(
                any((target / name).exists() for name in data_layout.SEED_FILE_NAMES)
            )
            self.assertTrue(data_migration.migration_receipt_valid(displaced))

    def test_startup_rejects_completed_root_substitution_before_initialization(self):
        if os.name == "nt":
            self.skipTest("Windows target guards prevent the injected rename natively")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            displaced = root / "displaced-target"
            seeds.mkdir()
            for name in data_layout.SEED_FILE_NAMES:
                payload = {} if name == "dashboard.json" else []
                (seeds / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            preview = data_migration.preview_legacy_migration(
                seeds,
                seeds,
                target,
                home=root / "home",
            )
            migrated = data_migration.migrate_legacy_data(
                seeds,
                seeds,
                target,
                confirmation_token=preview.confirmation_token or "",
                home=root / "home",
            )
            self.assertEqual(migrated.status, "migrated")
            config = server.AppConfig(
                config_files=tuple(),
                host="127.0.0.1",
                port=8888,
                data_dir=target,
                public_dir=server.PUBLIC_DIR,
                hermes_home=server.HERMES_HOME,
                obsidian_vault=server.OBSIDIAN_VAULT,
                data_dir_source="cli",
            )
            real_initialize = runtime_config.initialize_data_root

            def substitute_before_initialize(*args, **kwargs):
                target.rename(displaced)
                target.mkdir()
                return real_initialize(*args, **kwargs)

            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds), patch.object(
                runtime_config,
                "initialize_data_root",
                side_effect=substitute_before_initialize,
            ):
                error = runtime_config.prepare_data_root_for_startup(config)

            self.assertIsNotNone(error)
            self.assertFalse(
                any((target / name).exists() for name in data_layout.SEED_FILE_NAMES)
            )
            self.assertTrue(data_migration.migration_receipt_valid(displaced))

    def test_completed_migration_secures_every_required_directory_boundary(self):
        for case in ("missing_runtime", "broad_private", "file_private", "linked_runtime"):
            if case == "broad_private" and os.name != "posix":
                continue
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                seeds.mkdir()
                for name in data_layout.SEED_FILE_NAMES:
                    payload = {} if name == "dashboard.json" else []
                    (seeds / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
                preview = data_migration.preview_legacy_migration(
                    seeds,
                    seeds,
                    target,
                    home=root / "home",
                )
                migrated = data_migration.migrate_legacy_data(
                    seeds,
                    seeds,
                    target,
                    confirmation_token=preview.confirmation_token or "",
                    home=root / "home",
                )
                self.assertEqual(migrated.status, "migrated")

                outside = root / "outside"
                if case == "missing_runtime":
                    (target / "runtime").rmdir()
                elif case == "broad_private":
                    (target / "private").chmod(0o755)
                elif case == "file_private":
                    (target / "private").rmdir()
                    (target / "private").write_text("not a directory", encoding="utf-8")
                else:
                    (target / "runtime").rmdir()
                    outside.mkdir()
                    try:
                        (target / "runtime").symlink_to(outside, target_is_directory=True)
                    except OSError:
                        self.skipTest("directory symlink creation unavailable")

                config = server.AppConfig(
                    config_files=tuple(),
                    host="127.0.0.1",
                    port=8888,
                    data_dir=target,
                    public_dir=server.PUBLIC_DIR,
                    hermes_home=server.HERMES_HOME,
                    obsidian_vault=server.OBSIDIAN_VAULT,
                    data_dir_source="cli",
                )
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    error = runtime_config.prepare_data_root_for_startup(config)

                if case in {"missing_runtime", "broad_private"}:
                    self.assertIsNone(error)
                    selected = target / (
                        "runtime" if case == "missing_runtime" else "private"
                    )
                    self.assertTrue(selected.is_dir())
                    if os.name == "posix":
                        self.assertEqual(selected.stat().st_mode & 0o777, 0o700)
                else:
                    self.assertIsNotNone(error)
                    self.assertFalse((outside / "server-state.json").exists())

    def test_completed_receipt_writer_temporary_exception_stays_fail_closed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            seeds.mkdir()
            for name in data_layout.SEED_FILE_NAMES:
                payload = {} if name == "dashboard.json" else []
                (seeds / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            preview = data_migration.preview_legacy_migration(
                seeds,
                seeds,
                target,
                home=root / "home",
            )
            migrated = data_migration.migrate_legacy_data(
                seeds,
                seeds,
                target,
                confirmation_token=preview.confirmation_token or "",
                home=root / "home",
            )
            self.assertEqual(migrated.status, "migrated")
            config = server.AppConfig(
                config_files=tuple(),
                host="127.0.0.1",
                port=8888,
                data_dir=target,
                public_dir=server.PUBLIC_DIR,
                hermes_home=server.HERMES_HOME,
                obsidian_vault=server.OBSIDIAN_VAULT,
                data_dir_source="cli",
            )
            exact = target / (".tasks.json." + "b" * 32 + ".tmp")
            outside = root / "outside"
            outside.write_bytes(b"[]\n")
            if os.name == "posix":
                outside.chmod(0o600)

            def assert_completed_root_blocks(artifact: Path):
                self.assertFalse(data_migration.migration_receipt_valid(target))
                blocked = data_migration.preview_legacy_migration(
                    seeds,
                    seeds,
                    target,
                    home=root / "home",
                )
                self.assertEqual(blocked.status, "unsafe")
                self.assertIsNotNone(runtime_config.prepare_data_root_for_startup(config))
                if artifact.is_symlink() or artifact.is_file():
                    artifact.unlink()
                self.assertTrue(data_migration.migration_receipt_valid(target))

            with self.subTest(case="lookalike_name"):
                lookalike = target / (".tasks.json." + "g" * 32 + ".tmp")
                lookalike.write_bytes(b"[]\n")
                if os.name == "posix":
                    lookalike.chmod(0o600)
                assert_completed_root_blocks(lookalike)

            with self.subTest(case="symlink"):
                try:
                    exact.symlink_to(outside)
                except OSError:
                    pass
                else:
                    assert_completed_root_blocks(exact)

            with self.subTest(case="hardlink"):
                try:
                    os.link(outside, exact)
                except OSError:
                    pass
                else:
                    assert_completed_root_blocks(exact)

            with self.subTest(case="oversized"):
                with exact.open("wb") as handle:
                    handle.truncate(data_layout.MAX_PREFLIGHT_JSON_BYTES + 1)
                if os.name == "posix":
                    exact.chmod(0o600)
                assert_completed_root_blocks(exact)

            if os.name == "posix" and hasattr(os, "geteuid"):
                with self.subTest(case="owner_mismatch"):
                    exact.write_bytes(b"[]\n")
                    exact.chmod(0o600)
                    effective_uid = os.geteuid()
                    with patch.object(
                        data_migration.os,
                        "geteuid",
                        return_value=effective_uid + 1,
                    ):
                        self.assertFalse(data_migration._safe_json_store_temporary(exact))
                    exact.unlink()

            with self.subTest(case="receipt_absent"):
                fresh_target = root / "fresh-target"
                fresh_target.mkdir()
                fresh_temp = fresh_target / (".tasks.json." + "c" * 32 + ".tmp")
                fresh_temp.write_bytes(b"[]\n")
                if os.name == "posix":
                    fresh_temp.chmod(0o600)
                blocked = data_migration.preview_legacy_migration(
                    seeds,
                    seeds,
                    fresh_target,
                    home=root / "home",
                )
                self.assertEqual(blocked.status, "unsafe")
                self.assertIn("unsupported_target_entries", blocked.issues)

    def test_orphaned_backup_temporary_blocks_explicit_root_startup(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            seeds.mkdir()
            for name in data_layout.SEED_FILE_NAMES:
                payload = {} if name == "dashboard.json" else []
                (seeds / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            backups = target / "backups"
            backups.mkdir(parents=True)
            temporary = backups / (
                ".legacy-migration-v1-"
                + "0" * 24
                + ".zip.mentat-init-"
                + "1" * 32
                + ".tmp"
            )
            temporary.write_bytes(b"interrupted-private-backup")
            if os.name == "posix":
                temporary.chmod(0o600)
            config = server.AppConfig(
                config_files=tuple(),
                host="127.0.0.1",
                port=8888,
                data_dir=target,
                public_dir=server.PUBLIC_DIR,
                hermes_home=server.HERMES_HOME,
                obsidian_vault=server.OBSIDIAN_VAULT,
                data_dir_source="cli",
            )

            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                error = runtime_config.prepare_data_root_for_startup(config)

            self.assertIn("incomplete or invalid legacy migration", error)
            self.assertFalse(any((target / name).exists() for name in data_layout.SEED_FILE_NAMES))

    def test_legacy_migration_cli_preview_and_confirmation_are_bounded(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            seeds.mkdir()
            legacy.mkdir()
            for name in data_layout.SEED_FILE_NAMES:
                payload = {} if name == "dashboard.json" else []
                (seeds / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
                if name == "tasks.json":
                    payload = [{"id": "legacy-task"}]
                (legacy / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            config = server.AppConfig(
                config_files=tuple(),
                host="127.0.0.1",
                port=8888,
                data_dir=target,
                public_dir=server.PUBLIC_DIR,
                hermes_home=server.HERMES_HOME,
                obsidian_vault=server.OBSIDIAN_VAULT,
                data_dir_source="cli",
            )
            preview_args = server.parse_cli_args(
                ["--preview-legacy-migration", "--legacy-data-dir", str(legacy)]
            )
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                preview_summary, preview_exit = runtime_config.run_legacy_migration_cli(
                    preview_args,
                    config,
                )
                token = preview_summary["confirmation_token"]
                confirm_args = server.parse_cli_args(
                    [
                        "--confirm-legacy-migration",
                        token,
                        "--legacy-data-dir",
                        str(legacy),
                    ]
                )
                result_summary, result_exit = runtime_config.run_legacy_migration_cli(
                    confirm_args,
                    config,
                )

            serialized = json.dumps(preview_summary)
            self.assertEqual(preview_exit, 0)
            self.assertEqual(preview_summary["status"], "ready")
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("sha256", serialized)
            self.assertEqual(result_exit, 0)
            self.assertEqual(result_summary["status"], "migrated")
            self.assertTrue(data_migration.migration_receipt_valid(target))

    def test_legacy_migration_cli_modes_are_explicit_and_exclusive(self):
        with self.assertRaises(SystemExit):
            server.parse_cli_args(["--legacy-data-dir", "/tmp/legacy-only"])
        with self.assertRaises(SystemExit):
            server.parse_cli_args(
                ["--print-config", "--preview-legacy-migration"]
            )
        with self.assertRaises(SystemExit):
            server.parse_cli_args(
                ["--preview-legacy-migration", "--confirm-legacy-migration", "0" * 64]
            )
        with self.assertRaises(SystemExit):
            server.parse_cli_args(
                ["--preview-legacy-migration", "--preview-schema-migration"]
            )
        with self.assertRaises(SystemExit):
            server.parse_cli_args(
                ["--preview-schema-migration", "--confirm-schema-migration", "0" * 64]
            )

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

    def test_overview_uses_config_identity_when_dashboard_identity_is_absent(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in data_layout.SEED_FILE_NAMES:
                payload = {} if name == "dashboard.json" else []
                (root / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            if os.name == "posix":
                for path in root.glob("*.json"):
                    path.chmod(0o600)
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
