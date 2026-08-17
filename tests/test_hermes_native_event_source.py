from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.validate_hermes_native_events import (
    EXPECTED_COMMIT,
    EXPECTED_SOURCE_SHA256,
    EXPECTED_TAG,
    REQUIRED_SOURCE_MARKERS,
    validate_source,
)


class HermesNativeEventSourceTests(unittest.TestCase):
    def test_validator_covers_exact_stock_release_and_process_topology(self):
        self.assertEqual(EXPECTED_TAG, "v2026.8.13")
        self.assertEqual(EXPECTED_COMMIT, "f80f453ae0679347e38abc917c7f94f717bf96c5")
        self.assertIn("cli.py", REQUIRED_SOURCE_MARKERS)
        self.assertIn("hermes_cli/main.py", REQUIRED_SOURCE_MARKERS)
        self.assertIn("gateway/run.py", REQUIRED_SOURCE_MARKERS)
        self.assertIn("agent/turn_finalizer.py", REQUIRED_SOURCE_MARKERS)
        self.assertIn("tools/delegate_tool.py", REQUIRED_SOURCE_MARKERS)
        self.assertIn('"on_session_end"', REQUIRED_SOURCE_MARKERS["agent/turn_finalizer.py"])
        self.assertIn('"subagent_start"', REQUIRED_SOURCE_MARKERS["tools/delegate_tool.py"])
        self.assertIn('"subagent_stop"', REQUIRED_SOURCE_MARKERS["tools/delegate_tool.py"])
        worker = REQUIRED_SOURCE_MARKERS["hermes_cli/kanban_db.py"]
        self.assertIn('"--accept-hooks"', worker)
        self.assertIn("subprocess.Popen", worker)
        for event in (
            '"kanban_task_claimed"', '"kanban_task_completed"',
            '"kanban_task_blocked"', '"on_kanban_task_updated"',
        ):
            self.assertIn(event, worker)
        self.assertEqual(set(EXPECTED_SOURCE_SHA256), set(REQUIRED_SOURCE_MARKERS))

    def test_validator_passes_complete_fixture_and_fails_missing_marker(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative_path, markers in REQUIRED_SOURCE_MARKERS.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(markers), encoding="utf-8")
            passed = validate_source(root, require_exact=False)
            self.assertTrue(passed["ok"])
            self.assertEqual(passed["files_checked"], len(REQUIRED_SOURCE_MARKERS))
            self.assertEqual(set(passed["source_sha256"]), set(REQUIRED_SOURCE_MARKERS))

            (root / "model_tools.py").write_text("no observer", encoding="utf-8")
            failed = validate_source(root, require_exact=False)
            self.assertFalse(failed["ok"])
            self.assertEqual(failed["failures"][0]["file"], "model_tools.py")

    def test_marker_only_fixture_cannot_claim_exact_release_identity(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative_path, markers in REQUIRED_SOURCE_MARKERS.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(markers), encoding="utf-8")
            result = validate_source(root)
        self.assertFalse(result["ok"])
        errors = {failure.get("error") for failure in result["failures"]}
        self.assertIn("unexpected_sha256", errors)
        self.assertIn("unexpected_commit", errors)
        self.assertIn("source_identity_unverified", errors)


if __name__ == "__main__":
    unittest.main()
