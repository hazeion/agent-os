from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "DATA_LAYOUT.md"
CONTRACT = CONTRACT_PATH.read_text(encoding="utf-8") if CONTRACT_PATH.exists() else ""
ARCHITECTURE = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
ROADMAP = (ROOT / "ROAD_TO_BETA.md").read_text(encoding="utf-8")
RUNTIME_CONFIG = (ROOT / "runtime_config.py").read_text(encoding="utf-8")
DATA_MIGRATION = (ROOT / "data_migration.py").read_text(encoding="utf-8")
DATA_SCHEMA = (ROOT / "data_schema.py").read_text(encoding="utf-8")
SHARED_CONFIG = (ROOT / "mentat.toml").read_text(encoding="utf-8")
REQUIREMENTS = (ROOT / "requirements.txt").read_text(encoding="utf-8")


class DataLayoutContractTests(unittest.TestCase):
    def test_canonical_contract_distinguishes_read_only_from_writable_work(self):
        normalized = " ".join(CONTRACT.split())
        self.assertTrue(CONTRACT_PATH.exists())
        self.assertIn("Status: Milestone 1A contract approved", CONTRACT)
        self.assertIn("Milestone 1B initialization", CONTRACT)
        self.assertIn("Milestone 1C legacy migration", CONTRACT)
        self.assertIn("Milestone 1D durable-JSON schema versioning implemented", CONTRACT)
        self.assertIn("`--print-config` uses only this read-only path", normalized)
        self.assertIn(
            "config-less installed launch now initializes before lifecycle cleanup",
            normalized,
        )
        self.assertIn("no larger than 16 MiB", CONTRACT)
        self.assertIn("Milestone 1B-B", CONTRACT)
        self.assertIn("atomic hard-link operation that fails if the destination appeared", normalized)

    def test_all_tracked_seed_json_and_target_classes_are_defined(self):
        seed_names = sorted(path.name for path in (ROOT / "data").glob("*.json"))
        self.assertEqual(
            seed_names,
            [
                "agent_messages.json",
                "agents.json",
                "attention.json",
                "calendar.json",
                "context_packs.json",
                "dashboard.json",
                "email.json",
                "projects.json",
                "tasks.json",
            ],
        )
        for seed_name in seed_names:
            self.assertIn(f"`{seed_name}`", CONTRACT)
        for target in (
            "`<data-root>/*.json`",
            "`<data-root>/private/`",
            "`<data-root>/runtime/`",
            "`<data-root>/backups/`",
            "`<data-root>/cache/`",
            "`<data-root>/logs/`",
            "`<data-root>/config/`",
        ):
            self.assertIn(target, CONTRACT)

    def test_current_mutable_browser_config_and_external_surfaces_are_inventoried(self):
        for current_surface in (
            "`data/runtime/agent-console-runs.json`",
            "`data/runtime/mentat.sqlite3`",
            "`data/runtime/blobs/sha256/`",
            "`data/runtime/server-state.json`",
            "`data/runtime/uploads/`",
            "`data/runtime/agent-console-exports/`",
            "`data/runtime/agent-console-inputs/`",
            "`data/runtime/artifact-snapshots/`",
            "`data/runtime/workspace-snapshots/`",
            "`data/runtime/migrations/`",
            "`data/runtime/browser-smoke-profile/`",
            "`mentat.local.toml`",
            "`mentat.local.env`",
            "`mentat.local.env.bat`",
            "`agent-os.toml`",
            "`agent-os.local.toml`",
            "`AGENT_OS_DATA_DIR`",
            "`mentat-theme`",
            "`mentat-reminder:<task>:<reminder>:<at>`",
            "`mentat-agent-pulse-dismissed-v1`",
            "Hermes core files",
            "Obsidian vault",
            "Google Calendar",
            "browser notification permission",
        ):
            self.assertIn(current_surface, CONTRACT)

    def test_platform_defaults_and_override_precedence_are_exact(self):
        for default in (
            "`~/Library/Application Support/Mentat`",
            "`%LOCALAPPDATA%\\Mentat`",
            "`$XDG_DATA_HOME/Mentat`",
            "`~/.local/share/Mentat`",
        ):
            self.assertIn(default, CONTRACT)

        normalized = " ".join(CONTRACT.split())
        precedence = (
            "`--data-dir` → `MENTAT_DATA_DIR` → `AGENT_OS_DATA_DIR` → "
            "`[paths].data_dir` in TOML → platform default"
        )
        self.assertIn(precedence, normalized)
        self.assertIn("`MENTAT_DATA_DIR` outranks `AGENT_OS_DATA_DIR`", normalized)
        self.assertIn("valid and non-empty", normalized)

    def test_initialization_migration_backup_and_schema_rules_fail_closed(self):
        normalized = " ".join(CONTRACT.split())
        for requirement in (
            "copy a packaged seed only when its destination is missing",
            "never overwrite an existing operator file",
            "exact migration preview",
            "refuse source or destination conflicts",
            "validated pre-migration backup",
            "schema version",
            "refuse a newer unsupported schema version",
            "atomic replacement",
            "restore preview",
            "detect supported legacy state before copying any packaged seed",
            "leave every potentially colliding destination absent",
        ):
            self.assertIn(requirement, normalized)

    def test_private_and_secret_boundaries_are_explicit(self):
        normalized = " ".join(CONTRACT.split())
        self.assertIn("owner-only permissions", normalized)
        self.assertIn("future remote Hermes endpoint and API credential", normalized)
        self.assertIn("read-back verification of owner-only access", normalized)
        self.assertIn("before any private or secret-bearing content is written", normalized)
        self.assertIn("fails closed", normalized)
        for excluded_surface in (
            "browser payloads",
            "browser storage",
            "tracked files",
            "logs",
            "diagnostics",
            "ordinary backups",
        ):
            self.assertIn(excluded_surface, normalized)

    def test_every_target_class_has_an_explicit_backup_policy(self):
        backup_section = CONTRACT.split("## Backup and restore contract", 1)[1].split(
            "## Secret and privacy boundary", 1
        )[0]
        for target in (
            "durable operator JSON",
            "durable private Console set",
            "ephemeral runtime state",
            "backup files",
            "cache state",
            "local logs",
            "non-secret installed-app configuration",
        ):
            self.assertIn(target, backup_section)
        for consistency_rule in (
            "one consistency unit",
            "WAL-safe SQLite snapshot",
            "retained Console history",
            "referenced blobs",
            "shared lock or equivalent consistency boundary",
        ):
            self.assertIn(consistency_rule, backup_section)

    def test_primary_docs_link_the_contract_and_bound_the_implementation(self):
        normalized_roadmap = " ".join(ROADMAP.split())
        link = "[DATA_LAYOUT.md](DATA_LAYOUT.md)"
        self.assertIn(link, ARCHITECTURE)
        self.assertIn(link, README)
        self.assertIn(link, ROADMAP)
        self.assertIn("Milestone 1A contract, Milestone 1B", ROADMAP)
        self.assertIn("Milestone 1C legacy durable-JSON migration", normalized_roadmap)
        self.assertIn("Milestone 1D schema versioning", normalized_roadmap)
        self.assertIn("Milestone 1E-A durable-JSON backup/restore complete", normalized_roadmap)
        self.assertIn("Milestone 1E-B durable private Console migration/backup/restore is also complete", normalized_roadmap)
        self.assertIn("| 1 | Durable user data | In progress — 1A through 1E-B complete |", ROADMAP)

        self.assertIn("from data_layout import", RUNTIME_CONFIG)
        self.assertIn("resolve_data_root", RUNTIME_CONFIG)
        self.assertIn("initialize_data_root", RUNTIME_CONFIG)
        self.assertIn("migration_startup_status", RUNTIME_CONFIG)
        self.assertIn("preview_legacy_migration", DATA_MIGRATION)
        self.assertIn("migrate_legacy_data", DATA_MIGRATION)
        self.assertIn("preview_schema_migration", DATA_SCHEMA)
        self.assertIn("migrate_data_schema", DATA_SCHEMA)
        self.assertIn("schema_status_under_lock", RUNTIME_CONFIG)
        self.assertIn("restore_startup_status", RUNTIME_CONFIG)
        self.assertIn("_pinned_root_identity", RUNTIME_CONFIG)
        self.assertIn("data_dir_source=data_resolution.source", RUNTIME_CONFIG)
        self.assertIn('data_dir = "data"', SHARED_CONFIG)
        self.assertNotIn("platformdirs", REQUIREMENTS.lower())


if __name__ == "__main__":
    unittest.main()
