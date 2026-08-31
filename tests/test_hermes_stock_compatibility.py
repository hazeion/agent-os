from pathlib import Path
import inspect
import re
import unittest

from hermes_stock_compatibility import (
    ALL_CONTRACT_IDS,
    CONTRACT_CLASS_AND_DISPOSITION,
    REMOTE_FEATURE_CONTRACTS,
)
from hermes_event_refresh import HermesRefreshCoordinator
from remote_hermes import _KNOWN_BOOLEAN_FEATURES


ROOT = Path(__file__).resolve().parents[1]
AUDIT = (ROOT / "HERMES_STOCK_COMPATIBILITY.md").read_text(encoding="utf-8")
ARCHITECTURE = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
CORE = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
TRANSPORT = (ROOT / "hermes_transport.py").read_text(encoding="utf-8")


class HermesStockCompatibilityTests(unittest.TestCase):
    def test_audit_is_bound_to_the_qualified_stock_release(self):
        self.assertIn("v2026.8.13", AUDIT)
        self.assertIn("f80f453ae0679347e38abc917c7f94f717bf96c5", AUDIT)
        self.assertIn("scripts/validate_hermes_native_events.py", AUDIT)

    def test_inventory_has_every_distinct_contract_once(self):
        found = re.findall(r"^\| `([a-z_]+)` \|", AUDIT, re.MULTILINE)
        self.assertEqual(set(found), ALL_CONTRACT_IDS)
        self.assertEqual(len(found), len(ALL_CONTRACT_IDS))

    def test_every_production_remote_feature_is_classified_exactly_once(self):
        classified = [
            feature
            for features in REMOTE_FEATURE_CONTRACTS.values()
            for feature in features
        ]
        self.assertEqual(set(classified), _KNOWN_BOOLEAN_FEATURES)
        self.assertEqual(len(classified), len(set(classified)))

    def test_every_table_class_and_disposition_matches_the_canonical_inventory(self):
        rows = {}
        for line in AUDIT.splitlines():
            match = re.match(r"^\| `([a-z_]+)` \|", line)
            if match:
                rows[match.group(1)] = [part.strip() for part in line.split("|")[1:-1]]
        self.assertEqual(set(rows), set(CONTRACT_CLASS_AND_DISPOSITION))
        for contract, (expected_class, disposition) in CONTRACT_CLASS_AND_DISPOSITION.items():
            with self.subTest(contract=contract):
                self.assertEqual(rows[contract][3], expected_class)
                self.assertTrue(rows[contract][5].startswith(f"**{disposition}.**"))

    def test_no_fallback_is_retired_without_soak_evidence(self):
        self.assertIn("retires no correctness fallback", AUDIT)
        self.assertIn("At least 24 continuous hours", AUDIT)
        self.assertIn("REFRESH_MS = 30_000", AUDIT)
        self.assertIn("const REFRESH_MS = 30_000", CORE)
        self.assertIn("setInterval(refresh, REFRESH_MS)", APP)
        self.assertIn("reconciliation_interval=60.0", SERVER)
        default_interval = inspect.signature(HermesRefreshCoordinator).parameters[
            "reconciliation_interval"
        ].default
        self.assertEqual(default_interval, 60.0)

    def test_webhooks_are_wakeups_not_telemetry_or_authority(self):
        flattened = " ".join(AUDIT.split())
        for phrase in (
            "do not prove state", "grant mutation authority",
            "Wakeup only, not data", "Not a webhook authority",
            "Never infer mutation success from an event",
            "A wakeup event alone cannot satisfy this gate",
        ):
            self.assertIn(phrase, flattened)

    def test_local_telemetry_distinguishes_live_custom_from_stock_final_usage(self):
        self.assertIn("MENTAT_HERMES_USAGE_FILE", TRANSPORT)
        self.assertIn("MENTAT_HERMES_PROGRESS_FILE", TRANSPORT)
        self.assertIn("`local_console_live_progress`", AUDIT)
        self.assertIn("`local_console_final_usage`", AUDIT)
        self.assertIn("hermes -z --usage-file", AUDIT)
        self.assertIn("Mentat launches `chat -q`", AUDIT)
        self.assertIn("Unavailable context usage", AUDIT)

    def test_custom_contracts_have_explicit_stock_degradation(self):
        for contract in (
            "remote_approval_and_clarification", "remote_session_continuation",
            "remote_inline_images", "remote_profile_inventory",
            "remote_kanban_mutation",
            "remote_artifact_download", "remote_cron_inventory",
        ):
            row = next(line for line in AUDIT.splitlines() if f"`{contract}`" in line)
            self.assertIn("Custom required", row)
            self.assertRegex(row, r"Retain|Keep|Unsupported|degrades")

    def test_architecture_retains_the_stock_compatibility_contract(self):
        flattened = " ".join(ARCHITECTURE.split())
        self.assertIn("retires none of these fallbacks", flattened)
        self.assertIn("HERMES_STOCK_COMPATIBILITY.md", ARCHITECTURE)


if __name__ == "__main__":
    unittest.main()
