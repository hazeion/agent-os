from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch
import zipfile

import data_layout
import data_migration
import data_schema
import json_store
import runtime_config
import server


class DataSchemaTests(unittest.TestCase):
    def make_directory_redirect(self, link: Path, destination: Path) -> None:
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(destination)],
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            link.symlink_to(destination, target_is_directory=True)

    def write_inventory(self, root: Path, *, private: bool = False) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for name in data_layout.SEED_FILE_NAMES:
            payload = {"theme": "midnight"} if name == "dashboard.json" else []
            if name == "tasks.json":
                payload = [{"id": "operator-task"}]
            path = root / name
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            if private and os.name == "posix":
                path.chmod(0o600)
        for name in data_layout.DATA_ROOT_DIRECTORY_NAMES:
            directory = root / name
            directory.mkdir(exist_ok=True)
            if private and os.name == "posix":
                directory.chmod(0o700)

    def snapshot(self, root: Path) -> dict[str, tuple[int, bytes | None]]:
        return {
            str(path.relative_to(root)): (
                path.lstat().st_mtime_ns,
                path.read_bytes() if path.is_file() else None,
            )
            for path in root.rglob("*")
        }

    def config(self, target: Path) -> server.AppConfig:
        return server.AppConfig(
            config_files=tuple(),
            host="127.0.0.1",
            port=8888,
            data_dir=target,
            public_dir=server.PUBLIC_DIR,
            hermes_home=server.HERMES_HOME,
            obsidian_vault=server.OBSIDIAN_VAULT,
            data_dir_source="cli",
        )

    def test_preview_is_bounded_state_bound_and_read_only(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            before = self.snapshot(target)

            preview = data_schema.preview_schema_migration(
                seeds,
                target,
                home=root / "home",
            )
            summary = preview.public_summary()

            self.assertEqual(preview.status, "ready")
            self.assertRegex(preview.confirmation_token or "", r"^[0-9a-f]{64}$")
            self.assertEqual(len(summary["items"]), len(data_layout.SEED_FILE_NAMES))
            self.assertEqual({item["from_version"] for item in summary["items"]}, {0})
            self.assertEqual({item["to_version"] for item in summary["items"]}, {1})
            encoded = json.dumps(summary)
            self.assertNotIn(str(root), encoded)
            self.assertNotIn("operator-task", encoded)
            self.assertNotIn("sha256", encoded.lower())
            self.assertEqual(before, self.snapshot(target))

            (target / "tasks.json").write_text("[]\n", encoding="utf-8")
            changed = data_schema.preview_schema_migration(
                seeds,
                target,
                home=root / "home",
            )
            self.assertNotEqual(preview.confirmation_token, changed.confirmation_token)

    def test_migration_backs_up_records_manifest_and_allows_normal_mutation(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            live_before = {
                name: (target / name).read_bytes()
                for name in data_layout.SEED_FILE_NAMES
            }
            preview = data_schema.preview_schema_migration(
                seeds,
                target,
                home=root / "home",
            )

            result = data_schema.migrate_data_schema(
                seeds,
                target,
                confirmation_token=preview.confirmation_token or "",
                home=root / "home",
            )

            self.assertEqual(result.status, "migrated")
            self.assertEqual(data_schema.schema_startup_status(target), "current")
            self.assertEqual(
                live_before,
                {name: (target / name).read_bytes() for name in data_layout.SEED_FILE_NAMES},
            )
            manifest = json.loads(
                (target / "config" / data_schema.SCHEMA_MANIFEST_NAME).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["origin"], "schema_migration")
            self.assertEqual(
                [item["name"] for item in manifest["documents"]],
                list(data_layout.SEED_FILE_NAMES),
            )
            backup = target / "backups" / manifest["backup"]["name"]
            self.assertTrue(backup.is_file())
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
                self.assertEqual(
                    stat.S_IMODE(
                        (target / "config" / data_schema.SCHEMA_MANIFEST_NAME).stat().st_mode
                    ),
                    0o600,
                )
            self.assertEqual(
                data_schema.preview_schema_migration(
                    seeds,
                    target,
                    home=root / "home",
                ).status,
                "already_current",
            )

            json_store.update_json(
                target / "tasks.json",
                [],
                lambda _current: ([{"id": "post-schema-task"}], None),
            )
            self.assertEqual(data_schema.schema_startup_status(target), "current")

    def test_confirmation_rejects_stale_token_and_changed_state(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            preview = data_schema.preview_schema_migration(
                seeds,
                target,
                home=root / "home",
            )
            wrong = data_schema.migrate_data_schema(
                seeds,
                target,
                confirmation_token="0" * 64,
                home=root / "home",
            )
            self.assertEqual(wrong.status, "blocked")
            self.assertFalse((target / "config" / data_schema.SCHEMA_MANIFEST_NAME).exists())

            (target / "tasks.json").write_text("[]\n", encoding="utf-8")
            changed = data_schema.migrate_data_schema(
                seeds,
                target,
                confirmation_token=preview.confirmation_token or "",
                home=root / "home",
            )
            self.assertEqual(changed.status, "blocked")
            self.assertFalse((target / "config" / data_schema.SCHEMA_MANIFEST_NAME).exists())

    def test_interrupted_manifest_publication_resumes_only_matching_backup(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            preview = data_schema.preview_schema_migration(
                seeds,
                target,
                home=root / "home",
            )
            real_publish = data_schema._publish_raw_missing

            def interrupt_manifest(path, *args, **kwargs):
                if Path(path).name == data_schema.SCHEMA_MANIFEST_NAME:
                    raise OSError("simulated interruption")
                return real_publish(path, *args, **kwargs)

            with patch.object(
                data_schema,
                "_publish_raw_missing",
                side_effect=interrupt_manifest,
            ):
                interrupted = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=preview.confirmation_token or "",
                    home=root / "home",
                )
            self.assertEqual(interrupted.status, "partial_failure")
            manifest_temporary = target / "config" / (
                ".data-schema.json.mentat-init-" + "2" * 32 + ".tmp"
            )
            manifest_temporary.write_bytes(b"interrupted-manifest")
            if os.name == "posix":
                manifest_temporary.chmod(0o600)
            self.assertEqual(
                (
                    recovery := data_schema.preview_schema_migration(
                        seeds,
                        target,
                        home=root / "home",
                    )
                ).status,
                "recovery_required",
            )
            self.assertEqual(data_schema.schema_startup_status(target), "invalid")
            reconciled = data_schema.migrate_data_schema(
                seeds,
                target,
                confirmation_token=recovery.confirmation_token or "",
                home=root / "home",
            )
            self.assertEqual(reconciled.status, "reconciled")
            self.assertFalse(manifest_temporary.exists())
            retry = data_schema.preview_schema_migration(
                seeds,
                target,
                home=root / "home",
            )
            self.assertEqual(retry.status, "resume_required")
            resumed = data_schema.migrate_data_schema(
                seeds,
                target,
                confirmation_token=retry.confirmation_token or "",
                home=root / "home",
            )
            self.assertEqual(resumed.status, "resumed")
            self.assertEqual(data_schema.schema_startup_status(target), "current")

    def test_startup_refuses_current_or_newer_missing_documents_before_writes(self):
        for case in ("current", "newer"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                config = self.config(target)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                manifest_path = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                if case == "newer":
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["format_version"] = 99
                    manifest_path.write_bytes(data_schema._canonical_json(manifest))
                (target / "tasks.json").unlink()
                before = self.snapshot(target)

                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    error = runtime_config.prepare_data_root_for_startup(config)

                expected = (
                    "schema_version_newer_than_supported"
                    if case == "newer"
                    else "invalid_data_schema"
                )
                self.assertIn(expected, error or "")
                self.assertEqual(before, self.snapshot(target))
                self.assertFalse((target / "tasks.json").exists())

    def test_current_schema_startup_repairs_or_rejects_required_directories(self):
        for directory in data_layout.DATA_ROOT_DIRECTORY_NAMES:
            with self.subTest(case="missing", directory=directory), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                config = self.config(target)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                if directory == "config":
                    continue
                selected = target / directory
                selected.rmdir()
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                self.assertTrue(selected.is_dir())
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(selected.stat().st_mode), 0o700)

        if os.name == "posix":
            with TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                config = self.config(target)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                for directory in data_layout.DATA_ROOT_DIRECTORY_NAMES:
                    (target / directory).chmod(0o755)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                self.assertTrue(
                    all(
                        stat.S_IMODE((target / directory).stat().st_mode) == 0o700
                        for directory in data_layout.DATA_ROOT_DIRECTORY_NAMES
                    )
                )

        for directory in data_layout.DATA_ROOT_DIRECTORY_NAMES:
            with self.subTest(case="redirect", directory=directory), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                outside = root / "outside"
                self.write_inventory(seeds)
                config = self.config(target)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                selected = target / directory
                selected.rename(outside)
                try:
                    selected.symlink_to(outside, target_is_directory=True)
                except OSError:
                    self.skipTest("directory symlink creation unavailable")
                before = self.snapshot(outside)
                before_mode = stat.S_IMODE(outside.stat().st_mode)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    error = runtime_config.prepare_data_root_for_startup(config)
                self.assertIsNotNone(error)
                self.assertEqual(before, self.snapshot(outside))
                self.assertEqual(before_mode, stat.S_IMODE(outside.stat().st_mode))

    def test_under_lock_schema_change_blocks_seed_repair(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            config = self.config(target)
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
            real_status = runtime_config.schema_status_under_lock
            changed = False

            def delete_before_locked_check(path, descriptor):
                nonlocal changed
                if not changed:
                    changed = True
                    (target / "tasks.json").unlink()
                return real_status(path, descriptor)

            with (
                patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds),
                patch.object(
                    runtime_config,
                    "schema_status_under_lock",
                    side_effect=delete_before_locked_check,
                ),
            ):
                error = runtime_config.prepare_data_root_for_startup(config)
            self.assertIn("invalid_data_schema", error or "")
            self.assertFalse((target / "tasks.json").exists())

    def test_required_directory_hardening_stays_on_pinned_root(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            displaced = root / "displaced"
            self.write_inventory(seeds)
            config = self.config(target)
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
            real_preflight = data_layout.preflight_data_root
            calls = 0

            def substitute_after_locked_preflight(*args, **kwargs):
                nonlocal calls
                result = real_preflight(*args, **kwargs)
                calls += 1
                if calls == 2:
                    target.rename(displaced)
                    target.mkdir(mode=0o755)
                return result

            with (
                patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds),
                patch.object(
                    data_layout,
                    "preflight_data_root",
                    side_effect=substitute_after_locked_preflight,
                ),
            ):
                error = runtime_config.prepare_data_root_for_startup(config)

            self.assertIsNotNone(error)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)
            self.assertEqual(data_schema.schema_startup_status(displaced), "current")

    def test_initializer_rejects_root_replacement_before_final_success(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        for replacement_schema in ("legacy", "current"):
            with self.subTest(replacement_schema=replacement_schema), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                replacement = root / "replacement"
                displaced = root / "displaced"
                self.write_inventory(seeds)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(self.config(target)))
                if replacement_schema == "legacy":
                    self.write_inventory(replacement, private=True)
                else:
                    with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                        self.assertIsNone(
                            runtime_config.prepare_data_root_for_startup(self.config(replacement))
                        )
                target_before = self.snapshot(target)
                replacement_before = self.snapshot(replacement)
                real_preflight = data_layout.preflight_data_root
                calls = 0

                def replace_before_final_preflight(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == 3:
                        target.rename(displaced)
                        replacement.rename(target)
                    return real_preflight(*args, **kwargs)

                with (
                    patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds),
                    patch.object(
                        data_layout,
                        "preflight_data_root",
                        side_effect=replace_before_final_preflight,
                    ),
                ):
                    error = runtime_config.prepare_data_root_for_startup(self.config(target))

                self.assertEqual(calls, 3)
                self.assertIsNotNone(error)
                self.assertEqual(self.snapshot(displaced), target_before)
                self.assertEqual(self.snapshot(target), replacement_before)
                self.assertEqual(data_schema.schema_startup_status(displaced), "current")
                self.assertEqual(
                    data_schema.schema_startup_status(target),
                    replacement_schema,
                )

    def test_startup_rejects_same_status_root_replacement_after_initializer(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            replacement = root / "replacement"
            displaced = root / "displaced"
            self.write_inventory(seeds)
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(self.config(target)))
                self.assertIsNone(
                    runtime_config.prepare_data_root_for_startup(self.config(replacement))
                )
            real_initialize = runtime_config.initialize_data_root

            def replace_after_initializer(*args, **kwargs):
                result = real_initialize(*args, **kwargs)
                target.rename(displaced)
                replacement.rename(target)
                return result

            with (
                patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds),
                patch.object(
                    runtime_config,
                    "initialize_data_root",
                    side_effect=replace_after_initializer,
                ),
            ):
                error = runtime_config.prepare_data_root_for_startup(self.config(target))

            self.assertIn("changed after locked verification", error or "")
            self.assertEqual(data_schema.schema_startup_status(target), "current")
            self.assertEqual(data_schema.schema_startup_status(displaced), "current")

    def test_json_store_mutation_never_writes_substituted_root(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target"
            displaced = root / "displaced"
            self.write_inventory(target, private=True)
            original = (target / "tasks.json").read_bytes()
            real_read = json_store.read_json
            substituted = False

            def substitute_after_pinned_read(path, default, *, parent_fd=None, **kwargs):
                nonlocal substituted
                current = real_read(path, default, parent_fd=parent_fd, **kwargs)
                if not substituted:
                    substituted = True
                    target.rename(displaced)
                    target.mkdir(mode=0o755)
                return current

            with patch.object(json_store, "read_json", side_effect=substitute_after_pinned_read):
                with self.assertRaises(OSError):
                    json_store.update_json(
                        target / "tasks.json",
                        [],
                        lambda _current: ([{"id": "must-not-hit-replacement"}], None),
                    )

            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual((displaced / "tasks.json").read_bytes(), original)

    def test_writer_parent_hardening_never_touches_replacement_path(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target"
            displaced = root / "displaced"
            self.write_inventory(target, private=True)
            real_write = json_store.write_json_atomic
            substituted = False

            def substitute_at_writer_entry(*args, **kwargs):
                nonlocal substituted
                if not substituted:
                    substituted = True
                    target.rename(displaced)
                    target.mkdir(mode=0o755)
                return real_write(*args, **kwargs)

            with patch.object(
                json_store,
                "write_json_atomic",
                side_effect=substitute_at_writer_entry,
            ):
                with self.assertRaises(OSError):
                    json_store.update_json(
                        target / "tasks.json",
                        [],
                        lambda _current: ([{"id": "pinned-write"}], None),
                        required_mode=0o600,
                    )
            self.assertTrue(substituted)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(
                json.loads((displaced / "tasks.json").read_text(encoding="utf-8")),
                [{"id": "pinned-write"}],
            )

    def test_product_reads_and_writes_require_existing_safe_document(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target"
            outside = root / "outside.json"
            self.write_inventory(target, private=True)
            outside.write_text('[{"id":"outside"}]\n', encoding="utf-8")
            if os.name == "posix":
                outside.chmod(0o600)
            approved = data_layout._absolute_without_following(target)
            common = (
                patch.object(server, "DATA_DIR", approved),
                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                patch.object(server, "DATA_MUTATION_LOCK", True),
            )
            selected = target / "tasks.json"
            selected.unlink()
            if os.name == "nt":
                try:
                    selected.symlink_to(outside)
                except OSError as exc:
                    self.skipTest(f"file symlink unavailable: {exc}")
            else:
                selected.symlink_to(outside)
            with common[0], common[1], common[2]:
                with self.assertRaises(OSError):
                    server.read_json_file("tasks.json", [])
                with self.assertRaises(OSError):
                    server.update_json_file(
                        "tasks.json",
                        [],
                        lambda _current: ([{"id": "must-not-write"}], None),
                    )
            self.assertEqual(outside.read_text(encoding="utf-8"), '[{"id":"outside"}]\n')

            selected.unlink()
            with (
                patch.object(server, "DATA_DIR", approved),
                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                patch.object(server, "DATA_MUTATION_LOCK", True),
            ):
                with self.assertRaises(FileNotFoundError):
                    server.read_json_file("tasks.json", [])
                with self.assertRaises(FileNotFoundError):
                    server.update_json_file(
                        "tasks.json",
                        [],
                        lambda _current: ([{"id": "must-not-recreate"}], None),
                    )
            self.assertFalse(selected.exists())

    def test_json_writers_reject_preexisting_root_and_ancestor_redirects(self):
        for scope in ("root", "ancestor"):
            for writer in ("store", "server", "server_development"):
                with self.subTest(scope=scope, writer=writer), TemporaryDirectory() as tmpdir:
                    base = Path(tmpdir)
                    selected_parent = base / "selected-parent"
                    selected = selected_parent / "data"
                    outside_parent = base / "outside-parent"
                    outside = outside_parent / "data"
                    selected_parent.mkdir()
                    outside_parent.mkdir()
                    self.write_inventory(selected, private=True)
                    self.write_inventory(outside, private=True)
                    selected_before = (selected / "projects.json").read_bytes()
                    outside_before = (outside / "projects.json").read_bytes()
                    if scope == "root":
                        displaced = base / "displaced-data"
                        selected.rename(displaced)
                        self.make_directory_redirect(selected, outside)
                    else:
                        displaced_parent = base / "displaced-parent"
                        selected_parent.rename(displaced_parent)
                        self.make_directory_redirect(selected_parent, outside_parent)
                        displaced = displaced_parent / "data"

                    mutator = lambda _current: ([{"id": "must-not-escape"}], None)
                    approved = data_layout._absolute_without_following(selected)
                    with self.assertRaises(OSError):
                        if writer == "store":
                            json_store.update_json(selected / "projects.json", [], mutator)
                        else:
                            with (
                                patch.object(server, "DATA_DIR", approved),
                                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                                patch.object(
                                    server,
                                    "DATA_MUTATION_LOCK",
                                    writer != "server_development",
                                ),
                            ):
                                server.update_json_file("projects.json", [], mutator)

                    self.assertEqual((displaced / "projects.json").read_bytes(), selected_before)
                    self.assertEqual((outside / "projects.json").read_bytes(), outside_before)
                    self.assertFalse((outside / data_layout.INITIALIZATION_LOCK_NAME).exists())

    def test_development_json_write_is_pinned_with_restore_coordination_lock(self):
        with TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "data"
            self.write_inventory(target, private=True)
            approved = data_layout._absolute_without_following(target)
            with (
                patch.object(server, "DATA_DIR", approved),
                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                patch.object(server, "DATA_MUTATION_LOCK", False),
            ):
                result = server.update_json_file(
                    "projects.json",
                    [],
                    lambda _current: ([{"id": "development-write"}], "ok"),
                )
            self.assertEqual(result, "ok")
            self.assertEqual(
                json.loads((target / "projects.json").read_text(encoding="utf-8")),
                [{"id": "development-write"}],
            )
            lock_path = target / data_layout.INITIALIZATION_LOCK_NAME
            self.assertTrue(lock_path.is_file())
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)

    def test_successful_product_writes_cannot_break_schema_shape_or_size(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(self.config(target)))
            approved = data_layout._absolute_without_following(target)
            before = (target / "tasks.json").read_bytes()
            common = (
                patch.object(server, "DATA_DIR", approved),
                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                patch.object(server, "DATA_MUTATION_LOCK", True),
                patch.object(server, "MAX_PREFLIGHT_JSON_BYTES", 128),
            )
            with common[0], common[1], common[2], common[3]:
                with self.assertRaises(ValueError):
                    server.update_json_file(
                        "tasks.json",
                        [],
                        lambda _current: ({"wrong": "shape"}, None),
                    )
                with self.assertRaises(ValueError):
                    server.update_json_file(
                        "tasks.json",
                        [],
                        lambda _current: ([{"text": "x" * 256}], None),
                    )
            self.assertEqual((target / "tasks.json").read_bytes(), before)
            self.assertEqual(data_schema.schema_startup_status(target), "current")

    def test_windows_product_write_rejects_file_reparse_point(self):
        if os.name != "nt":
            self.skipTest("native Windows file-reparse regression")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target"
            outside = root / "outside.json"
            self.write_inventory(target, private=True)
            outside.write_text('[]\n', encoding="utf-8")
            selected = target / "tasks.json"
            selected.unlink()
            try:
                selected.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"file symlink unavailable: {exc}")
            approved = data_layout._absolute_without_following(target)
            with (
                patch.object(server, "DATA_DIR", approved),
                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                patch.object(server, "DATA_MUTATION_LOCK", True),
            ):
                with self.assertRaises(OSError):
                    server.update_json_file(
                        "tasks.json",
                        [],
                        lambda current: (current, None),
                    )
            self.assertEqual(outside.read_text(encoding="utf-8"), "[]\n")

    def test_newer_manifest_refuses_recovery_without_deleting_temporary(self):
        for kind in ("backup", "manifest"):
            with self.subTest(kind=kind), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                ready = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                token = ready.confirmation_token or ""
                backup_raw = data_schema._build_backup(ready._snapshots, token)
                manifest = data_schema._manifest_document(
                    origin="schema_migration",
                    backup_name=data_schema._backup_name(token),
                    backup_sha256=data_schema._digest(backup_raw),
                )
                manifest["format_version"] = 2
                manifest_path = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                manifest_path.write_bytes(data_schema._canonical_json(manifest))
                if os.name == "posix":
                    manifest_path.chmod(0o600)
                if kind == "backup":
                    temporary = target / "backups" / (
                        f".{data_schema._backup_name(token)}.mentat-init-" + "2" * 32 + ".tmp"
                    )
                    temporary.write_bytes(backup_raw)
                else:
                    temporary = target / "config" / (
                        ".data-schema.json.mentat-init-" + "3" * 32 + ".tmp"
                    )
                    temporary.write_bytes(data_schema._canonical_json(manifest))
                if os.name == "posix":
                    temporary.chmod(0o600)
                before = temporary.read_bytes()

                preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                self.assertEqual(preview.status, "newer_unsupported")
                self.assertIsNone(preview.confirmation_token)
                result = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=token,
                    home=root / "home",
                )
                self.assertEqual(result.status, "blocked")
                self.assertEqual(temporary.read_bytes(), before)

    def test_reserved_schema_temporary_lookalikes_fail_closed(self):
        for directory, name in (
            ("config", ".data-schema.json.mentat-init-nothex.tmp"),
            ("backups", ".data-schema-v1-notatoken.zip.mentat-init-nothex.tmp"),
        ):
            with self.subTest(scope="explicit", directory=directory), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                lookalike = target / directory / name
                lookalike.write_bytes(b"ambiguous")
                if os.name == "posix":
                    lookalike.chmod(0o600)
                preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                self.assertEqual(preview.status, "unsafe")
                self.assertIsNone(preview.confirmation_token)
                self.assertEqual(lookalike.read_bytes(), b"ambiguous")

        for scope, relative in (
            ("reservation", "..data-schema-fresh-v1.reservation.mentat-init-nothex.tmp"),
            ("seed", ".tasks.json.mentat-init-nothex.tmp"),
            ("manifest", "config/.data-schema.json.mentat-init-nothex.tmp"),
            ("backup", "backups/.data-schema-v1-notatoken.zip.mentat-init-nothex.tmp"),
        ):
            with self.subTest(scope="fresh_" + scope), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                if scope != "reservation":
                    reservation = target / data_schema.FRESH_SCHEMA_RESERVATION_NAME
                    reservation.write_bytes(data_schema._fresh_manifest_raw())
                    if os.name == "posix":
                        reservation.chmod(0o600)
                lookalike = target / relative
                lookalike.write_bytes(b"ambiguous")
                if os.name == "posix":
                    lookalike.chmod(0o600)
                before = self.snapshot(target)
                config = self.config(target)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    error = runtime_config.prepare_data_root_for_startup(config)
                self.assertIn("invalid_data_schema", error or "")
                self.assertEqual(before, self.snapshot(target))

    def test_cross_category_lookalikes_block_all_recovery_mutation(self):
        cases = (
            (
                "manifest_exact_backup_lookalike",
                "config/.data-schema.json.mentat-init-" + "a" * 32 + ".tmp",
                "backups/.data-schema-v1-bad.zip.mentat-init-nothex.tmp",
            ),
            (
                "backup_exact_config_lookalike",
                "backups/.data-schema-v1-" + "b" * 24 + ".zip.mentat-init-" + "c" * 32 + ".tmp",
                "config/.data-schema.json.mentat-init-nothex.tmp",
            ),
        )
        for label, exact_relative, lookalike_relative in cases:
            with self.subTest(label=label), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                for relative, raw in ((exact_relative, b"exact"), (lookalike_relative, b"ambiguous")):
                    path = target / relative
                    path.write_bytes(raw)
                    if os.name == "posix":
                        path.chmod(0o600)
                before = self.snapshot(target)
                preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                self.assertEqual(preview.status, "unsafe")
                self.assertIsNone(preview.confirmation_token)
                self.assertEqual(before, self.snapshot(target))

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            reservation = target / data_schema.FRESH_SCHEMA_RESERVATION_NAME
            reservation.write_bytes(data_schema._fresh_manifest_raw())
            exact = target / "config" / (
                ".data-schema.json.mentat-init-" + "d" * 32 + ".tmp"
            )
            exact.write_bytes(data_schema._fresh_manifest_raw())
            lookalike = target / "backups" / ".data-schema-v1-bad.zip.mentat-init-nothex.tmp"
            lookalike.write_bytes(b"ambiguous")
            if os.name == "posix":
                reservation.chmod(0o600)
                exact.chmod(0o600)
                lookalike.chmod(0o600)
            before = self.snapshot(target)
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                error = runtime_config.prepare_data_root_for_startup(self.config(target))
            self.assertIn("invalid_data_schema", error or "")
            self.assertEqual(before, self.snapshot(target))

    def test_recovery_post_inventory_prevents_stale_success_claim(self):
        for case in ("manifest", "backup"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                ready = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                token = ready.confirmation_token or ""
                if case == "manifest":
                    temporary = target / "config" / (
                        ".data-schema.json.mentat-init-" + "9" * 32 + ".tmp"
                    )
                    temporary.write_bytes(b"interrupted-manifest")
                    injected = target / "backups" / (
                        ".data-schema-v1-bad.zip.mentat-init-nothex.tmp"
                    )
                else:
                    backup_raw = data_schema._build_backup(ready._snapshots, token)
                    backup_name = data_schema._backup_name(token)
                    temporary = target / "backups" / (
                        f".{backup_name}.mentat-init-" + "a" * 32 + ".tmp"
                    )
                    temporary.write_bytes(backup_raw)
                    injected = target / "config" / (
                        ".data-schema.json.mentat-init-nothex.tmp"
                    )
                if os.name == "posix":
                    temporary.chmod(0o600)
                recovery = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                self.assertEqual(recovery.status, "recovery_required")
                real_unlink = data_schema._unlink_relative

                def inject_after_unlink(path, descriptor):
                    real_unlink(path, descriptor)
                    injected.write_bytes(b"ambiguous")
                    if os.name == "posix":
                        injected.chmod(0o600)

                with patch.object(data_schema, "_unlink_relative", side_effect=inject_after_unlink):
                    result = data_schema.migrate_data_schema(
                        seeds,
                        target,
                        confirmation_token=recovery.confirmation_token or "",
                        home=root / "home",
                    )

                self.assertEqual(result.status, "partial_failure")
                self.assertFalse(temporary.exists())
                self.assertTrue(injected.exists())
                self.assertEqual(
                    data_schema.preview_schema_migration(seeds, target, home=root / "home").status,
                    "unsafe",
                )

    def test_recovery_requires_exact_valid_next_state_and_live_bytes(self):
        for case in ("invalid_backup", "changed_live_bytes"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                ready = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                token = ready.confirmation_token or ""
                temporary = target / "config" / (
                    ".data-schema.json.mentat-init-" + "b" * 32 + ".tmp"
                )
                if case == "invalid_backup":
                    backup_name = data_schema._backup_name(token)
                    backup = target / "backups" / backup_name
                    backup.write_bytes(b"not-a-valid-schema-backup")
                    manifest = data_schema._manifest_document(
                        origin="schema_migration",
                        backup_name=backup_name,
                        backup_sha256=data_schema._digest(backup.read_bytes()),
                    )
                    temporary.write_bytes(data_schema._canonical_json(manifest))
                    if os.name == "posix":
                        backup.chmod(0o600)
                else:
                    temporary.write_bytes(b"interrupted-manifest")
                if os.name == "posix":
                    temporary.chmod(0o600)
                recovery = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                self.assertEqual(recovery.status, "recovery_required")
                real_post_state = data_schema._recovery_post_state_pinned
                changed = False

                def change_after_post_preview(*args, **kwargs):
                    nonlocal changed
                    valid = real_post_state(*args, **kwargs)
                    if case == "changed_live_bytes" and valid and not changed:
                        changed = True
                        tasks = target / "tasks.json"
                        tasks.write_text('[{"id":"changed-after-recovery"}]\n', encoding="utf-8")
                        if os.name == "posix":
                            tasks.chmod(0o600)
                    return valid

                with patch.object(
                    data_schema,
                    "_recovery_post_state_pinned",
                    side_effect=change_after_post_preview,
                ):
                    result = data_schema.migrate_data_schema(
                        seeds,
                        target,
                        confirmation_token=recovery.confirmation_token or "",
                        home=root / "home",
                    )

                self.assertEqual(result.status, "partial_failure")
                self.assertFalse(temporary.exists())

    def test_startup_prioritizes_newer_schema_over_recovery_artifacts(self):
        for artifact in ("lookalike", "reservation", "temporary"):
            with self.subTest(artifact=artifact), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(self.config(target)))
                manifest_path = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["format_version"] = 2
                manifest_path.write_bytes(data_schema._canonical_json(manifest))
                if artifact == "lookalike":
                    path = target / "config" / ".data-schema.json.mentat-init-nothex.tmp"
                    path.write_bytes(b"ambiguous")
                elif artifact == "reservation":
                    path = target / data_schema.FRESH_SCHEMA_RESERVATION_NAME
                    path.write_bytes(data_schema._fresh_manifest_raw())
                else:
                    path = target / "config" / (
                        ".data-schema.json.mentat-init-" + "e" * 32 + ".tmp"
                    )
                    path.write_bytes(data_schema._canonical_json(manifest))
                if os.name == "posix":
                    manifest_path.chmod(0o600)
                    path.chmod(0o600)
                before = self.snapshot(target)
                self.assertEqual(data_schema.schema_preflight_status(target), "newer")
                self.assertEqual(data_schema.schema_startup_status(target), "newer")
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    error = runtime_config.prepare_data_root_for_startup(self.config(target))
                self.assertIn("schema_version_newer_than_supported", error or "")
                self.assertEqual(before, self.snapshot(target))

    def test_resume_rejects_semantically_equal_byte_different_backup(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
            real_publish = data_schema._publish_raw_missing

            def interrupt_manifest(path, *args, **kwargs):
                if Path(path).name == data_schema.SCHEMA_MANIFEST_NAME:
                    raise OSError("simulated interruption")
                return real_publish(path, *args, **kwargs)

            with patch.object(data_schema, "_publish_raw_missing", side_effect=interrupt_manifest):
                result = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=preview.confirmation_token or "",
                    home=root / "home",
                )
            self.assertEqual(result.status, "partial_failure")
            backup = next((target / "backups").glob("data-schema-v1-*.zip"))
            with zipfile.ZipFile(backup, "a") as archive:
                archive.comment = b"byte-different"
            if os.name == "posix":
                backup.chmod(0o600)
            retry = data_schema.preview_schema_migration(seeds, target, home=root / "home")
            self.assertEqual(retry.status, "unsafe")
            self.assertFalse((target / "config" / data_schema.SCHEMA_MANIFEST_NAME).exists())

    def test_malformed_manifest_and_zip_fail_closed_without_traceback(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            manifest = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
            manifest.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")
            if os.name == "posix":
                manifest.chmod(0o600)
            self.assertEqual(data_schema.schema_preflight_status(target), "invalid")
            self.assertEqual(data_schema.schema_startup_status(target), "invalid")
            self.assertEqual(
                data_schema.preview_schema_migration(seeds, target, home=root / "home").status,
                "unsafe",
            )

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
            result = data_schema.migrate_data_schema(
                seeds,
                target,
                confirmation_token=preview.confirmation_token or "",
                home=root / "home",
            )
            self.assertEqual(result.status, "migrated")
            manifest_path = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            backup = target / "backups" / manifest["backup"]["name"]
            raw = bytearray(backup.read_bytes())
            local = raw.index(b"PK\x03\x04")
            central = raw.index(b"PK\x01\x02")
            raw[local + 6 : local + 8] = (
                int.from_bytes(raw[local + 6 : local + 8], "little") | 1
            ).to_bytes(2, "little")
            raw[central + 8 : central + 10] = (
                int.from_bytes(raw[central + 8 : central + 10], "little") | 1
            ).to_bytes(2, "little")
            backup.write_bytes(raw)
            if os.name == "posix":
                backup.chmod(0o600)
            manifest["backup"]["sha256"] = data_schema._digest(bytes(raw))
            manifest_path.write_bytes(data_schema._canonical_json(manifest))
            self.assertEqual(data_schema.schema_startup_status(target), "invalid")
            self.assertEqual(
                data_schema.preview_schema_migration(seeds, target, home=root / "home").status,
                "unsafe",
            )

    def test_boolean_schema_versions_are_invalid(self):
        for case in ("format", "document"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                config = self.config(target)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                manifest_path = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if case == "format":
                    manifest["format_version"] = True
                else:
                    manifest["documents"][0]["version"] = True
                manifest_path.write_bytes(data_schema._canonical_json(manifest))
                self.assertEqual(data_schema.schema_startup_status(target), "invalid")

        for case in ("backup_format", "backup_from", "backup_size"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                result = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=preview.confirmation_token or "",
                    home=root / "home",
                )
                self.assertEqual(result.status, "migrated")
                manifest_path = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                backup = target / "backups" / manifest["backup"]["name"]
                with zipfile.ZipFile(backup, "r") as archive:
                    entries = {name: archive.read(name) for name in archive.namelist()}
                backup_manifest = json.loads(entries["manifest.json"])
                if case == "backup_format":
                    backup_manifest["format_version"] = True
                elif case == "backup_from":
                    backup_manifest["from_version"] = False
                else:
                    backup_manifest["items"][0]["size"] = True
                entries["manifest.json"] = data_schema._canonical_json(backup_manifest)
                with zipfile.ZipFile(backup, "w", compression=zipfile.ZIP_STORED) as archive:
                    for name in [
                        "manifest.json",
                        *(f"data/{item}" for item in data_layout.SEED_FILE_NAMES),
                    ]:
                        archive.writestr(data_schema._zip_entry(name), entries[name])
                if os.name == "posix":
                    backup.chmod(0o600)
                manifest["backup"]["sha256"] = data_schema._digest(backup.read_bytes())
                manifest_path.write_bytes(data_schema._canonical_json(manifest))
                self.assertEqual(data_schema.schema_startup_status(target), "invalid")

    def test_clean_initialization_reservation_recovers_both_crash_windows(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            config = self.config(target)
            real_copy = data_layout._copy_seed_missing_only
            calls = 0

            def interrupt_after_one(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    return "simulated_interruption"
                return real_copy(*args, **kwargs)

            with (
                patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds),
                patch.object(data_layout, "_copy_seed_missing_only", side_effect=interrupt_after_one),
            ):
                self.assertIn(
                    "simulated_interruption",
                    runtime_config.prepare_data_root_for_startup(config) or "",
                )
            self.assertTrue((target / data_schema.FRESH_SCHEMA_RESERVATION_NAME).exists())
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
            self.assertEqual(data_schema.schema_startup_status(target), "current")

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            target.mkdir()
            if os.name == "posix":
                target.chmod(0o700)
            temporary = target / (
                "..data-schema-fresh-v1.reservation.mentat-init-"
                + "a" * 32
                + ".tmp"
            )
            temporary.write_bytes(b"interrupted reservation")
            if os.name == "posix":
                temporary.chmod(0o600)
            config = self.config(target)
            self.assertEqual(data_schema.schema_preflight_status(target), "fresh_incomplete")
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
            self.assertFalse(temporary.exists())
            self.assertEqual(data_schema.schema_startup_status(target), "current")

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            config = self.config(target)
            with (
                patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds),
                patch.object(
                    runtime_config,
                    "initialize_fresh_schema_under_lock",
                    return_value="simulated_crash",
                ),
            ):
                self.assertIn("simulated_crash", runtime_config.prepare_data_root_for_startup(config) or "")
            self.assertTrue(all((target / name).exists() for name in data_layout.SEED_FILE_NAMES))
            self.assertTrue((target / data_schema.FRESH_SCHEMA_RESERVATION_NAME).exists())
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
            self.assertEqual(data_schema.schema_startup_status(target), "current")

    def test_clean_initialization_reconciles_seed_and_manifest_promotion_windows(self):
        for case in ("seed_prelink", "seed_postlink", "manifest_prelink", "manifest_postlink"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                reservation = target / data_schema.FRESH_SCHEMA_RESERVATION_NAME
                reservation.write_bytes(data_schema._fresh_manifest_raw())
                if os.name == "posix":
                    reservation.chmod(0o600)
                selected = target / data_layout.SEED_FILE_NAMES[0]
                if case.startswith("seed"):
                    for name in data_layout.SEED_FILE_NAMES[1:]:
                        (target / name).unlink()
                    temporary = target / (
                        f".{selected.name}.mentat-init-" + "b" * 32 + ".tmp"
                    )
                    if case == "seed_prelink":
                        selected.unlink()
                        temporary.write_bytes(b"partial")
                    else:
                        os.link(selected, temporary)
                    if os.name == "posix":
                        temporary.chmod(0o600)
                else:
                    temporary = target / "config" / (
                        ".data-schema.json.mentat-init-" + "c" * 32 + ".tmp"
                    )
                    if case == "manifest_prelink":
                        temporary.write_bytes(b"partial")
                    else:
                        manifest = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                        manifest.write_bytes(data_schema._fresh_manifest_raw())
                        if os.name == "posix":
                            manifest.chmod(0o600)
                        os.link(manifest, temporary)
                    if os.name == "posix":
                        temporary.chmod(0o600)
                config = self.config(target)
                self.assertEqual(data_schema.schema_preflight_status(target), "fresh_incomplete")

                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))

                self.assertFalse(temporary.exists())
                self.assertFalse(reservation.exists())
                self.assertEqual(data_schema.schema_startup_status(target), "current")
                self.assertEqual(
                    {name: (target / name).read_bytes() for name in data_layout.SEED_FILE_NAMES},
                    {name: (seeds / name).read_bytes() for name in data_layout.SEED_FILE_NAMES},
                )

    def test_fresh_recovery_never_redirects_deletion_to_replacement_root(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        for case in ("reservation", "seed", "manifest"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                displaced = root / "displaced"
                self.write_inventory(seeds)
                if case == "reservation":
                    target.mkdir(mode=0o700)
                    relative = Path(
                        "..data-schema-fresh-v1.reservation.mentat-init-"
                        + "4" * 32
                        + ".tmp"
                    )
                    temporary = target / relative
                    temporary.write_bytes(b"partial")
                else:
                    self.write_inventory(target, private=True)
                    reservation = target / data_schema.FRESH_SCHEMA_RESERVATION_NAME
                    reservation.write_bytes(data_schema._fresh_manifest_raw())
                    reservation.chmod(0o600)
                    if case == "seed":
                        selected = target / data_layout.SEED_FILE_NAMES[0]
                        relative = Path(
                            f".{selected.name}.mentat-init-" + "5" * 32 + ".tmp"
                        )
                        temporary = target / relative
                        os.link(selected, temporary)
                    else:
                        manifest = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                        manifest.write_bytes(data_schema._fresh_manifest_raw())
                        manifest.chmod(0o600)
                        relative = Path("config") / (
                            ".data-schema.json.mentat-init-" + "6" * 32 + ".tmp"
                        )
                        temporary = target / relative
                        os.link(manifest, temporary)
                temporary.chmod(0o600)
                replacement_raw = temporary.read_bytes()
                self.assertEqual(data_schema.schema_preflight_status(target), "fresh_incomplete")
                real_issue = data_schema._schema_artifact_issue_pinned
                substituted = False

                def substitute_after_pinned_inventory(selected, descriptor):
                    nonlocal substituted
                    issue = real_issue(selected, descriptor)
                    if issue == "fresh_schema_initialization_incomplete" and not substituted:
                        substituted = True
                        target.rename(displaced)
                        (target / relative.parent).mkdir(parents=True, exist_ok=True)
                        replacement = target / relative
                        replacement.write_bytes(replacement_raw)
                        replacement.chmod(0o600)
                    return issue

                with (
                    patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds),
                    patch.object(
                        data_schema,
                        "_schema_artifact_issue_pinned",
                        side_effect=substitute_after_pinned_inventory,
                    ),
                ):
                    error = runtime_config.prepare_data_root_for_startup(self.config(target))

                self.assertTrue(substituted)
                self.assertIsNotNone(error)
                self.assertEqual((target / relative).read_bytes(), replacement_raw)

    def test_explicit_recovery_handles_promoted_backup_and_manifest_pairs(self):
        for case in ("backup", "manifest"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                token = preview.confirmation_token or ""
                snapshots = preview._snapshots
                backup_name = data_schema._backup_name(token)
                backup_raw = data_schema._build_backup(snapshots, token)
                backup = target / "backups" / backup_name
                backup.write_bytes(backup_raw)
                if os.name == "posix":
                    backup.chmod(0o600)
                if case == "backup":
                    temporary = target / "backups" / (
                        f".{backup_name}.mentat-init-" + "d" * 32 + ".tmp"
                    )
                    os.link(backup, temporary)
                else:
                    manifest_raw = data_schema._canonical_json(
                        data_schema._manifest_document(
                            origin="schema_migration",
                            backup_name=backup_name,
                            backup_sha256=data_schema._digest(backup_raw),
                        )
                    )
                    manifest = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                    manifest.write_bytes(manifest_raw)
                    if os.name == "posix":
                        manifest.chmod(0o600)
                    temporary = target / "config" / (
                        ".data-schema.json.mentat-init-" + "e" * 32 + ".tmp"
                    )
                    os.link(manifest, temporary)
                if os.name == "posix":
                    temporary.chmod(0o600)

                recovery = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                self.assertEqual(recovery.status, "recovery_required")
                reconciled = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=recovery.confirmation_token or "",
                    home=root / "home",
                )
                self.assertEqual(reconciled.status, "reconciled")
                self.assertFalse(temporary.exists())
                after = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                self.assertEqual(
                    after.status,
                    "resume_required" if case == "backup" else "already_current",
                )

    def test_explicit_recovery_keeps_validation_and_deletion_on_pinned_root(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        for case in ("backup", "manifest"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                displaced = root / "displaced"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                token = preview.confirmation_token or ""
                backup_name = data_schema._backup_name(token)
                backup_raw = data_schema._build_backup(preview._snapshots, token)
                backup = target / "backups" / backup_name
                backup.write_bytes(backup_raw)
                if os.name == "posix":
                    backup.chmod(0o600)
                if case == "backup":
                    relative = Path("backups") / (
                        f".{backup_name}.mentat-init-" + "7" * 32 + ".tmp"
                    )
                    final = backup
                else:
                    manifest_raw = data_schema._canonical_json(
                        data_schema._manifest_document(
                            origin="schema_migration",
                            backup_name=backup_name,
                            backup_sha256=data_schema._digest(backup_raw),
                        )
                    )
                    final = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                    final.write_bytes(manifest_raw)
                    if os.name == "posix":
                        final.chmod(0o600)
                    relative = Path("config") / (
                        ".data-schema.json.mentat-init-" + "8" * 32 + ".tmp"
                    )
                temporary = target / relative
                os.link(final, temporary)
                recovery = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                self.assertEqual(recovery.status, "recovery_required")
                expected_issue = (
                    "incomplete_schema_backup_temporary"
                    if case == "backup"
                    else "incomplete_schema_manifest_temporary"
                )
                real_issue = data_schema._schema_artifact_issue_pinned
                substituted = False
                replacement_raw = temporary.read_bytes()

                def substitute_after_pinned_inventory(selected, descriptor):
                    nonlocal substituted
                    issue = real_issue(selected, descriptor)
                    if issue == expected_issue and not substituted:
                        substituted = True
                        target.rename(displaced)
                        (target / relative.parent).mkdir(parents=True)
                        replacement = target / relative
                        replacement.write_bytes(replacement_raw)
                        if os.name == "posix":
                            replacement.chmod(0o600)
                    return issue

                with patch.object(
                    data_schema,
                    "_schema_artifact_issue_pinned",
                    side_effect=substitute_after_pinned_inventory,
                ):
                    result = data_schema.migrate_data_schema(
                        seeds,
                        target,
                        confirmation_token=recovery.confirmation_token or "",
                        home=root / "home",
                    )

                self.assertTrue(substituted)
                self.assertEqual(result.status, "partial_failure")
                self.assertFalse((displaced / relative).exists())
                self.assertEqual((target / relative).read_bytes(), replacement_raw)

    def test_recovery_rejects_or_detects_a_second_temporary_without_deletion(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            manifest_temporary = target / "config" / (
                ".data-schema.json.mentat-init-" + "f" * 32 + ".tmp"
            )
            manifest_temporary.write_bytes(b"partial")
            if os.name == "posix":
                manifest_temporary.chmod(0o600)
            recovery = data_schema.preview_schema_migration(seeds, target, home=root / "home")
            self.assertEqual(recovery.status, "recovery_required")
            token = data_schema._preview_token(target, recovery._snapshots)
            backup_temporary = target / "backups" / (
                f".{data_schema._backup_name(token)}.mentat-init-" + "1" * 32 + ".tmp"
            )
            backup_temporary.write_bytes(b"partial")
            if os.name == "posix":
                backup_temporary.chmod(0o600)

            changed = data_schema.migrate_data_schema(
                seeds,
                target,
                confirmation_token=recovery.confirmation_token or "",
                home=root / "home",
            )

            self.assertEqual(changed.status, "blocked")
            self.assertTrue(manifest_temporary.exists())
            self.assertTrue(backup_temporary.exists())
            repeated = data_schema.preview_schema_migration(seeds, target, home=root / "home")
            self.assertEqual(repeated.status, "unsafe")
            self.assertIsNone(repeated.confirmation_token)

    def test_clean_initialization_records_current_schema_and_repeat_is_idempotent(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            config = self.config(target)

            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                first = self.snapshot(target)
                self.assertEqual(data_schema.schema_startup_status(target), "current")
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                self.assertEqual(first, self.snapshot(target))

            manifest = json.loads(
                (target / "config" / data_schema.SCHEMA_MANIFEST_NAME).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["origin"], "fresh_seed")
            self.assertIsNone(manifest["backup"])

    def test_fresh_terminal_success_remains_exactly_seed_bound(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            real_status = data_schema._schema_status_pinned
            changed = False

            def change_after_terminal_status(selected, descriptor, **kwargs):
                nonlocal changed
                status = real_status(selected, descriptor, **kwargs)
                if (
                    status == "current"
                    and not changed
                    and not (target / data_schema.FRESH_SCHEMA_RESERVATION_NAME).exists()
                ):
                    changed = True
                    tasks = target / "tasks.json"
                    tasks.write_text('[{"id":"changed-after-fresh"}]\n', encoding="utf-8")
                    if os.name == "posix":
                        tasks.chmod(0o600)
                return status

            with (
                patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds),
                patch.object(
                    data_schema,
                    "_schema_status_pinned",
                    side_effect=change_after_terminal_status,
                ),
            ):
                error = runtime_config.prepare_data_root_for_startup(self.config(target))

            self.assertTrue(changed)
            self.assertIsNotNone(error)

    def test_existing_unversioned_root_remains_supported(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            config = self.config(target)

            self.assertEqual(data_schema.schema_startup_status(target), "legacy")
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
            self.assertEqual(data_schema.schema_startup_status(target), "legacy")

    def test_newer_manifest_and_document_versions_are_refused(self):
        for case in ("format", "document"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                config = self.config(target)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                manifest_path = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if case == "format":
                    manifest["format_version"] = 99
                else:
                    manifest["documents"][0]["version"] = 99
                manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
                self.assertEqual(data_schema.schema_startup_status(target), "newer")
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    error = runtime_config.prepare_data_root_for_startup(config)
                self.assertIn("schema_version_newer_than_supported", error or "")

    def test_invalid_manifest_backup_and_interruption_artifacts_fail_closed(self):
        for case in (
            "manifest_mode",
            "manifest_link",
            "manifest_hardlink",
            "backup_corrupt",
            "backup_missing",
            "backup_hardlink",
        ):
            if case == "manifest_mode" and os.name != "posix":
                continue
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                preview = data_schema.preview_schema_migration(
                    seeds,
                    target,
                    home=root / "home",
                )
                result = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=preview.confirmation_token or "",
                    home=root / "home",
                )
                self.assertEqual(result.status, "migrated")
                manifest_path = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                backup_path = target / "backups" / manifest["backup"]["name"]
                if case == "manifest_mode":
                    manifest_path.chmod(0o644)
                elif case == "manifest_link":
                    original = target / "config" / "original-manifest.json"
                    manifest_path.rename(original)
                    try:
                        manifest_path.symlink_to(original)
                    except OSError:
                        self.skipTest("file symlink creation unavailable")
                elif case == "manifest_hardlink":
                    original = target / "config" / "original-manifest.json"
                    manifest_path.rename(original)
                    try:
                        os.link(original, manifest_path)
                    except OSError:
                        self.skipTest("file hard-link creation unavailable")
                elif case == "backup_corrupt":
                    backup_path.write_bytes(b"not-a-schema-backup")
                elif case == "backup_hardlink":
                    original = target / "backups" / "original-backup.zip"
                    backup_path.rename(original)
                    try:
                        os.link(original, backup_path)
                    except OSError:
                        self.skipTest("file hard-link creation unavailable")
                else:
                    backup_path.unlink()
                self.assertEqual(data_schema.schema_startup_status(target), "invalid")
                self.assertEqual(
                    data_schema.preview_schema_migration(
                        seeds,
                        target,
                        home=root / "home",
                    ).status,
                    "unsafe",
                )

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target"
            self.write_inventory(target, private=True)
            temporary = target / "backups" / (
                ".data-schema-v1-"
                + "0" * 24
                + ".zip.mentat-init-"
                + "1" * 32
                + ".tmp"
            )
            temporary.write_bytes(b"interrupted")
            if os.name == "posix":
                temporary.chmod(0o600)
            self.assertEqual(data_schema.schema_startup_status(target), "invalid")

    def test_current_schema_rejects_unsafe_or_invalid_live_documents(self):
        for case in ("wrong_shape", "broad_mode", "missing", "symlink", "hardlink"):
            if case == "broad_mode" and os.name != "posix":
                continue
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                outside = root / "outside.json"
                self.write_inventory(seeds)
                config = self.config(target)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                selected = target / "tasks.json"
                outside.write_text("[]\n", encoding="utf-8")
                if os.name == "posix":
                    outside.chmod(0o600)
                if case == "wrong_shape":
                    selected.write_text("{}\n", encoding="utf-8")
                elif case == "broad_mode":
                    selected.chmod(0o644)
                elif case == "missing":
                    selected.unlink()
                elif case == "symlink":
                    selected.unlink()
                    try:
                        selected.symlink_to(outside)
                    except OSError:
                        self.skipTest("file symlink creation unavailable")
                else:
                    selected.unlink()
                    try:
                        os.link(outside, selected)
                    except OSError:
                        self.skipTest("file hard-link creation unavailable")
                self.assertEqual(data_schema.schema_startup_status(target), "invalid")

    def test_current_manifest_semantics_are_fixed_inventory(self):
        for case in ("unknown_field", "missing_document", "older_document"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                self.write_inventory(seeds)
                config = self.config(target)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                manifest_path = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if case == "unknown_field":
                    manifest["extra"] = True
                elif case == "missing_document":
                    manifest["documents"].pop()
                else:
                    manifest["documents"][0]["version"] = 0
                manifest_path.write_bytes(data_schema._canonical_json(manifest))
                if os.name == "posix":
                    manifest_path.chmod(0o600)
                self.assertEqual(data_schema.schema_startup_status(target), "invalid")

    def test_manifest_hash_cannot_bless_semantically_forged_schema_backup(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            preview = data_schema.preview_schema_migration(
                seeds,
                target,
                home=root / "home",
            )
            result = data_schema.migrate_data_schema(
                seeds,
                target,
                confirmation_token=preview.confirmation_token or "",
                home=root / "home",
            )
            self.assertEqual(result.status, "migrated")
            manifest_path = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            backup_path = target / "backups" / manifest["backup"]["name"]
            with zipfile.ZipFile(backup_path, "r") as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            backup_manifest = json.loads(entries["manifest.json"])
            backup_manifest["token_sha256"] = "f" * 64
            entries["manifest.json"] = data_schema._canonical_json(backup_manifest)
            with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_STORED) as archive:
                for name in [
                    "manifest.json",
                    *(f"data/{item}" for item in data_layout.SEED_FILE_NAMES),
                ]:
                    archive.writestr(name, entries[name])
            if os.name == "posix":
                backup_path.chmod(0o600)
            backup_raw = backup_path.read_bytes()
            manifest["backup"]["sha256"] = data_schema._digest(backup_raw)
            manifest_path.write_bytes(data_schema._canonical_json(manifest))
            if os.name == "posix":
                manifest_path.chmod(0o600)

            self.assertEqual(data_schema.schema_startup_status(target), "invalid")

    def test_schema_migration_serializes_with_normal_durable_json_writes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            preview = data_schema.preview_schema_migration(
                seeds,
                target,
                home=root / "home",
            )
            migration_inside_lock = Event()
            release_migration = Event()
            writer_done = Event()
            migration_result: list[data_schema.SchemaResult] = []
            real_build = data_schema._build_backup

            def pause_backup(*args, **kwargs):
                migration_inside_lock.set()
                self.assertTrue(release_migration.wait(10))
                return real_build(*args, **kwargs)

            def run_migration():
                with patch.object(data_schema, "_build_backup", side_effect=pause_backup):
                    migration_result.append(
                        data_schema.migrate_data_schema(
                            seeds,
                            target,
                            confirmation_token=preview.confirmation_token or "",
                            home=root / "home",
                        )
                    )

            def run_writer():
                json_store.update_json(
                    target / "tasks.json",
                    [],
                    lambda _current: ([{"id": "serialized-writer"}], None),
                )
                writer_done.set()

            migration_thread = Thread(target=run_migration)
            writer_thread = Thread(target=run_writer)
            migration_thread.start()
            self.assertTrue(migration_inside_lock.wait(10))
            writer_thread.start()
            self.assertFalse(writer_done.wait(0.2))
            release_migration.set()
            migration_thread.join(10)
            writer_thread.join(10)

            self.assertFalse(migration_thread.is_alive())
            self.assertFalse(writer_thread.is_alive())
            self.assertEqual(migration_result[0].status, "migrated")
            self.assertTrue(writer_done.is_set())
            self.assertEqual(data_schema.schema_startup_status(target), "current")

    def test_pinned_root_blocks_startup_and_migration_substitution(self):
        if os.name == "nt":
            self.skipTest("Windows directory guards prevent injected rename natively")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            displaced = root / "displaced"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            preview = data_schema.preview_schema_migration(
                seeds,
                target,
                home=root / "home",
            )
            real_build = data_schema._build_backup

            def substitute_during_build(*args, **kwargs):
                raw = real_build(*args, **kwargs)
                target.rename(displaced)
                target.mkdir()
                return raw

            with patch.object(
                data_schema,
                "_build_backup",
                side_effect=substitute_during_build,
            ):
                result = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=preview.confirmation_token or "",
                    home=root / "home",
                )
            self.assertEqual(result.status, "blocked")
            self.assertEqual(list(target.iterdir()), [])
            self.assertFalse((displaced / "config" / data_schema.SCHEMA_MANIFEST_NAME).exists())

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            displaced = root / "displaced"
            self.write_inventory(seeds)
            config = self.config(target)
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
            real_status = data_schema._schema_status_pinned
            substituted = False

            def substitute_after_validation(*args, **kwargs):
                nonlocal substituted
                status = real_status(*args, **kwargs)
                if status == "current" and not substituted:
                    substituted = True
                    target.rename(displaced)
                    target.mkdir()
                return status

            with patch.object(
                data_schema,
                "_schema_status_pinned",
                side_effect=substitute_after_validation,
            ):
                self.assertEqual(data_schema.schema_startup_status(target), "invalid")
            self.assertTrue(substituted)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(data_schema.schema_startup_status(displaced), "current")

    def test_schema_mutations_use_pinned_root_before_first_directory_write(self):
        if os.name == "nt":
            self.skipTest("Windows directory guards prevent injected rename natively")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            displaced = root / "displaced"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
            real_match = data_schema._pinned_target_matches
            swapped = False

            def substitute_on_first_match(path, descriptor):
                nonlocal swapped
                matched = real_match(path, descriptor)
                if matched and not swapped:
                    swapped = True
                    target.rename(displaced)
                    target.mkdir(mode=0o755)
                return matched

            with patch.object(
                data_schema,
                "_pinned_target_matches",
                side_effect=substitute_on_first_match,
            ):
                result = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=preview.confirmation_token or "",
                    home=root / "home",
                )
            self.assertEqual(result.status, "blocked")
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)

    def test_migration_terminal_verification_rechecks_identity_and_live_bytes(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        for case in ("identity", "bytes"):
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                target = root / "target"
                displaced = root / "displaced"
                replacement = root / "replacement"
                self.write_inventory(seeds)
                self.write_inventory(target, private=True)
                if case == "identity":
                    with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                        self.assertIsNone(
                            runtime_config.prepare_data_root_for_startup(self.config(replacement))
                        )
                preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
                real_status = data_schema._schema_status_pinned
                changed = False

                def change_during_terminal_status(selected, descriptor, **kwargs):
                    nonlocal changed
                    status = real_status(selected, descriptor, **kwargs)
                    if status == "current" and not changed:
                        changed = True
                        if case == "identity":
                            target.rename(displaced)
                            replacement.rename(target)
                        else:
                            tasks = target / "tasks.json"
                            tasks.write_text('[{"id":"changed-after-confirmation"}]\n', encoding="utf-8")
                            tasks.chmod(0o600)
                    return status

                with patch.object(
                    data_schema,
                    "_schema_status_pinned",
                    side_effect=change_during_terminal_status,
                ):
                    result = data_schema.migrate_data_schema(
                        seeds,
                        target,
                        confirmation_token=preview.confirmation_token or "",
                        home=root / "home",
                    )

                self.assertTrue(changed)
                self.assertEqual(result.status, "partial_failure")

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            displaced = root / "displaced"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            reservation = target / data_schema.FRESH_SCHEMA_RESERVATION_NAME
            reservation.write_bytes(data_schema._fresh_manifest_raw())
            if os.name == "posix":
                reservation.chmod(0o600)
            real_match = data_schema._pinned_target_matches
            swapped = False

            def substitute_fresh(path, descriptor):
                nonlocal swapped
                matched = real_match(path, descriptor)
                if matched and not swapped:
                    swapped = True
                    target.rename(displaced)
                    target.mkdir(mode=0o755)
                return matched

            with patch.object(
                data_schema,
                "_pinned_target_matches",
                side_effect=substitute_fresh,
            ):
                issue = data_schema.initialize_fresh_schema(seeds, target)
            self.assertEqual(issue, "fresh_schema_target_changed")
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)

    def test_schema_preview_rejects_seed_target_containment_without_writes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "application" / "data"
            descendant = seeds / "operator"
            self.write_inventory(seeds)
            self.write_inventory(descendant, private=True)
            before = self.snapshot(root)
            preview = data_schema.preview_schema_migration(
                seeds,
                descendant,
                home=root / "home",
            )
            self.assertEqual(preview.status, "unsafe")
            self.assertIn("schema_seed_target_overlap", preview.issues)
            self.assertEqual(before, self.snapshot(root))

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ancestor = root / "application"
            seeds = ancestor / "data"
            self.write_inventory(ancestor, private=True)
            self.write_inventory(seeds)
            before = self.snapshot(root)
            preview = data_schema.preview_schema_migration(
                seeds,
                ancestor,
                home=root / "home",
            )
            self.assertEqual(preview.status, "unsafe")
            self.assertIn("schema_seed_target_overlap", preview.issues)
            self.assertEqual(before, self.snapshot(root))

    def test_json_store_root_lock_is_reentrant_and_precedes_file_locks(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_inventory(root, private=True)
            tasks = root / "tasks.json"
            projects = root / "projects.json"
            completed = Event()
            errors: list[BaseException] = []

            def nested_writer():
                try:
                    def outer(current):
                        json_store.update_json(
                            projects,
                            [],
                            lambda nested: (nested, None),
                        )
                        json_store.update_json(
                            tasks,
                            [],
                            lambda nested: (json_store.NO_WRITE, len(nested)),
                        )
                        return current, None

                    json_store.update_json(tasks, [], outer)
                    completed.set()
                except BaseException as exc:  # pragma: no cover - diagnostic capture
                    errors.append(exc)

            thread = Thread(target=nested_writer, daemon=True)
            thread.start()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(completed.is_set())
            self.assertEqual(errors, [])

            starts = Event()
            done: list[str] = []

            def opposing(first: Path, second: Path, label: str):
                starts.wait(5)

                def outer(current):
                    json_store.update_json(
                        second,
                        [],
                        lambda nested: (nested, None),
                    )
                    return current, None

                json_store.update_json(first, [], outer)
                done.append(label)

            left = Thread(target=opposing, args=(tasks, projects, "left"), daemon=True)
            right = Thread(target=opposing, args=(projects, tasks, "right"), daemon=True)
            left.start()
            right.start()
            starts.set()
            left.join(5)
            right.join(5)
            self.assertFalse(left.is_alive())
            self.assertFalse(right.is_alive())
            self.assertCountEqual(done, ["left", "right"])

    def test_schema_cli_preview_and_confirmation_are_bounded(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            config = self.config(target)
            preview_args = server.parse_cli_args(["--preview-schema-migration"])

            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                preview_summary, preview_exit = runtime_config.run_schema_migration_cli(
                    preview_args,
                    config,
                )
                confirm_args = server.parse_cli_args(
                    [
                        "--confirm-schema-migration",
                        preview_summary["confirmation_token"],
                    ]
                )
                result_summary, result_exit = runtime_config.run_schema_migration_cli(
                    confirm_args,
                    config,
                )

            self.assertEqual(preview_exit, 0)
            self.assertEqual(preview_summary["status"], "ready")
            encoded = json.dumps(preview_summary)
            self.assertNotIn(str(root), encoded)
            self.assertNotIn("sha256", encoded)
            self.assertEqual(result_exit, 0)
            self.assertEqual(result_summary["status"], "migrated")
            self.assertEqual(data_schema.schema_startup_status(target), "current")

    def test_startup_status_uses_only_pinned_schema_evidence_under_lock(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(self.config(target)))
            with patch.object(
                data_schema,
                "_schema_status_guarded",
                side_effect=AssertionError("pathname status must not run under the lock"),
            ):
                self.assertEqual(data_schema.schema_startup_status(target), "current")

    def test_pinned_schema_read_rejects_fifo_without_blocking(self):
        if os.name != "posix" or not hasattr(os, "mkfifo"):
            self.skipTest("POSIX FIFO regression")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(self.config(target)))
            selected = target / "tasks.json"
            selected.unlink()
            os.mkfifo(selected, mode=0o600)
            results: list[str] = []
            worker = Thread(
                target=lambda: results.append(data_schema.schema_startup_status(target)),
                daemon=True,
            )
            worker.start()
            worker.join(1)
            blocked = worker.is_alive()
            if blocked:
                writer = os.open(selected, os.O_WRONLY | getattr(os, "O_NONBLOCK", 0))
                os.close(writer)
                worker.join(1)
            self.assertFalse(blocked, "schema status blocked opening an untrusted FIFO")
            self.assertEqual(results, ["invalid"])

    def test_backup_commit_followed_by_root_swap_is_partial_failure(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            displaced = root / "displaced"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
            real_read = data_migration._read_exact_regular_at
            swapped = False

            def swap_before_backup_verification(path, maximum, *, parent_fd):
                nonlocal swapped
                if Path(path).suffix == ".zip" and not swapped:
                    swapped = True
                    target.rename(displaced)
                    target.mkdir(mode=0o700)
                return real_read(path, maximum, parent_fd=parent_fd)

            with patch.object(
                data_migration,
                "_read_exact_regular_at",
                side_effect=swap_before_backup_verification,
            ):
                result = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=preview.confirmation_token or "",
                    home=root / "home",
                )

            self.assertTrue(swapped)
            self.assertEqual(result.status, "partial_failure")
            self.assertEqual(len(list((displaced / "backups").glob("data-schema-v1-*.zip"))), 1)
            self.assertFalse((displaced / "config" / data_schema.SCHEMA_MANIFEST_NAME).exists())
            self.assertFalse(any(path.name.endswith(".tmp") for path in displaced.rglob("*")))
            self.assertEqual(list(target.iterdir()), [])

    def test_backup_publication_fsync_failure_is_partial_after_root_swap(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            displaced = root / "displaced"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
            real_promote = data_migration._promote_seed_copy
            real_fsync = os.fsync
            swapped = False
            fsync_failed = False

            def promote_then_swap(*args, **kwargs):
                nonlocal swapped
                result = real_promote(*args, **kwargs)
                if not swapped:
                    swapped = True
                    target.rename(displaced)
                    target.mkdir(mode=0o700)
                return result

            def fail_first_post_publication_fsync(descriptor):
                nonlocal fsync_failed
                if swapped and not fsync_failed:
                    fsync_failed = True
                    raise OSError("simulated directory fsync failure")
                return real_fsync(descriptor)

            with (
                patch.object(data_migration, "_promote_seed_copy", side_effect=promote_then_swap),
                patch.object(data_migration.os, "fsync", side_effect=fail_first_post_publication_fsync),
            ):
                result = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=preview.confirmation_token or "",
                    home=root / "home",
                )

            self.assertTrue(swapped)
            self.assertTrue(fsync_failed)
            self.assertEqual(result.status, "partial_failure")
            self.assertEqual(len(list((displaced / "backups").glob("data-schema-v1-*.zip"))), 1)
            self.assertFalse((displaced / "config" / data_schema.SCHEMA_MANIFEST_NAME).exists())
            self.assertFalse(any(path.name.endswith(".tmp") for path in displaced.rglob("*")))
            self.assertEqual(list(target.iterdir()), [])

    def test_changed_backup_read_after_publication_is_partial_failure(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
            real_read = data_schema._read_private_artifact_at
            changed = False

            def changed_reciprocal_read(path, parent_descriptor, **kwargs):
                nonlocal changed
                raw, state = real_read(path, parent_descriptor, **kwargs)
                if Path(path).suffix == ".zip" and not changed:
                    changed = True
                    return b"changed-after-publication", state
                return raw, state

            with patch.object(
                data_schema,
                "_read_private_artifact_at",
                side_effect=changed_reciprocal_read,
            ):
                result = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=preview.confirmation_token or "",
                    home=root / "home",
                )

            self.assertTrue(changed)
            self.assertEqual(result.status, "partial_failure")
            self.assertEqual(len(list((target / "backups").glob("data-schema-v1-*.zip"))), 1)
            self.assertFalse((target / "config" / data_schema.SCHEMA_MANIFEST_NAME).exists())
            self.assertFalse(any(path.name.endswith(".tmp") for path in target.rglob("*")))

    def test_existing_backup_decision_stays_on_pinned_root_during_aba_swap(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            displaced = root / "displaced"
            replacement = root / "replacement"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            self.write_inventory(replacement, private=True)
            preview = data_schema.preview_schema_migration(seeds, target, home=root / "home")
            token = preview.confirmation_token or ""
            replacement_backup = replacement / "backups" / data_schema._backup_name(token)
            replacement_backup.write_bytes(data_schema._build_backup(preview._snapshots, token))
            if os.name == "posix":
                replacement_backup.chmod(0o600)
            real_exists = data_schema._entry_exists_at
            swapped = False

            def aba_during_pinned_existence(path, parent_descriptor):
                nonlocal swapped
                if Path(path).suffix == ".zip" and not swapped:
                    swapped = True
                    target.rename(displaced)
                    replacement.rename(target)
                    try:
                        return real_exists(path, parent_descriptor)
                    finally:
                        target.rename(replacement)
                        displaced.rename(target)
                return real_exists(path, parent_descriptor)

            with (
                patch.object(data_schema, "_entry_exists_at", side_effect=aba_during_pinned_existence),
                patch.object(
                    data_schema,
                    "_backup_valid",
                    side_effect=AssertionError("locked migration must not validate backup by pathname"),
                ),
            ):
                result = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=token,
                    home=root / "home",
                )

            self.assertTrue(swapped)
            self.assertEqual(result.status, "migrated")
            self.assertTrue((target / "backups" / data_schema._backup_name(token)).exists())
            self.assertTrue((target / "config" / data_schema.SCHEMA_MANIFEST_NAME).exists())
            self.assertEqual(data_schema.schema_startup_status(target), "current")

    def test_confirmation_revalidation_uses_pinned_tree_not_pathname_aba(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            a_clone = root / "a-clone"
            displaced = root / "displaced"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            self.write_inventory(a_clone, private=True)
            external = data_schema.preview_schema_migration(seeds, target, home=root / "home")
            before_a = self.snapshot(a_clone)
            real_preview = data_schema.preview_schema_migration
            calls = 0
            changed_raw = b'[{"id":"changed-pinned-b"}]\n'

            def expose_a_only_to_pathname_preview(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    result = real_preview(*args, **kwargs)
                    (target / "tasks.json").write_bytes(changed_raw)
                    (target / "tasks.json").chmod(0o600)
                    return result
                target.rename(displaced)
                a_clone.rename(target)
                try:
                    return real_preview(*args, **kwargs)
                finally:
                    target.rename(a_clone)
                    displaced.rename(target)

            with patch.object(
                data_schema,
                "preview_schema_migration",
                side_effect=expose_a_only_to_pathname_preview,
            ):
                result = data_schema.migrate_data_schema(
                    seeds,
                    target,
                    confirmation_token=external.confirmation_token or "",
                    home=root / "home",
                )

            self.assertEqual(calls, 1)
            self.assertEqual(result.status, "blocked")
            self.assertEqual((target / "tasks.json").read_bytes(), changed_raw)
            self.assertEqual(data_schema.schema_startup_status(target), "legacy")
            self.assertFalse((target / "config" / data_schema.SCHEMA_MANIFEST_NAME).exists())
            self.assertEqual(list((target / "backups").iterdir()), [])
            self.assertEqual(self.snapshot(a_clone), before_a)

    def test_recovery_confirmation_binds_temporary_promotion_state(self):
        for kind in ("backup", "manifest"):
            for initial_pair in (False, True):
                for transition_phase in (
                    "before_pinned",
                    "before_discard",
                    "immediate_pre_unlink",
                ):
                    with self.subTest(
                        kind=kind,
                        initial_pair=initial_pair,
                        transition_phase=transition_phase,
                    ), TemporaryDirectory() as tmpdir:
                        root = Path(tmpdir)
                        seeds = root / "seeds"
                        target = root / "target"
                        self.write_inventory(seeds)
                        self.write_inventory(target, private=True)
                        base = data_schema.preview_schema_migration(
                            seeds,
                            target,
                            home=root / "home",
                        )
                        token = base.confirmation_token or ""
                        backup_name = data_schema._backup_name(token)
                        backup_raw = data_schema._build_backup(base._snapshots, token)
                        backup = target / "backups" / backup_name
                        if kind == "backup":
                            raw = backup_raw
                            final = backup
                            temporary = target / "backups" / (
                                f".{backup_name}.mentat-init-" + "9" * 32 + ".tmp"
                            )
                        else:
                            backup.write_bytes(backup_raw)
                            raw = data_schema._canonical_json(
                                data_schema._manifest_document(
                                    origin="schema_migration",
                                    backup_name=backup_name,
                                    backup_sha256=data_schema._digest(backup_raw),
                                )
                            )
                            final = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
                            temporary = target / "config" / (
                                ".data-schema.json.mentat-init-" + "a" * 32 + ".tmp"
                            )
                        if initial_pair:
                            final.write_bytes(raw)
                            os.link(final, temporary)
                        else:
                            temporary.write_bytes(raw)
                        if os.name == "posix":
                            temporary.chmod(0o600)
                            if final.exists():
                                final.chmod(0o600)
                            if backup.exists():
                                backup.chmod(0o600)
                        recovery = data_schema.preview_schema_migration(
                            seeds,
                            target,
                            home=root / "home",
                        )
                        self.assertEqual(recovery.status, "recovery_required")
                        transitioned = False

                        def transition() -> None:
                            nonlocal transitioned
                            if transitioned:
                                return
                            transitioned = True
                            if initial_pair:
                                final.unlink()
                            else:
                                os.link(temporary, final)

                        real_preview = data_schema.preview_schema_migration
                        real_match = data_schema._pinned_confirmation_matches
                        real_issue = data_schema._schema_artifact_issue_pinned
                        issue_calls = 0

                        def preview_then_transition(*args, **kwargs):
                            result = real_preview(*args, **kwargs)
                            transition()
                            return result

                        def match_then_transition(*args, **kwargs):
                            matched = real_match(*args, **kwargs)
                            if matched:
                                transition()
                            return matched

                        def inventory_then_transition(*args, **kwargs):
                            nonlocal issue_calls
                            issue = real_issue(*args, **kwargs)
                            issue_calls += 1
                            if issue_calls == 2:
                                transition()
                            return issue

                        if transition_phase == "before_pinned":
                            selected_patch = patch.object(
                                data_schema,
                                "preview_schema_migration",
                                side_effect=preview_then_transition,
                            )
                        elif transition_phase == "before_discard":
                            selected_patch = patch.object(
                                data_schema,
                                "_pinned_confirmation_matches",
                                side_effect=match_then_transition,
                            )
                        else:
                            selected_patch = patch.object(
                                data_schema,
                                "_schema_artifact_issue_pinned",
                                side_effect=inventory_then_transition,
                            )
                        with selected_patch:
                            result = data_schema.migrate_data_schema(
                                seeds,
                                target,
                                confirmation_token=recovery.confirmation_token or "",
                                home=root / "home",
                            )

                        self.assertTrue(transitioned)
                        self.assertEqual(result.status, "blocked")
                        self.assertTrue(temporary.exists())
                        self.assertEqual(final.exists(), not initial_pair)
                        self.assertEqual(temporary.read_bytes(), raw)

    def test_changed_runtime_root_keeps_full_durable_document_policy(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = root / "approved"
            changed = root / "changed"
            self.write_inventory(approved, private=True)
            self.write_inventory(changed, private=True)
            (changed / "tasks.json").unlink()
            with (
                patch.object(server, "DATA_DIR", data_layout._absolute_without_following(changed)),
                patch.object(server, "CONFIGURED_DATA_DIR", data_layout._absolute_without_following(approved)),
                patch.object(server, "DATA_MUTATION_LOCK", False),
            ):
                with self.assertRaises(FileNotFoundError):
                    server.read_json_file("tasks.json", [])
                with self.assertRaises(FileNotFoundError):
                    server.update_json_file("tasks.json", [], lambda _value: ([], None))
            self.assertFalse((changed / "tasks.json").exists())

            (changed / "tasks.json").write_text("[]\n", encoding="utf-8")
            if os.name == "posix":
                (changed / "tasks.json").chmod(0o644)
                with (
                    patch.object(server, "DATA_DIR", data_layout._absolute_without_following(changed)),
                    patch.object(server, "CONFIGURED_DATA_DIR", data_layout._absolute_without_following(approved)),
                    patch.object(server, "DATA_MUTATION_LOCK", False),
                ):
                    with self.assertRaises(OSError):
                        server.read_json_file("tasks.json", [])

    def test_email_is_allowlisted_for_reads_but_never_for_writes(self):
        with TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "data"
            self.write_inventory(target, private=True)
            approved = data_layout._absolute_without_following(target)
            with (
                patch.object(server, "DATA_DIR", approved),
                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                patch.object(server, "DATA_MUTATION_LOCK", False),
            ):
                self.assertEqual(server.email_payload()["items"], [])
                with self.assertRaises(ValueError):
                    server.update_json_file("email.json", [], lambda value: (value, None))


if __name__ == "__main__":
    unittest.main()
