from __future__ import annotations

from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch
import zipfile

import data_backup_restore as backup_restore
import data_layout
import data_schema
import json_store
import runtime_config
import server


ROOT = Path(__file__).resolve().parents[1]
THREAD_TIMEOUT_SECONDS = 15


class DataBackupRestoreTests(unittest.TestCase):
    def write_inventory(
        self,
        root: Path,
        *,
        marker: str,
        extra_markers: bool = False,
    ) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for name in data_layout.SEED_FILE_NAMES:
            payload = {"theme": "midnight"} if name == "dashboard.json" else []
            if name == "tasks.json":
                payload = [{"id": f"task-{marker}"}]
            if extra_markers and name == "projects.json":
                payload = [{"id": f"project-{marker}"}]
            path = root / name
            path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
            if os.name == "posix":
                path.chmod(0o600)
        for name in data_layout.DATA_ROOT_DIRECTORY_NAMES:
            directory = root / name
            directory.mkdir(exist_ok=True)
            if os.name == "posix":
                directory.chmod(0o700)

    def make_current(
        self,
        base: Path,
        name: str,
        marker: str,
        *,
        extra_markers: bool = False,
    ) -> tuple[Path, Path]:
        seeds = base / f"{name}-seeds"
        target = base / name
        self.write_inventory(seeds, marker="seed")
        self.write_inventory(target, marker=marker, extra_markers=extra_markers)
        preview = data_schema.preview_schema_migration(
            seeds,
            target,
            home=base / "home",
        )
        self.assertEqual(preview.status, "ready")
        result = data_schema.migrate_data_schema(
            seeds,
            target,
            confirmation_token=preview.confirmation_token or "",
            home=base / "home",
        )
        self.assertEqual(result.status, "migrated")
        self.assertEqual(data_schema.schema_preflight_status(target), "current")
        return seeds, target

    def snapshot(self, root: Path) -> dict[str, bytes | None]:
        return {
            str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")
            if path.relative_to(root) != Path(data_layout.INITIALIZATION_LOCK_NAME)
        }

    def config(self, target: Path) -> runtime_config.AppConfig:
        return runtime_config.AppConfig(
            config_files=(),
            host="127.0.0.1",
            port=8888,
            data_dir=target,
            public_dir=target.parent / "public",
            hermes_home=target.parent / "hermes",
            obsidian_vault=target.parent / "vault",
            data_dir_source="cli",
        )

    def create_source_backup(self, base: Path) -> tuple[Path, Path, backup_restore.BackupResult]:
        _seeds, source = self.make_current(
            base,
            "source",
            "source",
            extra_markers=True,
        )
        result = backup_restore.create_durable_backup(source)
        self.assertEqual(result.status, "created")
        assert result.backup_name is not None
        return source, source / "backups" / result.backup_name, result

    def test_backup_is_fixed_private_nonrecursive_and_idempotent(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            source, backup_path, result = self.create_source_backup(base)
            (source / "private" / "secret.txt").write_text("must-not-enter", encoding="utf-8")
            (source / "runtime" / "scratch.txt").write_text("runtime-secret", encoding="utf-8")
            documents_before = {
                name: (source / name).read_bytes() for name in data_layout.SEED_FILE_NAMES
            }

            second = backup_restore.create_durable_backup(source)

            self.assertEqual(second.status, "existing")
            self.assertEqual(result.backup_name, second.backup_name)
            self.assertEqual(
                documents_before,
                {name: (source / name).read_bytes() for name in data_layout.SEED_FILE_NAMES},
            )
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(backup_path.stat().st_mode), 0o600)
            with zipfile.ZipFile(backup_path, "r") as archive:
                self.assertEqual(
                    archive.namelist(),
                    [
                        "manifest.json",
                        *(f"data/{name}" for name in data_layout.SEED_FILE_NAMES),
                        "private/history.json",
                        "private/mentat.sqlite3",
                    ],
                )
                manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["kind"], backup_restore.BACKUP_KIND)
            self.assertEqual(len(manifest["items"]), len(data_layout.SEED_FILE_NAMES) + 1)
            self.assertIn("private_console", {item["name"] for item in manifest["items"]})
            self.assertNotIn("private_console", {item["name"] for item in manifest["excluded"]})
            encoded = backup_path.read_bytes()
            self.assertNotIn(b"must-not-enter", encoded)
            self.assertNotIn(b"runtime-secret", encoded)
            self.assertNotIn(os.fsencode(str(base)), encoded)

    def test_backup_snapshot_serializes_with_ordinary_json_mutation(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _seeds, source = self.make_current(base, "source", "source")
            entered = Event()
            release = Event()
            writer_finished = Event()
            real_build = backup_restore._build_backup

            def pause_build(documents, private_unit=None, **kwargs):
                entered.set()
                self.assertTrue(release.wait(THREAD_TIMEOUT_SECONDS))
                return real_build(documents, private_unit, **kwargs)

            def create_backup():
                backup_restore.create_durable_backup(source)

            def mutate():
                json_store.update_json(
                    source / "tasks.json",
                    [],
                    lambda _current: ([{"id": "writer"}], None),
                    mutation_lock=True,
                    maximum_bytes=data_layout.MAX_PREFLIGHT_JSON_BYTES,
                    expected_type=list,
                    required_mode=0o600,
                    require_existing=True,
                )
                writer_finished.set()

            with patch.object(backup_restore, "_build_backup", side_effect=pause_build):
                backup_thread = Thread(target=create_backup)
                writer_thread = None
                try:
                    backup_thread.start()
                    self.assertTrue(entered.wait(THREAD_TIMEOUT_SECONDS))
                    writer_thread = Thread(target=mutate)
                    writer_thread.start()
                    self.assertFalse(writer_finished.wait(0.1))
                finally:
                    release.set()
                    if backup_thread.ident is not None:
                        backup_thread.join(THREAD_TIMEOUT_SECONDS)
                    if writer_thread is not None and writer_thread.ident is not None:
                        writer_thread.join(THREAD_TIMEOUT_SECONDS)

            self.assertFalse(backup_thread.is_alive())
            self.assertIsNotNone(writer_thread)
            self.assertFalse(writer_thread.is_alive())
            self.assertTrue(writer_finished.is_set())

    def test_backup_conflict_is_never_overwritten(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            source, backup_path, _result = self.create_source_backup(base)
            conflicting = b"not-the-canonical-backup"
            backup_path.write_bytes(conflicting)
            if os.name == "posix":
                backup_path.chmod(0o600)

            blocked = backup_restore.create_durable_backup(source)

            self.assertEqual(blocked.status, "blocked")
            self.assertEqual(backup_path.read_bytes(), conflicting)

    @unittest.skipUnless(os.name == "posix", "POSIX child-substitution regression")
    def test_backup_artifact_check_stays_on_pinned_child_boundary(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _seeds, source = self.make_current(base, "source", "source")
            displaced = base / "displaced-backups"
            outside = base / "outside-backups"
            outside.mkdir()
            real_check = backup_restore._restore_artifact_issue_under_lock
            substituted = False

            def substitute_then_check(target, descriptor):
                nonlocal substituted
                if not substituted:
                    (target / "backups").rename(displaced)
                    (target / "backups").symlink_to(outside, target_is_directory=True)
                    substituted = True
                return real_check(target, descriptor)

            with patch.object(
                backup_restore,
                "_restore_artifact_issue_under_lock",
                side_effect=substitute_then_check,
            ):
                result = backup_restore.create_durable_backup(source)

            self.assertTrue(substituted)
            self.assertEqual(result.status, "blocked")
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse(
                any(path.name.startswith(backup_restore.BACKUP_PREFIX) for path in displaced.iterdir())
            )

    def test_restore_inventory_lists_native_pins_without_posix_descriptors(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _seeds, target = self.make_current(base, "target", "target")
            state_path = target / "config" / backup_restore.RESTORE_STATE_NAME
            state_path.write_bytes(b'{"marker":"state"}\n')
            if os.name == "posix":
                state_path.chmod(0o600)

            @contextmanager
            def native_pin_without_descriptor(selected, descriptor, name):
                self.assertEqual(
                    selected,
                    data_layout._absolute_without_following(target),
                )
                self.assertIn(name, {"config", "backups"})
                yield True, None

            with json_store._durable_mutation_lock(target) as root_descriptor:
                with patch.object(
                    backup_restore,
                    "_pinned_existing_child_directory_state",
                    side_effect=native_pin_without_descriptor,
                ):
                    issue = backup_restore._restore_artifact_issue_under_lock(
                        target,
                        root_descriptor,
                    )

            self.assertEqual(issue, "restore_incomplete")

    def test_restore_inventory_never_lists_child_that_appears_after_absence(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _seeds, target = self.make_current(base, "target", "target")
            normalized_target = data_layout._absolute_without_following(target)
            real_pin = backup_restore._pinned_existing_child_directory_state
            real_names = backup_restore._names_from_pinned_directory
            listed: list[Path] = []

            @contextmanager
            def appear_after_absence(selected, descriptor, name):
                if name == "backups":
                    yield False, None
                    return
                with real_pin(selected, descriptor, name) as pinned:
                    yield pinned

            def record_listing(path, descriptor):
                listed.append(path)
                return real_names(path, descriptor)

            real_lexists = os.path.lexists

            def appeared(path):
                if Path(path).name == "backups":
                    return True
                return real_lexists(path)

            with json_store._durable_mutation_lock(target) as root_descriptor:
                with (
                    patch.object(
                        backup_restore,
                        "_pinned_existing_child_directory_state",
                        side_effect=appear_after_absence,
                    ),
                    patch.object(
                        backup_restore,
                        "_names_from_pinned_directory",
                        side_effect=record_listing,
                    ),
                    patch.object(backup_restore.os.path, "lexists", side_effect=appeared),
                ):
                    issue = backup_restore._restore_artifact_issue_under_lock(
                        target,
                        root_descriptor,
                    )

            self.assertEqual(issue, "restore_artifacts_invalid")
            self.assertNotIn(normalized_target / "backups", listed)

    @unittest.skipUnless(os.name == "posix", "POSIX pinned-mode regression")
    def test_restore_inventory_finds_state_in_broad_directory_via_descriptor(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _seeds, target = self.make_current(base, "target", "target")
            normalized_target = data_layout._absolute_without_following(target)
            state_path = target / "config" / backup_restore.RESTORE_STATE_NAME
            state_path.write_bytes(b'{"marker":"state"}\n')
            state_path.chmod(0o600)
            (target / "config").chmod(0o755)
            real_names = backup_restore._names_from_pinned_directory
            listed_with: list[tuple[Path, int | None]] = []

            def record_listing(path, descriptor):
                listed_with.append((path, descriptor))
                return real_names(path, descriptor)

            with json_store._durable_mutation_lock(target) as root_descriptor:
                with patch.object(
                    backup_restore,
                    "_names_from_pinned_directory",
                    side_effect=record_listing,
                ):
                    issue = backup_restore._restore_artifact_issue_under_lock(
                        target,
                        root_descriptor,
                    )

            config_listings = [
                descriptor
                for path, descriptor in listed_with
                if path == normalized_target / "config"
            ]
            self.assertEqual(issue, "restore_artifacts_invalid")
            self.assertTrue(config_listings)
            self.assertTrue(all(descriptor is not None for descriptor in config_listings))

    def test_restore_preview_is_read_only_and_success_preserves_exclusions(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            source, backup_path, _result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")
            schema_before = (target / "config" / data_schema.SCHEMA_MANIFEST_NAME).read_bytes()
            sentinels = {}
            for directory in ("private", "runtime", "cache", "logs"):
                path = target / directory / "sentinel.txt"
                path.write_text(f"keep-{directory}", encoding="utf-8")
                sentinels[path] = path.read_bytes()
            before = self.snapshot(target)

            preview = backup_restore.preview_durable_restore(target, backup_path)

            self.assertEqual(preview.status, "ready")
            self.assertEqual(before, self.snapshot(target))
            self.assertRegex(preview.confirmation_token or "", r"^[0-9a-f]{64}$")
            self.assertEqual(
                {item["name"] for item in preview.items if item["action"] == "replace"},
                {"projects.json", "tasks.json"},
            )
            result = backup_restore.restore_durable_backup(
                target,
                backup_path,
                confirmation_token=preview.confirmation_token or "",
            )

            self.assertEqual(result.status, "restored")
            self.assertEqual((target / "tasks.json").read_bytes(), (source / "tasks.json").read_bytes())
            self.assertEqual((target / "projects.json").read_bytes(), (source / "projects.json").read_bytes())
            self.assertEqual(
                (target / "config" / data_schema.SCHEMA_MANIFEST_NAME).read_bytes(),
                schema_before,
            )
            self.assertTrue(all(path.read_bytes() == raw for path, raw in sentinels.items()))
            self.assertEqual(data_schema.schema_preflight_status(target), "current")
            self.assertEqual(backup_restore.restore_startup_status(target), "clear")

    def test_restore_confirmation_rejects_changed_backup_and_target(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, _result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")
            preview = backup_restore.preview_durable_restore(target, backup_path)
            before = {name: (target / name).read_bytes() for name in data_layout.SEED_FILE_NAMES}

            (target / "tasks.json").write_text('[{"id":"changed-after-preview"}]\n', encoding="utf-8")
            stale = backup_restore.restore_durable_backup(
                target,
                backup_path,
                confirmation_token=preview.confirmation_token or "",
            )
            self.assertEqual(stale.status, "blocked")
            self.assertFalse((target / "config" / backup_restore.RESTORE_STATE_NAME).exists())
            self.assertNotEqual((target / "tasks.json").read_bytes(), before["tasks.json"])

            changed_raw = bytearray(backup_path.read_bytes())
            changed_raw[-1] ^= 1
            backup_path.write_bytes(bytes(changed_raw))
            invalid = backup_restore.preview_durable_restore(target, backup_path)
            self.assertEqual(invalid.status, "unsafe")

    def test_preview_refuses_malformed_newer_and_linked_archives_without_writes(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, backup_result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")
            before = self.snapshot(target)

            malformed = base / (backup_result.backup_name or "missing.zip")
            malformed.write_bytes(b"not-a-zip")
            if os.name == "posix":
                malformed.chmod(0o600)
            self.assertEqual(
                backup_restore.preview_durable_restore(target, malformed).status,
                "unsafe",
            )

            with zipfile.ZipFile(backup_path, "r") as original:
                entries = [(info.filename, original.read(info.filename)) for info in original.infolist()]
            manifest = json.loads(entries[0][1])
            manifest["format_version"] = backup_restore.BACKUP_FORMAT_VERSION + 1
            newer_buffer = io.BytesIO()
            with zipfile.ZipFile(newer_buffer, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr(backup_restore._zip_entry("manifest.json"), json.dumps(manifest).encode())
                for name, raw in entries[1:]:
                    archive.writestr(backup_restore._zip_entry(name), raw)
            malformed.write_bytes(newer_buffer.getvalue())
            self.assertEqual(
                backup_restore.preview_durable_restore(target, malformed).status,
                "unsupported",
            )

            if os.name == "posix":
                malformed.unlink()
                malformed.symlink_to(backup_path)
                self.assertEqual(
                    backup_restore.preview_durable_restore(target, malformed).status,
                    "unsafe",
                )
            self.assertEqual(before, self.snapshot(target))

    def test_zip_entry_count_is_bounded_before_zipfile_construction(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            for index in range(1 + len(data_layout.SEED_FILE_NAMES) + 2 + backup_restore.MAX_BLOBS + 1):
                archive.writestr(f"entry-{index}", b"")
        with patch.object(
            backup_restore.zipfile,
            "ZipFile",
            side_effect=AssertionError("ZipFile must not parse an invalid entry count"),
        ):
            with self.assertRaisesRegex(ValueError, "backup_container_invalid"):
                backup_restore._documents_from_backup(buffer.getvalue())

    def test_validated_documents_do_not_retain_decoded_json_trees(self):
        document = backup_restore._document_from_raw("tasks.json", b"[0,1,2]\n")
        self.assertEqual(document.raw, b"[0,1,2]\n")
        self.assertNotIn("payload", document.__dataclass_fields__)

    def test_recovery_backup_and_state_exist_before_first_live_commit(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, _result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")
            preview = backup_restore.preview_durable_restore(target, backup_path)
            real_write = backup_restore.write_json_bytes_atomic
            observed = []

            def verify_checkpoint(*args, **kwargs):
                state = target / "config" / backup_restore.RESTORE_STATE_NAME
                self.assertTrue(state.is_file())
                document = json.loads(state.read_text(encoding="utf-8"))
                recovery = target / "backups" / document["recovery_backup_name"]
                source_copy = target / "backups" / document["source_backup_name"]
                observed.append(recovery.is_file() and source_copy.is_file())
                return real_write(*args, **kwargs)

            with patch.object(
                backup_restore,
                "write_json_bytes_atomic",
                side_effect=verify_checkpoint,
            ):
                result = backup_restore.restore_durable_backup(
                    target,
                    backup_path,
                    confirmation_token=preview.confirmation_token or "",
                )

            self.assertEqual(result.status, "restored")
            self.assertTrue(observed)
            self.assertTrue(all(observed))

    def test_exact_orphan_restore_temporary_requires_confirmed_cleanup(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")
            assert result.backup_name is not None
            final = target / "backups" / result.backup_name
            final.write_bytes(backup_path.read_bytes())
            if os.name == "posix":
                final.chmod(0o600)
            temporary = final.with_name(
                f".{final.name}.mentat-init-{'a' * 32}.tmp"
            )
            os.link(final, temporary)
            before = {name: (target / name).read_bytes() for name in data_layout.SEED_FILE_NAMES}

            recovery = backup_restore.preview_durable_restore(target, backup_path)

            self.assertEqual(recovery.status, "recovery_required")
            self.assertTrue(temporary.exists())
            cli_preview = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "server.py"),
                    "--data-dir",
                    str(target),
                    "--preview-restore",
                    "--restore-backup",
                    str(backup_path),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(cli_preview.returncode, 0, cli_preview.stderr)
            self.assertEqual(json.loads(cli_preview.stdout)["status"], "recovery_required")
            recovered = backup_restore.restore_durable_backup(
                target,
                backup_path,
                confirmation_token=recovery.confirmation_token or "",
            )
            self.assertEqual(recovered.status, "recovered")
            self.assertFalse(temporary.exists())
            self.assertTrue(final.exists())
            self.assertEqual(final.stat().st_nlink, 1)
            self.assertEqual(
                before,
                {name: (target / name).read_bytes() for name in data_layout.SEED_FILE_NAMES},
            )
            self.assertEqual(
                backup_restore.preview_durable_restore(target, backup_path).status,
                "ready",
            )

    def test_recovery_confirmation_binds_archive_and_live_documents(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")
            assert result.backup_name is not None
            temporary = target / "backups" / (
                f".{result.backup_name}.mentat-init-{'b' * 32}.tmp"
            )
            temporary.write_bytes(backup_path.read_bytes())
            if os.name == "posix":
                temporary.chmod(0o600)
            recovery = backup_restore.preview_durable_restore(target, backup_path)
            old_tasks = (target / "tasks.json").read_bytes()
            (target / "tasks.json").write_text(
                '[{"id":"changed-after-recovery-preview"}]\n',
                encoding="utf-8",
            )
            if os.name == "posix":
                (target / "tasks.json").chmod(0o600)

            stale_live = backup_restore.restore_durable_backup(
                target,
                backup_path,
                confirmation_token=recovery.confirmation_token or "",
            )

            self.assertEqual(stale_live.status, "blocked")
            self.assertTrue(temporary.exists())
            (target / "tasks.json").write_bytes(old_tasks)
            if os.name == "posix":
                (target / "tasks.json").chmod(0o600)
            _alt_source, alternate_path, _alt_result = self.create_source_backup(
                base / "alternate"
            )
            stale_archive = backup_restore.restore_durable_backup(
                target,
                alternate_path,
                confirmation_token=recovery.confirmation_token or "",
            )
            self.assertEqual(stale_archive.status, "blocked")
            self.assertTrue(temporary.exists())

    def test_recovery_confirmation_binds_restore_state_presence(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, result = self.create_source_backup(base)
            assert result.backup_name is not None
            for scenario in ("appeared", "removed"):
                with self.subTest(scenario=scenario):
                    _seeds, target = self.make_current(
                        base,
                        f"target-{scenario}",
                        scenario,
                    )
                    temporary = target / "backups" / (
                        f".{result.backup_name}.mentat-init-{'d' * 32}.tmp"
                    )
                    temporary.write_bytes(backup_path.read_bytes())
                    state_path = target / "config" / backup_restore.RESTORE_STATE_NAME
                    if scenario == "removed":
                        state_path.write_bytes(b'{"marker":"state"}\n')
                    if os.name == "posix":
                        temporary.chmod(0o600)
                        if state_path.exists():
                            state_path.chmod(0o600)
                    recovery = backup_restore.preview_durable_restore(target, backup_path)
                    self.assertEqual(recovery.status, "recovery_required")
                    if scenario == "appeared":
                        state_path.write_bytes(b'{"marker":"state"}\n')
                        if os.name == "posix":
                            state_path.chmod(0o600)
                    else:
                        state_path.unlink()

                    stale = backup_restore.restore_durable_backup(
                        target,
                        backup_path,
                        confirmation_token=recovery.confirmation_token or "",
                    )

                    self.assertEqual(stale.status, "blocked")
                    self.assertTrue(temporary.exists())

    def test_recovery_rechecks_state_evidence_adjacent_to_unlink(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, result = self.create_source_backup(base)
            assert result.backup_name is not None
            for scenario in ("appeared", "removed"):
                with self.subTest(scenario=scenario):
                    _seeds, target = self.make_current(
                        base,
                        f"adjacent-{scenario}",
                        scenario,
                    )
                    temporary = target / "backups" / (
                        f".{result.backup_name}.mentat-init-{'e' * 32}.tmp"
                    )
                    temporary.write_bytes(backup_path.read_bytes())
                    state_path = target / "config" / backup_restore.RESTORE_STATE_NAME
                    if scenario == "removed":
                        state_path.write_bytes(b'{"marker":"state"}\n')
                    if os.name == "posix":
                        temporary.chmod(0o600)
                        if state_path.exists():
                            state_path.chmod(0o600)
                    recovery = backup_restore.preview_durable_restore(target, backup_path)
                    real_evidence = backup_restore._restore_state_evidence
                    locked_calls = 0

                    def change_at_adjacent_check(selected, descriptor):
                        nonlocal locked_calls
                        locked_calls += 1
                        if locked_calls == 2:
                            if scenario == "appeared":
                                state_path.write_bytes(b'{"marker":"state"}\n')
                                if os.name == "posix":
                                    state_path.chmod(0o600)
                            else:
                                state_path.unlink()
                        return real_evidence(selected, descriptor)

                    with (
                        patch.object(
                            backup_restore,
                            "preview_durable_restore",
                            return_value=recovery,
                        ),
                        patch.object(
                            backup_restore,
                            "_restore_state_evidence",
                            side_effect=change_at_adjacent_check,
                        ),
                    ):
                        stale = backup_restore.restore_durable_backup(
                            target,
                            backup_path,
                            confirmation_token=recovery.confirmation_token or "",
                        )

                    self.assertEqual(locked_calls, 2)
                    self.assertEqual(stale.status, "blocked")
                    self.assertTrue(temporary.exists())

    def test_backup_temporary_cleanup_preserves_bound_restore_state(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")
            assert result.backup_name is not None
            temporary = target / "backups" / (
                f".{result.backup_name}.mentat-init-{'f' * 32}.tmp"
            )
            temporary.write_bytes(backup_path.read_bytes())
            state_path = target / "config" / backup_restore.RESTORE_STATE_NAME
            state_path.write_bytes(b'{"marker":"state"}\n')
            if os.name == "posix":
                temporary.chmod(0o600)
                state_path.chmod(0o600)
            recovery = backup_restore.preview_durable_restore(target, backup_path)

            recovered = backup_restore.restore_durable_backup(
                target,
                backup_path,
                confirmation_token=recovery.confirmation_token or "",
            )

            self.assertEqual(recovered.status, "recovered")
            self.assertFalse(temporary.exists())
            self.assertTrue(state_path.exists())
            self.assertEqual(backup_restore.restore_startup_status(target), "invalid")

    def test_new_restore_temporary_after_preview_blocks_confirmation(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")
            preview = backup_restore.preview_durable_restore(target, backup_path)
            before = {name: (target / name).read_bytes() for name in data_layout.SEED_FILE_NAMES}
            assert result.backup_name is not None
            temporary = target / "backups" / (
                f".{result.backup_name}.mentat-init-{'c' * 32}.tmp"
            )
            real_preview = backup_restore.preview_durable_restore

            def preview_then_publish_temporary(*args, **kwargs):
                internal = real_preview(*args, **kwargs)
                temporary.write_bytes(backup_path.read_bytes())
                if os.name == "posix":
                    temporary.chmod(0o600)
                return internal

            with patch.object(
                backup_restore,
                "preview_durable_restore",
                side_effect=preview_then_publish_temporary,
            ):
                blocked = backup_restore.restore_durable_backup(
                    target,
                    backup_path,
                    confirmation_token=preview.confirmation_token or "",
                )

            self.assertEqual(blocked.status, "blocked")
            self.assertTrue(temporary.exists())
            self.assertEqual(
                before,
                {name: (target / name).read_bytes() for name in data_layout.SEED_FILE_NAMES},
            )
            self.assertEqual(
                backup_restore.preview_durable_restore(target, backup_path).status,
                "recovery_required",
            )

    def test_interrupted_restore_resumes_only_exact_old_or_new_documents(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            source, backup_path, _result = self.create_source_backup(base)
            _seeds, target = self.make_current(
                base,
                "target",
                "target",
                extra_markers=True,
            )
            preview = backup_restore.preview_durable_restore(target, backup_path)
            real_write = backup_restore.write_json_bytes_atomic
            calls = 0

            def interrupt_second(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated interruption")
                return real_write(*args, **kwargs)

            with patch.object(
                backup_restore,
                "write_json_bytes_atomic",
                side_effect=interrupt_second,
            ):
                partial = backup_restore.restore_durable_backup(
                    target,
                    backup_path,
                    confirmation_token=preview.confirmation_token or "",
                )
            self.assertEqual(partial.status, "partial_failure")
            self.assertEqual(backup_restore.restore_startup_status(target), "invalid")
            startup_snapshot = self.snapshot(target)
            startup_error = runtime_config.prepare_data_root_for_startup(self.config(target))
            self.assertIn("restore_incomplete_or_invalid", startup_error or "")
            self.assertEqual(startup_snapshot, self.snapshot(target))
            approved = data_layout._absolute_without_following(target)
            with (
                patch.object(server, "DATA_DIR", approved),
                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                patch.object(server, "DATA_MUTATION_LOCK", True),
            ):
                with self.assertRaises(OSError):
                    server.read_json_file("tasks.json", [])
                with self.assertRaises(OSError):
                    server.update_json_file(
                        "tasks.json",
                        [],
                        lambda _current: ([{"id": "must-not-write"}], None),
                    )
            self.assertEqual(startup_snapshot, self.snapshot(target))

            resume = backup_restore.preview_durable_restore(target, backup_path)
            self.assertEqual(resume.status, "resume_required")
            self.assertEqual(resume.confirmation_token, preview.confirmation_token)
            completed = backup_restore.restore_durable_backup(
                target,
                backup_path,
                confirmation_token=resume.confirmation_token or "",
            )
            self.assertEqual(completed.status, "resumed")
            for name in data_layout.SEED_FILE_NAMES:
                self.assertEqual((target / name).read_bytes(), (source / name).read_bytes())

    def test_startup_rechecks_restore_state_after_waiting_for_shared_lock(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, _result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")
            preview = backup_restore.preview_durable_restore(target, backup_path)
            initial_checked = Event()
            startup_finished = Event()
            startup_errors: list[str | None] = []
            real_startup_status = runtime_config.restore_startup_status

            def observe_initial_status(root):
                status = real_startup_status(root)
                initial_checked.set()
                return status

            def run_startup():
                startup_errors.append(
                    runtime_config.prepare_data_root_for_startup(self.config(target))
                )
                startup_finished.set()

            startup_thread = Thread(target=run_startup)
            try:
                with json_store._durable_mutation_lock(target):
                    with patch.object(
                        runtime_config,
                        "restore_startup_status",
                        side_effect=observe_initial_status,
                    ):
                        startup_thread.start()
                        self.assertTrue(initial_checked.wait(THREAD_TIMEOUT_SECONDS))
                        self.assertFalse(startup_finished.wait(0.1))
                        with patch.object(
                            backup_restore,
                            "write_json_bytes_atomic",
                            side_effect=OSError("simulated first-commit failure"),
                        ):
                            partial = backup_restore.restore_durable_backup(
                                target,
                                backup_path,
                                confirmation_token=preview.confirmation_token or "",
                            )
                        self.assertEqual(partial.status, "partial_failure")
                        partial_snapshot = self.snapshot(target)
            finally:
                if startup_thread.ident is not None:
                    startup_thread.join(THREAD_TIMEOUT_SECONDS)

            self.assertFalse(startup_thread.is_alive())
            self.assertIn("restore_incomplete_or_invalid", startup_errors[0] or "")
            self.assertEqual(partial_snapshot, self.snapshot(target))

    def test_failure_after_reservation_publication_reports_partial(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, _result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")
            preview = backup_restore.preview_durable_restore(target, backup_path)
            real_publish = backup_restore._publish_restore_state

            def publish_then_fail(*args, **kwargs):
                real_publish(*args, **kwargs)
                raise OSError("simulated post-reservation failure")

            with patch.object(
                backup_restore,
                "_publish_restore_state",
                side_effect=publish_then_fail,
            ):
                result = backup_restore.restore_durable_backup(
                    target,
                    backup_path,
                    confirmation_token=preview.confirmation_token or "",
                )

            self.assertEqual(result.status, "partial_failure")
            self.assertTrue((target / "config" / backup_restore.RESTORE_STATE_NAME).is_file())
            self.assertEqual(
                backup_restore.preview_durable_restore(target, backup_path).status,
                "resume_required",
            )

    def test_noncanonical_reservation_is_not_deleted_at_completion(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, _result = self.create_source_backup(base)
            _seeds, target = self.make_current(
                base,
                "target",
                "target",
                extra_markers=True,
            )
            preview = backup_restore.preview_durable_restore(target, backup_path)
            real_write = backup_restore.write_json_bytes_atomic
            calls = 0

            def rewrite_state_after_last_commit(*args, **kwargs):
                nonlocal calls
                real_write(*args, **kwargs)
                calls += 1
                if calls == 2:
                    state_path = target / "config" / backup_restore.RESTORE_STATE_NAME
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
                    if os.name == "posix":
                        state_path.chmod(0o600)

            with patch.object(
                backup_restore,
                "write_json_bytes_atomic",
                side_effect=rewrite_state_after_last_commit,
            ):
                result = backup_restore.restore_durable_backup(
                    target,
                    backup_path,
                    confirmation_token=preview.confirmation_token or "",
                )

            self.assertEqual(calls, 2)
            self.assertEqual(result.status, "partial_failure")
            self.assertTrue((target / "config" / backup_restore.RESTORE_STATE_NAME).is_file())

    def test_changed_recovery_evidence_blocks_resume_without_overwrite(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, _result = self.create_source_backup(base)
            _seeds, target = self.make_current(
                base,
                "target",
                "target",
                extra_markers=True,
            )
            preview = backup_restore.preview_durable_restore(target, backup_path)
            real_write = backup_restore.write_json_bytes_atomic
            calls = 0

            def interrupt_second(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated interruption")
                return real_write(*args, **kwargs)

            with patch.object(
                backup_restore,
                "write_json_bytes_atomic",
                side_effect=interrupt_second,
            ):
                partial = backup_restore.restore_durable_backup(
                    target,
                    backup_path,
                    confirmation_token=preview.confirmation_token or "",
                )
            self.assertEqual(partial.status, "partial_failure")
            state = json.loads(
                (target / "config" / backup_restore.RESTORE_STATE_NAME).read_text(
                    encoding="utf-8"
                )
            )
            evidence = target / "backups" / state["recovery_backup_name"]
            evidence.write_bytes(b"changed-recovery-evidence")
            if os.name == "posix":
                evidence.chmod(0o600)
            before = {name: (target / name).read_bytes() for name in data_layout.SEED_FILE_NAMES}

            blocked = backup_restore.preview_durable_restore(target, backup_path)

            self.assertEqual(blocked.status, "unsafe")
            self.assertEqual(
                before,
                {name: (target / name).read_bytes() for name in data_layout.SEED_FILE_NAMES},
            )

    def test_unknown_partial_state_fails_closed_and_preserves_conflict(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, _result = self.create_source_backup(base)
            _seeds, target = self.make_current(
                base,
                "target",
                "target",
                extra_markers=True,
            )
            preview = backup_restore.preview_durable_restore(target, backup_path)
            real_write = backup_restore.write_json_bytes_atomic
            calls = 0

            def interrupt_after_first(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("stop")
                return real_write(*args, **kwargs)

            with patch.object(
                backup_restore,
                "write_json_bytes_atomic",
                side_effect=interrupt_after_first,
            ):
                backup_restore.restore_durable_backup(
                    target,
                    backup_path,
                    confirmation_token=preview.confirmation_token or "",
                )
            conflict = b'[{"id":"unknown-conflict"}]\n'
            (target / "tasks.json").write_bytes(conflict)

            blocked = backup_restore.preview_durable_restore(target, backup_path)

            self.assertEqual(blocked.status, "unsafe")
            self.assertEqual((target / "tasks.json").read_bytes(), conflict)

    def test_waiting_server_writer_observes_failed_restore_reservation(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            _source, backup_path, _result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")
            preview = backup_restore.preview_durable_restore(target, backup_path)
            entered = Event()
            release = Event()
            writer_finished = Event()
            results: list[str] = []

            def fail_first_live_commit(*_args, **_kwargs):
                entered.set()
                self.assertTrue(release.wait(THREAD_TIMEOUT_SECONDS))
                raise OSError("simulated commit interruption")

            def run_restore():
                result = backup_restore.restore_durable_backup(
                    target,
                    backup_path,
                    confirmation_token=preview.confirmation_token or "",
                )
                results.append(result.status)

            def run_server_writer():
                try:
                    server.update_json_file(
                        "tasks.json",
                        [],
                        lambda _current: ([{"id": "must-not-write"}], None),
                    )
                except OSError:
                    results.append("server_blocked")
                finally:
                    writer_finished.set()

            approved = data_layout._absolute_without_following(target)
            with (
                patch.object(
                    backup_restore,
                    "write_json_bytes_atomic",
                    side_effect=fail_first_live_commit,
                ),
                patch.object(server, "DATA_DIR", approved),
                patch.object(server, "CONFIGURED_DATA_DIR", approved),
                patch.object(server, "DATA_MUTATION_LOCK", True),
            ):
                restore_thread = Thread(target=run_restore)
                writer_thread = None
                try:
                    restore_thread.start()
                    self.assertTrue(entered.wait(THREAD_TIMEOUT_SECONDS))
                    writer_thread = Thread(target=run_server_writer)
                    writer_thread.start()
                    self.assertFalse(writer_finished.wait(0.1))
                finally:
                    release.set()
                    if restore_thread.ident is not None:
                        restore_thread.join(THREAD_TIMEOUT_SECONDS)
                    if writer_thread is not None and writer_thread.ident is not None:
                        writer_thread.join(THREAD_TIMEOUT_SECONDS)

            self.assertFalse(restore_thread.is_alive())
            self.assertIsNotNone(writer_thread)
            self.assertFalse(writer_thread.is_alive())
            self.assertCountEqual(results, ["partial_failure", "server_blocked"])
            self.assertEqual(backup_restore.restore_startup_status(target), "invalid")
            self.assertNotEqual(
                json.loads((target / "tasks.json").read_text(encoding="utf-8"))[0]["id"],
                "must-not-write",
            )

    def test_cli_contract_is_explicit_and_bounded(self):
        with self.assertRaises(SystemExit):
            runtime_config.parse_cli_args(["--preview-restore"])
        with self.assertRaises(SystemExit):
            runtime_config.parse_cli_args(["--restore-backup", "backup.zip"])
        with self.assertRaises(SystemExit):
            runtime_config.parse_cli_args(["--create-backup", "--preview-restore", "--restore-backup", "x"])

        preview_args = runtime_config.parse_cli_args(
            ["--preview-restore", "--restore-backup", "backup.zip"]
        )
        confirm_args = runtime_config.parse_cli_args(
            ["--confirm-restore", "a" * 64, "--restore-backup", "backup.zip"]
        )
        self.assertTrue(preview_args.preview_restore)
        self.assertEqual(confirm_args.confirm_restore, "a" * 64)

    def test_server_cli_creates_previews_and_confirms_restore(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            source, _unused, _result = self.create_source_backup(base)
            _seeds, target = self.make_current(base, "target", "target")

            created = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "server.py"),
                    "--data-dir",
                    str(source),
                    "--create-backup",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            created_payload = json.loads(created.stdout)
            backup_path = source / "backups" / created_payload["backup_name"]
            previewed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "server.py"),
                    "--data-dir",
                    str(target),
                    "--preview-restore",
                    "--restore-backup",
                    str(backup_path),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(previewed.returncode, 0, previewed.stderr)
            preview_payload = json.loads(previewed.stdout)
            self.assertEqual(preview_payload["status"], "ready")
            self.assertNotIn(str(base), previewed.stdout)
            confirmed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "server.py"),
                    "--data-dir",
                    str(target),
                    "--confirm-restore",
                    preview_payload["confirmation_token"],
                    "--restore-backup",
                    str(backup_path),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
            self.assertEqual(json.loads(confirmed.stdout)["status"], "restored")


if __name__ == "__main__":
    unittest.main()
