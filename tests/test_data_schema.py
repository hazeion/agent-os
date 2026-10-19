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
import data_schema
import json_store
import runtime_config
import server
import task_repository


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

    def initialize_current_documents(self, seeds: Path, target: Path) -> None:
        result = data_layout.initialize_data_root(
            seeds, target,
            locked_prepare=lambda root, descriptor, plan: data_schema.prepare_fresh_schema_initialization(seeds, root, descriptor, plan),
            locked_finalize=lambda root, descriptor, _plan: data_schema.initialize_fresh_schema_under_lock(seeds, root, descriptor),
        )
        self.assertIn(result.status, {'initialized', 'existing'})
        self.assertEqual(data_schema.schema_startup_status(target), 'current')

    def write_current_inventory(self, root: Path) -> None:
        with TemporaryDirectory() as temporary:
            seeds = Path(temporary) / 'seeds'
            self.write_inventory(seeds)
            with patch.object(runtime_config, 'PACKAGED_SEED_DIR', seeds):
                self.assertIsNone(runtime_config.prepare_data_root_for_startup(self.config(root)))
        self.assertEqual(data_schema.schema_startup_status(root), 'current')

    def write_prior_current_inventory(self, root: Path) -> None:
        """Static current-format prior-origin evidence; no migration is invoked."""
        self.write_current_inventory(root)
        import hashlib
        token = 'a' * 64
        name = 'data-schema-v1-' + token[:24] + '.zip'
        documents = [(name, (root / name).read_bytes()) for name in data_layout.SEED_FILE_NAMES]
        record = {'format_version': 1, 'kind': 'mentat-data-schema-backup',
                  'token_sha256': token, 'from_version': 0, 'to_version': 1,
                  'items': [{'name': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                            for name, raw in documents]}
        backup = root / 'backups' / name
        with zipfile.ZipFile(backup, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('manifest.json', json.dumps(record).encode())
            for document, raw in documents:
                archive.writestr('data/' + document, raw)
        backup.chmod(0o600)
        manifest_path = root / 'config' / data_schema.SCHEMA_MANIFEST_NAME
        manifest = json.loads(manifest_path.read_bytes())
        manifest.update(origin='schema_migration', applied_steps=[{
            'id': 'durable-json-v0-to-v1', 'from_version': 0, 'to_version': 1}],
            backup={'name': name, 'sha256': hashlib.sha256(backup.read_bytes()).hexdigest()})
        manifest_path.write_bytes(data_schema._canonical_json(manifest))
        manifest_path.chmod(0o600)
        self.assertEqual(data_schema.schema_startup_status(root), 'current')

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
                    "current_data_root_required"
                    if case == "newer"
                    else "current_data_root_required"
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
                self.initialize_current_documents(seeds, target)
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
                    if directory != 'private':
                        (target / directory).chmod(0o755)
                with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                    self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
                self.assertTrue(
                    all(
                        stat.S_IMODE((target / directory).stat().st_mode) == 0o700
                        for directory in data_layout.DATA_ROOT_DIRECTORY_NAMES
                    )
                )

        if os.name == 'posix':
            with TemporaryDirectory() as temporary:
                target = Path(temporary) / 'target'
                self.write_current_inventory(target)
                (target / 'private').chmod(0o755)
                before = self.snapshot(target)
                self.assertIn('current_data_root_required', runtime_config.prepare_data_root_for_startup(self.config(target)) or '')
                self.assertEqual(self.snapshot(target), before)

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
            self.assertIn("data_initialization_failed", error or "")
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

            self.assertIn("invalid_data_schema", error or "")
            self.assertEqual(data_schema.schema_startup_status(target), "current")
            self.assertEqual(data_schema.schema_startup_status(displaced), "current")

    def test_json_store_mutation_never_writes_substituted_root(self):
        if os.name == "nt":
            self.skipTest("Windows root handle chain prevents injected rename")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target"
            displaced = root / "displaced"
            self.write_current_inventory(target)
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
            self.write_current_inventory(target)
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
            self.write_current_inventory(target)
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
            selected.write_text(
                json.dumps([{"id": "operator-task", "title": "Operator task"}]) + "\n",
                encoding="utf-8",
            )
            if os.name == "posix":
                selected.chmod(0o600)
            task_repository.ensure_task_sqlite_authority(target)
            selected.unlink()
            if os.name == "nt":
                try:
                    selected.symlink_to(outside)
                except OSError as exc:
                    self.skipTest(f"file symlink unavailable: {exc}")
            else:
                selected.symlink_to(outside)
            with common[0], common[1], common[2]:
                self.assertEqual(
                    [item["id"] for item in server.read_json_file("tasks.json", [])],
                    ["operator-task"],
                )
                self.assertEqual(
                    server.update_json_file(
                        "tasks.json",
                        [],
                        lambda current: (current, "unchanged"),
                    ),
                    "unchanged",
                )
            self.assertEqual(outside.read_text(encoding="utf-8"), '[{"id":"outside"}]\n')

            selected.unlink()
            with (
                patch.object(server, "DATA_DIR", approved),
                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                patch.object(server, "DATA_MUTATION_LOCK", True),
            ):
                self.assertEqual(
                    [item["id"] for item in server.read_json_file("tasks.json", [])],
                    ["operator-task"],
                )
                self.assertEqual(
                    server.update_json_file(
                        "tasks.json",
                        [],
                        lambda current: (current, "unchanged"),
                    ),
                    "unchanged",
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
                    self.write_current_inventory(selected)
                    self.write_current_inventory(outside)
                    (outside / data_layout.INITIALIZATION_LOCK_NAME).unlink()
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
            self.write_current_inventory(target)
            approved = data_layout._absolute_without_following(target)
            with (
                patch.object(server, "DATA_DIR", approved),
                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                patch.object(server, "DATA_MUTATION_LOCK", False),
            ):
                result = server.update_json_file(
                    "agents.json",
                    [],
                    lambda _current: ([{"id": "development-write"}], "ok"),
                )
            self.assertEqual(result, "ok")
            self.assertEqual(
                json.loads((target / "agents.json").read_text(encoding="utf-8")),
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
            (target / "tasks.json").write_text(
                json.dumps([{"id": "operator-task", "title": "Operator task"}]) + "\n",
                encoding="utf-8",
            )
            if os.name == "posix":
                (target / "tasks.json").chmod(0o600)
            task_repository.ensure_task_sqlite_authority(target, required_source_mode=None)
            before = (target / "tasks.json").read_bytes()
            common = (
                patch.object(server, "DATA_DIR", approved),
                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                patch.object(server, "DATA_MUTATION_LOCK", True),
            )
            with common[0], common[1], common[2]:
                wrong_shape, wrong_shape_status = server.update_json_file(
                    "tasks.json",
                    [],
                    lambda _current: ({"wrong": "shape"}, None),
                )
                oversized, oversized_status = server.update_json_file(
                    "tasks.json",
                    [],
                    lambda current: (
                        [
                            {
                                **current[0],
                                "description": "x"
                                * (task_repository.MAX_TASK_DOCUMENT_BYTES + 1),
                            }
                        ],
                        None,
                    ),
                )
            self.assertEqual(wrong_shape_status, 503)
            self.assertIn("tasks.invalid", wrong_shape["error"])
            self.assertEqual(oversized_status, 503)
            self.assertIn("description.invalid", oversized["error"])
            self.assertEqual((target / "tasks.json").read_bytes(), before)
            self.assertEqual(
                [item["id"] for item in task_repository.read_authoritative_tasks(target)],
                ["operator-task"],
            )
            self.assertEqual(data_schema.schema_startup_status(target), "current")

    def test_windows_product_write_rejects_file_reparse_point(self):
        if os.name != "nt":
            self.skipTest("native Windows file-reparse regression")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target"
            outside = root / "outside.json"
            self.write_current_inventory(target)
            outside.write_text('[]\n', encoding="utf-8")
            selected = target / "tasks.json"
            selected.write_text(
                json.dumps([{"id": "operator-task", "title": "Operator task"}]) + "\n",
                encoding="utf-8",
            )
            task_repository.ensure_task_sqlite_authority(target)
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
                self.assertIsNone(
                    server.update_json_file(
                        "tasks.json",
                        [],
                        lambda current: (current, None),
                    )
                )
            self.assertEqual(outside.read_text(encoding="utf-8"), "[]\n")

    def test_newer_manifest_refuses_startup_without_deleting_temporary(self):
        for kind in ('backup', 'manifest'):
            with self.subTest(kind=kind), TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / 'target'
                seeds = root / 'seeds'
                self.write_inventory(seeds)
                self.write_prior_current_inventory(target)
                manifest_path = target / 'config' / data_schema.SCHEMA_MANIFEST_NAME
                manifest = json.loads(manifest_path.read_bytes())
                manifest['format_version'] = 2
                manifest_path.write_bytes(data_schema._canonical_json(manifest))
                if kind == 'backup':
                    temporary_path = target / 'backups' / ('.' + manifest['backup']['name'] + '.mentat-init-' + '2' * 32 + '.tmp')
                    temporary_path.write_bytes((target / 'backups' / manifest['backup']['name']).read_bytes())
                else:
                    temporary_path = target / 'config' / ('.data-schema.json.mentat-init-' + '3' * 32 + '.tmp')
                    temporary_path.write_bytes(data_schema._canonical_json(manifest))
                temporary_path.chmod(0o600)
                before = self.snapshot(target)
                self.assertEqual(data_schema.schema_preflight_status(target), 'newer')
                self.assertEqual(data_schema.schema_startup_status(target), 'newer')
                with patch.object(runtime_config, 'PACKAGED_SEED_DIR', seeds):
                    self.assertIn('current_data_root_required', runtime_config.prepare_data_root_for_startup(self.config(target)) or '')
                self.assertEqual(self.snapshot(target), before)

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
                self.assertEqual(data_schema.schema_preflight_status(target), "invalid")
                self.assertEqual(data_schema.schema_startup_status(target), "invalid")
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
                self.assertIn("current_data_root_required", error or "")
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
                self.assertEqual(data_schema.schema_preflight_status(target), "invalid")
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
            self.assertIn("current_data_root_required", error or "")
            self.assertEqual(before, self.snapshot(target))


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
                self.assertIn("current_data_root_required", error or "")
                self.assertEqual(before, self.snapshot(target))


    def test_malformed_manifest_and_zip_fail_closed_without_traceback(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_prior_current_inventory(target)
            manifest = target / "config" / data_schema.SCHEMA_MANIFEST_NAME
            manifest.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")
            if os.name == "posix":
                manifest.chmod(0o600)
            self.assertEqual(data_schema.schema_preflight_status(target), "invalid")
            self.assertEqual(data_schema.schema_startup_status(target), "invalid")

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_prior_current_inventory(target)
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
                self.write_prior_current_inventory(target)
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
                        archive.writestr(name, entries[name])
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
                    "data_initialization_failed",
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
                self.assertIn("data_initialization_failed", runtime_config.prepare_data_root_for_startup(config) or "")
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
                second = self.snapshot(target)
                self.assertEqual(set(first), set(second))
                self.assertEqual({name: value for name, value in first.items() if value[1] is not None},
                                 {name: value for name, value in second.items() if value[1] is not None})
                self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o700
                                    for path in target.rglob('*') if path.is_dir()))

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

    def test_existing_unversioned_root_is_refused_without_changes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            config = self.config(target)

            self.assertEqual(data_schema.schema_startup_status(target), "legacy")
            before = self.snapshot(target)
            with patch.object(runtime_config, "PACKAGED_SEED_DIR", seeds):
                self.assertIn('current_data_root_required', runtime_config.prepare_data_root_for_startup(config) or '')
            self.assertEqual(self.snapshot(target), before)
            self.assertEqual(data_schema.schema_startup_status(target), "legacy")

    def test_prior_origin_current_manifest_validates_without_source_changes(self):
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / 'target'
            self.write_prior_current_inventory(target)
            before = self.snapshot(target)
            self.assertEqual(data_schema.schema_preflight_status(target), 'current')
            self.assertEqual(data_schema.schema_startup_status(target), 'current')
            self.assertEqual(self.snapshot(target), before)

    def test_fresh_completion_cannot_upgrade_an_unreserved_inventory(self):
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / 'target'
            seeds = Path(temporary) / 'seeds'
            self.write_inventory(seeds)
            self.write_inventory(target, private=True)
            before = self.snapshot(target)
            self.assertEqual(data_schema.initialize_fresh_schema(seeds, target), 'invalid_schema_manifest')
            self.assertEqual(self.snapshot(target), before)

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
                self.assertIn("current_data_root_required", error or "")

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
                self.write_prior_current_inventory(target)
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

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target"
            self.write_prior_current_inventory(target)
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
            self.write_prior_current_inventory(target)
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


    def test_pinned_root_blocks_current_startup_substitution(self):
        if os.name == "nt":
            self.skipTest("Windows directory guards prevent injected rename natively")
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


    def test_json_store_root_lock_is_reentrant_and_precedes_file_locks(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_current_inventory(root)
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


    def test_changed_runtime_root_keeps_full_durable_document_policy(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = root / "approved"
            changed = root / "changed"
            self.write_current_inventory(approved)
            self.write_current_inventory(changed)
            (changed / "tasks.json").write_text(
                json.dumps([{"id": "operator-task", "title": "Operator task"}]) + "\n",
                encoding="utf-8",
            )
            if os.name == "posix":
                (changed / "tasks.json").chmod(0o600)
            task_repository.ensure_task_sqlite_authority(changed)
            (changed / "tasks.json").unlink()
            with (
                patch.object(server, "DATA_DIR", data_layout._absolute_without_following(changed)),
                patch.object(server, "CONFIGURED_DATA_DIR", data_layout._absolute_without_following(approved)),
                patch.object(server, "DATA_MUTATION_LOCK", False),
            ):
                self.assertEqual(
                    [item["id"] for item in server.read_json_file("tasks.json", [])],
                    ["operator-task"],
                )
                self.assertEqual(
                    server.update_json_file(
                        "tasks.json", [], lambda value: (value, "unchanged")
                    ),
                    "unchanged",
                )
            self.assertFalse((changed / "tasks.json").exists())

            (changed / "tasks.json").write_text("[]\n", encoding="utf-8")
            if os.name == "posix":
                (changed / "tasks.json").chmod(0o644)
                with (
                    patch.object(server, "DATA_DIR", data_layout._absolute_without_following(changed)),
                    patch.object(server, "CONFIGURED_DATA_DIR", data_layout._absolute_without_following(approved)),
                    patch.object(server, "DATA_MUTATION_LOCK", False),
                ):
                    self.assertEqual(
                        [item["id"] for item in server.read_json_file("tasks.json", [])],
                        ["operator-task"],
                    )

    def test_email_is_allowlisted_for_reads_but_never_for_writes(self):
        with TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "data"
            self.write_current_inventory(target)
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
