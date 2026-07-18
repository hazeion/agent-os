from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

import data_migration
from data_layout import SEED_FILE_NAMES
from data_migration import (
    MAX_MIGRATION_BACKUP_BYTES,
    MIGRATION_RECEIPT_NAME,
    MIGRATION_STATE_NAME,
    migrate_legacy_data,
    migration_receipt_valid,
    preview_legacy_migration,
)


class LegacyDataMigrationTests(unittest.TestCase):
    def write_seed_inventory(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for name in SEED_FILE_NAMES:
            payload = {"theme": "midnight"} if name == "dashboard.json" else []
            (root / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def write_legacy_inventory(self, seed_root: Path, legacy_root: Path) -> None:
        legacy_root.mkdir(parents=True, exist_ok=True)
        for name in SEED_FILE_NAMES:
            raw = (seed_root / name).read_bytes()
            if name == "tasks.json":
                raw = b'[{"id":"operator-secret-task","title":"Keep me"}]\n'
            (legacy_root / name).write_bytes(raw)
        (legacy_root / "runtime").mkdir()
        (legacy_root / "runtime" / "private.txt").write_text(
            "excluded-private-runtime",
            encoding="utf-8",
        )

    def tree_snapshot(self, root: Path) -> dict[str, tuple[int, bytes | None]]:
        if not root.exists():
            return {}
        return {
            str(path.relative_to(root)): (
                path.lstat().st_mtime_ns,
                path.read_bytes() if path.is_file() else None,
            )
            for path in root.rglob("*")
        }

    def test_preview_is_exact_bounded_state_bound_and_read_only(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seed_inventory(seeds)
            self.write_legacy_inventory(seeds, legacy)
            before = self.tree_snapshot(root)

            preview = preview_legacy_migration(
                seeds,
                legacy,
                target,
                home=root / "home",
            )
            summary = preview.public_summary()

            self.assertEqual(preview.status, "ready")
            self.assertRegex(preview.confirmation_token or "", r"^[0-9a-f]{64}$")
            self.assertEqual(len(summary["items"]), len(SEED_FILE_NAMES))
            self.assertEqual({item["name"] for item in summary["items"]}, set(SEED_FILE_NAMES))
            self.assertEqual({item["source"] for item in summary["items"]}, {"legacy"})
            self.assertEqual({item["classification"] for item in summary["items"]}, {"durable_operator"})
            self.assertEqual(summary["excluded"], [{
                "name": "runtime/",
                "classification": "deferred_private_runtime",
                "action": "excluded",
            }])
            encoded = json.dumps(summary)
            self.assertNotIn(str(root), encoded)
            self.assertNotIn("operator-secret-task", encoded)
            self.assertNotIn("sha256", encoded.lower())
            self.assertEqual(before, self.tree_snapshot(root))

            (legacy / "tasks.json").write_text("[]\n", encoding="utf-8")
            changed = preview_legacy_migration(seeds, legacy, target, home=root / "home")
            self.assertNotEqual(preview.confirmation_token, changed.confirmation_token)

    def test_migration_backs_up_before_copying_verifies_and_preserves_source(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seed_inventory(seeds)
            self.write_legacy_inventory(seeds, legacy)
            source_before = self.tree_snapshot(legacy)
            preview = preview_legacy_migration(seeds, legacy, target, home=root / "home")
            token = preview.confirmation_token or ""
            backup = target / "backups" / f"legacy-migration-v1-{token[:24]}.zip"
            original_publish = data_migration._publish_destination
            observed_backup: list[bool] = []

            def assert_backup_first(*args, **kwargs):
                observed_backup.append(
                    backup.is_file()
                    and data_migration._validated_backup_matches(backup, preview)
                )
                return original_publish(*args, **kwargs)

            with patch.object(
                data_migration,
                "_publish_destination",
                side_effect=assert_backup_first,
            ):
                result = migrate_legacy_data(
                    seeds,
                    legacy,
                    target,
                    confirmation_token=token,
                    home=root / "home",
                )

            self.assertEqual(result.status, "migrated")
            self.assertTrue(observed_backup)
            self.assertTrue(all(observed_backup))
            self.assertEqual(source_before, self.tree_snapshot(legacy))
            for name in SEED_FILE_NAMES:
                self.assertEqual((target / name).read_bytes(), (legacy / name).read_bytes())
            self.assertTrue(migration_receipt_valid(target))
            repeated_confirmation = migrate_legacy_data(
                seeds,
                legacy,
                target,
                confirmation_token=token,
                home=root / "home",
            )
            self.assertEqual(repeated_confirmation.status, "blocked")
            self.assertIn(
                "migration_already_complete",
                repeated_confirmation.issues,
            )
            with zipfile.ZipFile(backup, "r") as archive:
                expected = {"manifest.json"} | {f"data/{name}" for name in SEED_FILE_NAMES}
                self.assertEqual(set(archive.namelist()), expected)
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["protocol_version"], 1)
                self.assertNotIn(str(root), json.dumps(manifest))
                for name in SEED_FILE_NAMES:
                    self.assertEqual(archive.read(f"data/{name}"), (legacy / name).read_bytes())
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
            encoded = json.dumps(result.public_summary())
            self.assertNotIn(str(root), encoded)
            self.assertNotIn("operator-secret-task", encoded)
            self.assertNotIn("sha256", encoded.lower())

    def test_wrong_or_stale_confirmation_and_destination_conflict_write_nothing(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seed_inventory(seeds)
            self.write_legacy_inventory(seeds, legacy)
            preview = preview_legacy_migration(seeds, legacy, target, home=root / "home")

            wrong = migrate_legacy_data(
                seeds,
                legacy,
                target,
                confirmation_token="0" * 64,
                home=root / "home",
            )
            self.assertEqual(wrong.status, "blocked")
            self.assertFalse(target.exists())

            (legacy / "tasks.json").write_text("[]\n", encoding="utf-8")
            stale = migrate_legacy_data(
                seeds,
                legacy,
                target,
                confirmation_token=preview.confirmation_token or "",
                home=root / "home",
            )
            self.assertEqual(stale.status, "blocked")
            self.assertFalse(target.exists())

            target.mkdir()
            operator = b'[{"id":"destination-wins-only-by-refusal"}]\n'
            (target / "tasks.json").write_bytes(operator)
            (target / "projects.json").write_bytes((legacy / "projects.json").read_bytes())
            if os.name == "posix":
                (target / "projects.json").chmod(0o600)
            conflict = preview_legacy_migration(seeds, legacy, target, home=root / "home")
            self.assertEqual(conflict.status, "conflict")
            self.assertIsNone(conflict.confirmation_token)
            by_name = {item.name: item for item in conflict.items}
            self.assertEqual(by_name["tasks.json"].action, "conflict")
            self.assertEqual(by_name["projects.json"].action, "conflict")
            self.assertEqual(by_name["attention.json"].action, "migrate")
            self.assertEqual(by_name["tasks.json"].source, "legacy")
            self.assertIn("legacy_destination_conflict:tasks.json", conflict.issues)
            self.assertIn("legacy_destination_conflict:projects.json", conflict.issues)
            self.assertEqual((target / "tasks.json").read_bytes(), operator)
            self.assertFalse((target / "backups").exists())

    def test_confirmation_token_distinguishes_exact_root_spellings(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "Seeds"
            legacy = root / "Legacy"
            target = root / "Target"
            self.write_seed_inventory(seeds)
            self.write_legacy_inventory(seeds, legacy)
            preview = preview_legacy_migration(
                seeds,
                legacy,
                target,
                home=root / "home",
            )

            differently_spelled = data_migration._preview_token(
                root / "seeds",
                root / "legacy",
                root / "target",
                preview._snapshots,
            )
            rejected = migrate_legacy_data(
                seeds,
                legacy,
                root / "target",
                confirmation_token=preview.confirmation_token or "",
                home=root / "home",
            )

            self.assertNotEqual(preview.confirmation_token, differently_spelled)
            self.assertEqual(rejected.status, "blocked")
            self.assertFalse((root / "target").exists())

    def test_execution_repreviews_under_lock_and_rejects_changed_source(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seed_inventory(seeds)
            self.write_legacy_inventory(seeds, legacy)
            token = preview_legacy_migration(
                seeds,
                legacy,
                target,
                home=root / "home",
            ).confirmation_token or ""
            real_preview = data_migration._preview_guarded
            calls = 0

            def change_source_before_locked_preview(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    (legacy / "tasks.json").write_text(
                        '[{"id":"changed-after-confirmation"}]\n',
                        encoding="utf-8",
                    )
                return real_preview(*args, **kwargs)

            with patch.object(
                data_migration,
                "_preview_guarded",
                side_effect=change_source_before_locked_preview,
            ):
                result = migrate_legacy_data(
                    seeds,
                    legacy,
                    target,
                    confirmation_token=token,
                    home=root / "home",
                )

            self.assertEqual(result.status, "blocked")
            self.assertIn("migration_state_changed", result.issues)
            self.assertFalse(any((target / name).exists() for name in SEED_FILE_NAMES))
            self.assertFalse(list((target / "backups").glob("*.zip")))

    def test_destination_race_never_overwrites_operator_bytes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seed_inventory(seeds)
            self.write_legacy_inventory(seeds, legacy)
            token = preview_legacy_migration(
                seeds,
                legacy,
                target,
                home=root / "home",
            ).confirmation_token or ""
            original_publish = data_migration._publish_destination
            operator = b'[{"id":"raced-operator-value"}]\n'
            raced_name = SEED_FILE_NAMES[0]
            raced = False

            def publish_after_race(snapshot, destination, **kwargs):
                nonlocal raced
                if not raced:
                    raced = True
                    destination.write_bytes(operator)
                return original_publish(snapshot, destination, **kwargs)

            with patch.object(
                data_migration,
                "_publish_destination",
                side_effect=publish_after_race,
            ):
                result = migrate_legacy_data(
                    seeds,
                    legacy,
                    target,
                    confirmation_token=token,
                    home=root / "home",
                )

            self.assertEqual(result.status, "partial_failure")
            self.assertNotIn(
                "verified",
                {item.status for item in result.items},
            )
            self.assertEqual((target / raced_name).read_bytes(), operator)
            self.assertFalse(migration_receipt_valid(target))

    def test_interrupted_migration_resumes_only_matching_partial_state(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seed_inventory(seeds)
            self.write_legacy_inventory(seeds, legacy)
            preview = preview_legacy_migration(seeds, legacy, target, home=root / "home")
            token = preview.confirmation_token or ""
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
                interrupted = migrate_legacy_data(
                    seeds,
                    legacy,
                    target,
                    confirmation_token=token,
                    home=root / "home",
                )

            self.assertEqual(interrupted.status, "partial_failure")
            self.assertNotIn(
                "verified",
                {item.status for item in interrupted.items},
            )
            self.assertEqual(len([name for name in SEED_FILE_NAMES if (target / name).exists()]), 1)
            before_resume_preview = self.tree_snapshot(root)
            resumed_preview = preview_legacy_migration(seeds, legacy, target, home=root / "home")
            self.assertEqual(resumed_preview.status, "resume_required")
            self.assertEqual(resumed_preview.confirmation_token, token)
            self.assertEqual(before_resume_preview, self.tree_snapshot(root))

            resumed = migrate_legacy_data(
                seeds,
                legacy,
                target,
                confirmation_token=token,
                home=root / "home",
            )
            self.assertEqual(resumed.status, "resumed")
            self.assertTrue(migration_receipt_valid(target))
            repeat = preview_legacy_migration(seeds, legacy, target, home=root / "home")
            self.assertEqual(repeat.status, "already_migrated")
            self.assertIsNone(repeat.confirmation_token)

    def test_tampered_partial_destination_or_backup_fails_closed(self):
        for tamper in ("destination", "backup"):
            with self.subTest(tamper=tamper), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                legacy = root / "legacy"
                target = root / "target"
                self.write_seed_inventory(seeds)
                self.write_legacy_inventory(seeds, legacy)
                preview = preview_legacy_migration(seeds, legacy, target, home=root / "home")
                token = preview.confirmation_token or ""
                original_publish = data_migration._publish_destination
                calls = 0

                def interrupt_after_one(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise OSError("simulated interruption")
                    return original_publish(*args, **kwargs)

                with patch.object(data_migration, "_publish_destination", side_effect=interrupt_after_one):
                    migrate_legacy_data(
                        seeds,
                        legacy,
                        target,
                        confirmation_token=token,
                        home=root / "home",
                    )
                if tamper == "destination":
                    created = next(target / name for name in SEED_FILE_NAMES if (target / name).exists())
                    if created.name == "dashboard.json":
                        created.write_text('{"tampered":true}\n', encoding="utf-8")
                    else:
                        created.write_text('[{"tampered":true}]\n', encoding="utf-8")
                else:
                    backup = target / "backups" / f"legacy-migration-v1-{token[:24]}.zip"
                    backup.write_bytes(b"not-a-valid-backup")

                blocked = preview_legacy_migration(seeds, legacy, target, home=root / "home")
                self.assertEqual(blocked.status, "unsafe")
                self.assertIsNone(blocked.confirmation_token)
                self.assertFalse(migration_receipt_valid(target))

    def test_unknown_or_linked_legacy_entries_fail_before_target_creation(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seed_inventory(seeds)
            self.write_legacy_inventory(seeds, legacy)
            (legacy / "unknown-private.txt").write_text("do not copy", encoding="utf-8")

            unknown = preview_legacy_migration(seeds, legacy, target, home=root / "home")
            self.assertEqual(unknown.status, "unsafe")
            self.assertIn("unsupported_legacy_entries", unknown.issues)
            self.assertFalse(target.exists())

            (legacy / "unknown-private.txt").unlink()
            original = legacy / "tasks.json"
            outside = root / "outside.json"
            outside.write_text("[]\n", encoding="utf-8")
            original.unlink()
            try:
                original.symlink_to(outside)
            except OSError:
                self.skipTest("symlink creation unavailable")
            linked = preview_legacy_migration(seeds, legacy, target, home=root / "home")
            self.assertEqual(linked.status, "unsafe")
            self.assertTrue(any("legacy_symlink:tasks.json" in issue for issue in linked.issues))
            self.assertFalse(target.exists())

    def test_hard_linked_legacy_and_seed_fallback_sources_fail_closed(self):
        for source_kind in ("legacy", "seed_fallback"):
            with self.subTest(source_kind=source_kind), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                legacy = root / "legacy"
                target = root / "target"
                self.write_seed_inventory(seeds)
                self.write_legacy_inventory(seeds, legacy)
                name = "tasks.json" if source_kind == "legacy" else "projects.json"
                selected = legacy / name if source_kind == "legacy" else seeds / name
                outside = root / f"outside-{name}"
                outside.write_text('[{"id":"outside-linked-data"}]\n', encoding="utf-8")
                selected.unlink()
                if source_kind == "seed_fallback":
                    (legacy / name).unlink()
                try:
                    os.link(outside, selected)
                except OSError:
                    self.skipTest("hard-link creation unavailable")

                preview = preview_legacy_migration(
                    seeds,
                    legacy,
                    target,
                    home=root / "home",
                )

                self.assertEqual(preview.status, "unsafe")
                self.assertIsNone(preview.confirmation_token)
                self.assertFalse(target.exists())

    def test_dangling_control_and_backup_links_fail_before_migration_writes(self):
        for artifact in ("receipt", "reservation", "backup"):
            with self.subTest(artifact=artifact), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                legacy = root / "legacy"
                target = root / "target"
                self.write_seed_inventory(seeds)
                self.write_legacy_inventory(seeds, legacy)
                token = (
                    preview_legacy_migration(seeds, legacy, target, home=root / "home")
                    .confirmation_token
                    or ""
                )
                if artifact == "backup":
                    parent = target / "backups"
                    name = f"legacy-migration-v1-{token[:24]}.zip"
                else:
                    parent = target / "config"
                    name = (
                        MIGRATION_RECEIPT_NAME
                        if artifact == "receipt"
                        else MIGRATION_STATE_NAME
                    )
                parent.mkdir(parents=True)
                try:
                    (parent / name).symlink_to(root / "missing-artifact")
                except OSError:
                    self.skipTest("symlink creation unavailable")
                before = self.tree_snapshot(root)

                preview = preview_legacy_migration(
                    seeds,
                    legacy,
                    target,
                    home=root / "home",
                )

                self.assertEqual(preview.status, "unsafe")
                self.assertIsNone(preview.confirmation_token)
                self.assertEqual(before, self.tree_snapshot(root))
                self.assertFalse(any((target / item).exists() for item in SEED_FILE_NAMES))

    def test_missing_invalid_and_oversized_inputs_fail_closed(self):
        cases = ("missing_seed", "invalid_legacy", "oversized_legacy")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                legacy = root / "legacy"
                target = root / "target"
                self.write_seed_inventory(seeds)
                self.write_legacy_inventory(seeds, legacy)
                if case == "missing_seed":
                    (seeds / "projects.json").unlink()
                elif case == "invalid_legacy":
                    (legacy / "projects.json").write_text("{}\n", encoding="utf-8")
                else:
                    with (legacy / "projects.json").open("wb") as handle:
                        handle.truncate(data_migration.MAX_PREFLIGHT_JSON_BYTES + 1)

                preview = preview_legacy_migration(
                    seeds,
                    legacy,
                    target,
                    home=root / "home",
                )

                self.assertEqual(preview.status, "unsafe")
                self.assertIsNone(preview.confirmation_token)
                self.assertFalse(target.exists())

    def test_source_read_failure_does_not_expose_exception_paths(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seed_inventory(seeds)
            self.write_legacy_inventory(seeds, legacy)
            private_path = root / "private-operator-path"

            with patch.object(
                data_migration,
                "_load_snapshots",
                side_effect=FileNotFoundError(str(private_path)),
            ):
                summary = preview_legacy_migration(
                    seeds,
                    legacy,
                    target,
                    home=root / "home",
                ).public_summary()

            self.assertEqual(summary["status"], "unsafe")
            self.assertNotIn(str(root), json.dumps(summary))
            self.assertEqual(
                summary["issues"],
                ["migration_source_changed_or_invalid"],
            )

    def test_partial_legacy_inventory_uses_packaged_seeds_explicitly(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seed_inventory(seeds)
            legacy.mkdir()
            (legacy / "tasks.json").write_text(
                '[{"id":"only-legacy-document"}]\n',
                encoding="utf-8",
            )

            preview = preview_legacy_migration(seeds, legacy, target, home=root / "home")
            sources = {item.name: item.source for item in preview.items}

            self.assertEqual(preview.status, "ready")
            self.assertEqual(sources["tasks.json"], "legacy")
            self.assertEqual(
                {source for name, source in sources.items() if name != "tasks.json"},
                {"packaged_seed"},
            )

    def test_unsafe_root_relations_fail_without_writes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            self.write_seed_inventory(seeds)
            self.write_legacy_inventory(seeds, legacy)

            overlap = preview_legacy_migration(
                seeds,
                legacy,
                legacy / "target",
                home=root / "home",
            )
            broad = preview_legacy_migration(
                seeds,
                legacy,
                root / "home",
                home=root / "home",
            )

            self.assertEqual(overlap.status, "unsafe")
            self.assertIn("legacy_target_overlap", overlap.issues)
            self.assertEqual(broad.status, "unsafe")
            self.assertIn("migration_root_too_broad", broad.issues)
            self.assertFalse((legacy / "target").exists())
            self.assertFalse((root / "home").exists())

    def test_invalid_reservation_receipt_and_backup_metadata_fail_closed(self):
        for tamper in (
            "reservation",
            "receipt",
            "destination_mode",
            "backup_size",
            "backup_mode",
        ):
            if tamper in {"destination_mode", "backup_mode"} and os.name != "posix":
                continue
            with self.subTest(tamper=tamper), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                seeds = root / "seeds"
                legacy = root / "legacy"
                target = root / "target"
                self.write_seed_inventory(seeds)
                self.write_legacy_inventory(seeds, legacy)
                preview = preview_legacy_migration(seeds, legacy, target, home=root / "home")
                token = preview.confirmation_token or ""

                if tamper in {"receipt", "destination_mode"}:
                    result = migrate_legacy_data(
                        seeds,
                        legacy,
                        target,
                        confirmation_token=token,
                        home=root / "home",
                    )
                    self.assertEqual(result.status, "migrated")
                    if tamper == "receipt":
                        receipt = target / "config" / MIGRATION_RECEIPT_NAME
                        document = json.loads(receipt.read_text(encoding="utf-8"))
                        document["migration_id"] = "0" * 24
                        receipt.write_text(json.dumps(document) + "\n", encoding="utf-8")
                    else:
                        (target / "tasks.json").chmod(0o644)
                else:
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
                        migrate_legacy_data(
                            seeds,
                            legacy,
                            target,
                            confirmation_token=token,
                            home=root / "home",
                        )
                    if tamper == "reservation":
                        state = target / "config" / MIGRATION_STATE_NAME
                        document = json.loads(state.read_text(encoding="utf-8"))
                        document["preview_token"] = "0" * 64
                        state.write_text(json.dumps(document) + "\n", encoding="utf-8")
                    else:
                        backup = target / "backups" / f"legacy-migration-v1-{token[:24]}.zip"
                        if tamper == "backup_size":
                            with backup.open("r+b") as handle:
                                handle.truncate(MAX_MIGRATION_BACKUP_BYTES + 1)
                        else:
                            backup.chmod(0o644)

                blocked = preview_legacy_migration(
                    seeds,
                    legacy,
                    target,
                    home=root / "home",
                )
                self.assertEqual(blocked.status, "unsafe")
                self.assertIsNone(blocked.confirmation_token)
                self.assertFalse(migration_receipt_valid(target))

    def test_receipt_rejects_semantically_forged_backup_manifest(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seed_inventory(seeds)
            self.write_legacy_inventory(seeds, legacy)
            preview = preview_legacy_migration(seeds, legacy, target, home=root / "home")
            token = preview.confirmation_token or ""
            result = migrate_legacy_data(
                seeds,
                legacy,
                target,
                confirmation_token=token,
                home=root / "home",
            )
            self.assertEqual(result.status, "migrated")
            backup = target / "backups" / f"legacy-migration-v1-{token[:24]}.zip"
            with zipfile.ZipFile(backup, "r") as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            manifest = json.loads(entries["manifest.json"])
            manifest["excluded"][0]["classification"] = "forged"
            forged_manifest = data_migration._canonical_json(manifest)
            entries["manifest.json"] = forged_manifest
            with zipfile.ZipFile(backup, "w", compression=zipfile.ZIP_STORED) as archive:
                for name in ["manifest.json", *(f"data/{item}" for item in SEED_FILE_NAMES)]:
                    archive.writestr(name, entries[name])
            if os.name == "posix":
                backup.chmod(0o600)
            receipt = target / "config" / MIGRATION_RECEIPT_NAME
            receipt_document = json.loads(receipt.read_text(encoding="utf-8"))
            receipt_document["manifest_sha256"] = data_migration._digest(forged_manifest)
            receipt.write_bytes(data_migration._canonical_json(receipt_document))
            if os.name == "posix":
                receipt.chmod(0o600)

            self.assertFalse(migration_receipt_valid(target))
            blocked = preview_legacy_migration(seeds, legacy, target, home=root / "home")
            self.assertEqual(blocked.status, "unsafe")
            self.assertIn("invalid_migration_receipt", blocked.issues)


if __name__ == "__main__":
    unittest.main()
