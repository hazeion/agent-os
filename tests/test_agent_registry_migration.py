from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Lock, Thread
import unittest
from unittest.mock import patch
import zipfile

import agent_registry_migration
import agent_registry
from agent_registry import (
    AgentRegistry,
    AgentRegistryError,
    authority_receipt,
    initialize_registry_file,
    registry_database_path,
)
from agent_registry_migration import (
    AgentRegistryMigrationError,
    confirm_agent_registry_migration,
    preview_agent_registry_migration,
)
import data_backup_restore
import data_layout
import data_schema
import mentat_db
from mentat import cli as mentat_cli
from mentat_db import MentatDatabaseError, connect as connect_database, database_path
from private_console_unit import _initialize_database
from runtime_config import AppConfig, prepare_data_root_for_startup


class AgentRegistryMigrationTests(unittest.TestCase):
    def make_current(self, base: Path, name: str) -> Path:
        seeds = base / f"{name}-seeds"
        target = base / name
        for root in (seeds, target):
            root.mkdir()
            for filename in data_layout.SEED_FILE_NAMES:
                payload = {"theme": "midnight"} if filename == "dashboard.json" else []
                path = root / filename
                path.write_text(
                    json.dumps(payload, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                if os.name == "posix":
                    path.chmod(0o600)
            for directory in data_layout.DATA_ROOT_DIRECTORY_NAMES:
                child = root / directory
                child.mkdir()
                if os.name == "posix":
                    child.chmod(0o700)
        preview = data_schema.preview_schema_migration(
            seeds,
            target,
            home=base / "home",
        )
        result = data_schema.migrate_data_schema(
            seeds,
            target,
            confirmation_token=preview.confirmation_token or "",
            home=base / "home",
        )
        self.assertEqual(result.status, "migrated")
        console = target / "private" / "console"
        console.mkdir(parents=True, mode=0o700)
        if os.name == "posix":
            (target / "private").chmod(0o700)
            console.chmod(0o700)
        _initialize_database(database_path(target), schema_version=7)
        initialize_registry_file(registry_database_path(target))
        connection = sqlite3.connect(registry_database_path(target))
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO agent_runtime_configs VALUES (?, ?, ?, ?, ?)",
                ("runtime_config_researcher", "hermes", "researcher-main", 1.0, 1.0),
            )
            connection.execute(
                "INSERT INTO mentat_agents VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "agent_researcher",
                    "Researcher",
                    "runtime_config_researcher",
                    '["research.web"]',
                    1.0,
                    1.0,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return target

    def config(self, root: Path) -> AppConfig:
        return AppConfig(
            config_files=(),
            host="127.0.0.1",
            port=8888,
            data_dir=root,
            public_dir=root.parent / "public",
            hermes_home=root.parent / "hermes",
            obsidian_vault=root.parent / "vault",
            data_dir_source="cli",
        )

    def snapshot(self, root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*")
            if path.is_file()
        }

    def test_preview_is_read_only_exact_and_startup_requires_confirmation(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            console = root / "private" / "console"
            if os.name == "posix":
                console.chmod(0o755)
            mode_before = console.stat().st_mode
            before = self.snapshot(root)

            preview = preview_agent_registry_migration(root)

            self.assertEqual(preview.status, "ready")
            self.assertEqual(self.snapshot(root), before)
            self.assertEqual(console.stat().st_mode, mode_before)
            summary = preview.public_summary()
            self.assertEqual(summary["source"]["agent_count"], 1)
            self.assertEqual(
                summary["source"]["agents"][0]["id"],
                "agent_researcher",
            )
            self.assertNotIn("researcher-main", json.dumps(summary))
            startup_issue = prepare_data_root_for_startup(self.config(root)) or ""
            self.assertIn(
                "agent_registry_migration_required",
                startup_issue,
            )
            self.assertIn(
                "python -m mentat.cli agent-registry-migration",
                startup_issue,
            )

    def test_confirmation_backs_up_then_commits_one_authority_and_ignores_source(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            preview = preview_agent_registry_migration(root)
            source_before = registry_database_path(root).read_bytes()

            result = confirm_agent_registry_migration(
                root,
                preview.confirmation_token or "",
            )

            self.assertEqual(result["status"], "migrated")
            self.assertTrue(result["backup_name"].startswith("mentat-backup-v3-"))
            registry = AgentRegistry(
                root,
                supported_runtime_types={"codex", "hermes"},
            )
            self.assertEqual(registry.list_agents()[0].id, "agent_researcher")
            connection = sqlite3.connect(database_path(root))
            connection.row_factory = sqlite3.Row
            try:
                receipt = authority_receipt(connection, required=True)
                self.assertEqual(receipt.source_kind, "legacy")
                self.assertEqual(receipt.source_agent_count, 1)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM mentat_agents").fetchone()[0],
                    1,
                )
            finally:
                connection.close()
            self.assertEqual(
                len(list((root / "backups").glob("mentat-backup-v3-*.zip"))),
                1,
            )
            registry.create_agent(
                agent_id="agent_second",
                name="Second",
                runtime_config_id="runtime_config_second",
                runtime_type="hermes",
                runtime_agent_ref="second-main",
                capabilities=(),
            )
            self.assertEqual(registry_database_path(root).read_bytes(), source_before)
            self.assertEqual(len(registry.list_agents()), 2)
            self.assertEqual(
                preview_agent_registry_migration(root).status,
                "already_converged",
            )
            backup = data_backup_restore.create_durable_backup(root)
            self.assertTrue((backup.backup_name or "").startswith("mentat-backup-v5-"))
            with zipfile.ZipFile(root / "backups" / str(backup.backup_name)) as archive:
                self.assertNotIn(
                    "private/agent-registry.sqlite3",
                    archive.namelist(),
                )

    def test_standalone_only_root_migrates_instead_of_claiming_empty_authority(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            main = database_path(root)
            for candidate in (main, Path(f"{main}-wal"), Path(f"{main}-shm")):
                candidate.unlink(missing_ok=True)

            ordinary = connect_database(root)
            ordinary.close()

            preview = preview_agent_registry_migration(root)

            self.assertEqual(preview.status, "ready")
            self.assertEqual(len(preview.source.records if preview.source else ()), 1)
            confirm_agent_registry_migration(
                root,
                preview.confirmation_token or "",
            )
            self.assertEqual(
                [
                    agent.id
                    for agent in AgentRegistry(
                        root,
                        supported_runtime_types={"codex", "hermes"},
                    ).list_agents()
                ],
                ["agent_researcher"],
            )

    def test_orphan_legacy_sidecars_never_claim_empty_authority(self):
        for suffix in ("-journal", "-wal", "-shm"):
            with self.subTest(suffix=suffix), TemporaryDirectory() as temporary:
                root = self.make_current(Path(temporary), "data")
                main = database_path(root)
                retired = registry_database_path(root)
                for candidate in (
                    main,
                    Path(f"{main}-wal"),
                    Path(f"{main}-shm"),
                    retired,
                    Path(f"{retired}-wal"),
                    Path(f"{retired}-shm"),
                ):
                    candidate.unlink(missing_ok=True)
                orphan = Path(f"{retired}{suffix}")
                orphan.write_bytes(b"orphan")
                if os.name == "posix":
                    orphan.chmod(0o600)

                ordinary = connect_database(root)
                try:
                    self.assertIsNone(authority_receipt(ordinary))
                finally:
                    ordinary.close()

                self.assertEqual(
                    preview_agent_registry_migration(root).status,
                    "blocked",
                )

    def test_fresh_claim_rechecks_a_racing_orphan_sidecar(self):
        for race_call in (2, 3):
            with self.subTest(race_call=race_call), TemporaryDirectory() as temporary:
                root = Path(temporary) / "data"
                orphan = Path(
                    f"{registry_database_path(root)}-wal"
                )
                original = mentat_db.legacy_agent_registry_artifacts_present
                calls = 0

                def race(data_root: Path) -> bool:
                    nonlocal calls
                    calls += 1
                    if calls == race_call:
                        orphan.parent.mkdir(parents=True, exist_ok=True)
                        orphan.write_bytes(b"racing orphan")
                        if os.name == "posix":
                            orphan.chmod(0o600)
                    return original(data_root)

                with patch.object(
                    mentat_db,
                    "legacy_agent_registry_artifacts_present",
                    side_effect=race,
                ):
                    with self.assertRaises(MentatDatabaseError):
                        connect_database(root)

                destination = sqlite3.connect(database_path(root))
                try:
                    self.assertIsNone(authority_receipt(destination))
                finally:
                    destination.close()

    def test_fresh_cleanup_preserves_concurrent_supported_agent_state(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            orphan = Path(f"{registry_database_path(root)}-wal")
            original = mentat_db.legacy_agent_registry_artifacts_present
            calls = 0

            def race_with_agent(data_root: Path) -> bool:
                nonlocal calls
                calls += 1
                if calls == 3:
                    orphan.write_bytes(b"post-cutover orphan")
                    if os.name == "posix":
                        orphan.chmod(0o600)
                    AgentRegistry(
                        root,
                        supported_runtime_types={"codex", "hermes"},
                    ).create_agent(
                        agent_id="agent_concurrent",
                        name="Concurrent",
                        runtime_config_id="runtime_config_concurrent",
                        runtime_type="hermes",
                        runtime_agent_ref="concurrent-main",
                        capabilities=(),
                    )
                return original(data_root)

            with patch.object(
                mentat_db,
                "legacy_agent_registry_artifacts_present",
                side_effect=race_with_agent,
            ):
                with self.assertRaises(MentatDatabaseError):
                    connect_database(root)

            destination = sqlite3.connect(database_path(root))
            destination.row_factory = sqlite3.Row
            try:
                self.assertIsNotNone(authority_receipt(destination, required=True))
                self.assertEqual(
                    destination.execute(
                        "SELECT id FROM mentat_agents"
                    ).fetchone()[0],
                    "agent_concurrent",
                )
                self.assertEqual(
                    destination.execute(
                        "SELECT id FROM agent_runtime_configs"
                    ).fetchone()[0],
                    "runtime_config_concurrent",
                )
            finally:
                destination.close()

    def test_source_sidecar_race_cannot_report_migration_success(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            retired = registry_database_path(root)
            retired.unlink()
            preview = preview_agent_registry_migration(root)
            original_verify = agent_registry_migration._verified_backup

            def verify_with_orphan(*args, **kwargs):
                result = original_verify(*args, **kwargs)
                orphan = Path(f"{retired}-wal")
                orphan.write_bytes(b"racing orphan")
                if os.name == "posix":
                    orphan.chmod(0o600)
                return result

            with patch.object(
                agent_registry_migration,
                "_verified_backup",
                side_effect=verify_with_orphan,
            ):
                with self.assertRaises(AgentRegistryMigrationError) as raised:
                    confirm_agent_registry_migration(
                        root,
                        preview.confirmation_token or "",
                    )

            self.assertNotEqual(raised.exception.code, "migrated")
            destination = sqlite3.connect(database_path(root))
            try:
                self.assertIsNone(authority_receipt(destination))
            finally:
                destination.close()

    def test_post_commit_source_race_removes_exact_import(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            retired = registry_database_path(root)
            retired.unlink()
            preview = preview_agent_registry_migration(root)
            original_connect = (
                agent_registry_migration.connect_for_agent_registry_migration
            )

            class RacingConnection:
                def __init__(self, connection: sqlite3.Connection):
                    self.connection = connection
                    self.raced = False

                def __getattr__(self, name):
                    return getattr(self.connection, name)

                @property
                def row_factory(self):
                    return self.connection.row_factory

                @row_factory.setter
                def row_factory(self, value):
                    self.connection.row_factory = value

                def commit(self):
                    self.connection.commit()
                    if not self.raced:
                        self.raced = True
                        orphan = Path(f"{retired}-wal")
                        orphan.write_bytes(b"post-commit orphan")
                        if os.name == "posix":
                            orphan.chmod(0o600)

            def racing_connect(data_root: Path):
                return RacingConnection(original_connect(data_root))

            with patch.object(
                agent_registry_migration,
                "connect_for_agent_registry_migration",
                side_effect=racing_connect,
            ):
                with self.assertRaises(AgentRegistryMigrationError):
                    confirm_agent_registry_migration(
                        root,
                        preview.confirmation_token or "",
                    )

            destination = sqlite3.connect(database_path(root))
            try:
                self.assertIsNone(authority_receipt(destination))
                self.assertEqual(
                    destination.execute(
                        "SELECT COUNT(*) FROM mentat_agents"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    destination.execute(
                        "SELECT COUNT(*) FROM agent_runtime_configs"
                    ).fetchone()[0],
                    0,
                )
            finally:
                destination.close()

    def test_preconvergence_backup_rejects_orphan_registry_sidecar(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            retired = registry_database_path(root)
            retired.unlink()
            orphan = Path(f"{retired}-wal")
            orphan.write_bytes(b"orphan")
            if os.name == "posix":
                orphan.chmod(0o600)

            backup = data_backup_restore.create_durable_backup(root)

            self.assertEqual(backup.status, "blocked")
            self.assertEqual(backup.issues, ("backup_failed",))
            self.assertEqual(
                list((root / "backups").glob("mentat-backup-v*.zip")),
                [],
            )

    @unittest.skipIf(os.name == "nt", "POSIX symlink contract")
    def test_preview_rejects_symlinked_data_root_without_writes(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            real = self.make_current(base, "real-data")
            alias = base / "linked-data"
            alias.symlink_to(real, target_is_directory=True)

            preview = preview_agent_registry_migration(alias)

            self.assertEqual(preview.status, "blocked")

    def test_legacy_cutover_lock_is_not_public_writable_api(self):
        self.assertFalse(
            hasattr(agent_registry, "hold_legacy_registry_write_lock")
        )

    def test_converged_root_never_reads_retired_registry_artifacts(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            preview = preview_agent_registry_migration(root)
            confirm_agent_registry_migration(
                root,
                preview.confirmation_token or "",
            )
            retired = registry_database_path(root)
            retired.write_bytes(b"not a sqlite database")
            Path(f"{retired}-journal").write_bytes(b"stale journal")
            if os.name == "posix":
                retired.chmod(0o644)

            self.assertEqual(
                preview_agent_registry_migration(root).status,
                "already_converged",
            )
            self.assertIsNone(prepare_data_root_for_startup(self.config(root)))
            self.assertEqual(
                AgentRegistry(
                    root,
                    supported_runtime_types={"codex", "hermes"},
                ).list_agents()[0].id,
                "agent_researcher",
            )

            if os.name == "posix":
                retired.unlink()
                decoy = root / "retired-registry-decoy"
                decoy.write_bytes(b"decoy")
                retired.symlink_to(decoy)
                self.assertEqual(
                    preview_agent_registry_migration(root).status,
                    "already_converged",
                )
                self.assertIsNone(
                    prepare_data_root_for_startup(self.config(root))
                )

    def test_hot_legacy_rollback_journal_blocks_preview(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            source = registry_database_path(root)
            script = (
                "import os, sqlite3, sys; "
                "c=sqlite3.connect(sys.argv[1]); "
                "c.execute('PRAGMA journal_mode=DELETE'); "
                "c.execute('PRAGMA synchronous=FULL'); "
                "c.execute('BEGIN IMMEDIATE'); "
                "c.execute(\"UPDATE mentat_agents SET name='UNCOMMITTED'\"); "
                "os._exit(0)"
            )
            subprocess.run(
                [sys.executable, "-c", script, str(source)],
                check=True,
            )
            self.assertTrue(Path(f"{source}-journal").exists())

            preview = preview_agent_registry_migration(root)

            self.assertEqual(preview.status, "blocked")
            destination = sqlite3.connect(database_path(root))
            try:
                self.assertIsNone(destination.execute(
                    "SELECT name FROM sqlite_master WHERE "
                    "name = 'mentat_agent_registry_state'"
                ).fetchone())
            finally:
                destination.close()

    def test_source_write_is_blocked_through_destination_commit(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            preview = preview_agent_registry_migration(root)
            original_verify = agent_registry_migration._verified_backup
            writer_blocked: list[bool] = []

            def verify_with_competing_writer(*args, **kwargs):
                competing = sqlite3.connect(
                    registry_database_path(root),
                    timeout=0,
                    isolation_level=None,
                )
                try:
                    try:
                        competing.execute("BEGIN IMMEDIATE")
                    except sqlite3.OperationalError:
                        writer_blocked.append(True)
                    else:
                        competing.execute(
                            "UPDATE mentat_agents SET name = 'Raced'"
                        )
                        competing.commit()
                        writer_blocked.append(False)
                finally:
                    competing.close()
                return original_verify(*args, **kwargs)

            with patch.object(
                agent_registry_migration,
                "_verified_backup",
                side_effect=verify_with_competing_writer,
            ):
                confirm_agent_registry_migration(
                    root,
                    preview.confirmation_token or "",
                )

            self.assertEqual(writer_blocked, [True])
            self.assertEqual(
                AgentRegistry(
                    root,
                    supported_runtime_types={"codex", "hermes"},
                ).list_agents()[0].name,
                "Researcher",
            )

    def test_changed_source_rejects_old_token_before_cutover(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            preview = preview_agent_registry_migration(root)
            connection = sqlite3.connect(registry_database_path(root))
            try:
                connection.execute(
                    "UPDATE mentat_agents SET name = 'Changed' WHERE id = 'agent_researcher'"
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaisesRegex(
                AgentRegistryMigrationError,
                "confirmation_invalid",
            ):
                confirm_agent_registry_migration(
                    root,
                    preview.confirmation_token or "",
                )

            connection = sqlite3.connect(database_path(root))
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0],
                    7,
                )
                self.assertIsNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE name = "
                        "'mentat_agent_registry_state'"
                    ).fetchone()
                )
            finally:
                connection.close()

    def test_import_failure_rolls_back_agents_and_receipt_together(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            preview = preview_agent_registry_migration(root)
            with patch.object(
                agent_registry_migration,
                "validate_registry_connection",
                side_effect=AgentRegistryError("injected"),
            ):
                with self.assertRaises(AgentRegistryMigrationError):
                    confirm_agent_registry_migration(
                        root,
                        preview.confirmation_token or "",
                    )
            connection = sqlite3.connect(database_path(root))
            connection.row_factory = sqlite3.Row
            try:
                self.assertIsNone(authority_receipt(connection))
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM mentat_agents").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM agent_runtime_configs"
                    ).fetchone()[0],
                    0,
                )
            finally:
                connection.close()
            self.assertEqual(
                len(list((root / "backups").glob("mentat-backup-v3-*.zip"))),
                1,
            )

    def test_active_server_blocks_preview_without_writes(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            before = self.snapshot(root)
            with patch.object(
                agent_registry_migration,
                "mentat_server_active",
                return_value=True,
            ):
                preview = preview_agent_registry_migration(root)
            self.assertEqual(preview.status, "blocked")
            self.assertEqual(self.snapshot(root), before)

    def test_concurrent_confirmations_commit_the_source_exactly_once(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            preview = preview_agent_registry_migration(root)
            start = Barrier(3)
            result_lock = Lock()
            results: list[str] = []

            def confirm() -> None:
                start.wait()
                try:
                    confirm_agent_registry_migration(
                        root,
                        preview.confirmation_token or "",
                    )
                    outcome = "migrated"
                except AgentRegistryMigrationError:
                    outcome = "rejected"
                with result_lock:
                    results.append(outcome)

            workers = [Thread(target=confirm) for _item in range(2)]
            for worker in workers:
                worker.start()
            start.wait()
            for worker in workers:
                # The second confirmation may wait on the same bounded
                # initialization lock on slower Windows runners.
                worker.join(timeout=data_layout.INITIALIZATION_LOCK_TIMEOUT_SECONDS + 5)
                self.assertFalse(worker.is_alive())

            self.assertEqual(sorted(results), ["migrated", "rejected"])
            agents = AgentRegistry(
                root,
                supported_runtime_types={"codex", "hermes"},
            ).list_agents()
            self.assertEqual([agent.id for agent in agents], ["agent_researcher"])

    def test_unified_cli_previews_and_confirms_without_private_references(self):
        with TemporaryDirectory() as temporary:
            root = self.make_current(Path(temporary), "data")
            preview_output = io.StringIO()
            with redirect_stdout(preview_output):
                preview_code = mentat_cli.main([
                    "agent-registry-migration",
                    "--data-dir",
                    str(root),
                ])
            preview = json.loads(preview_output.getvalue())

            self.assertEqual(preview_code, 0)
            self.assertTrue(preview["ok"])
            self.assertEqual(preview["status"], "ready")
            self.assertNotIn("researcher-main", json.dumps(preview))

            confirm_output = io.StringIO()
            with redirect_stdout(confirm_output):
                confirm_code = mentat_cli.main([
                    "agent-registry-migration",
                    "--data-dir",
                    str(root),
                    "--confirm",
                    preview["confirmation_token"],
                ])
            confirmed = json.loads(confirm_output.getvalue())

            self.assertEqual(confirm_code, 0)
            self.assertTrue(confirmed["ok"])
            self.assertEqual(confirmed["status"], "migrated")
            self.assertNotIn("researcher-main", json.dumps(confirmed))


if __name__ == "__main__":
    unittest.main()
