from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.validate_hermes_stock_compatibility import (
    EXPECTED_COMMIT,
    EXPECTED_SOURCE_SHA256,
    EXPECTED_TAG,
    FORBIDDEN_SOURCE_MARKERS,
    REQUIRED_SOURCE_MARKERS,
    validate_source,
)


class HermesStockCompatibilitySourceTests(unittest.TestCase):
    def test_validator_pins_usage_schema_and_capability_absence(self):
        self.assertEqual(EXPECTED_TAG, "v2026.8.13")
        self.assertEqual(EXPECTED_COMMIT, "f80f453ae0679347e38abc917c7f94f717bf96c5")
        self.assertEqual(set(EXPECTED_SOURCE_SHA256), set(REQUIRED_SOURCE_MARKERS))
        self.assertIn('"--usage-file"', REQUIRED_SOURCE_MARKERS["hermes_cli/_parser.py"])
        self.assertIn('"total_tokens"', REQUIRED_SOURCE_MARKERS["hermes_cli/oneshot.py"])
        self.assertIn('"run_event_replay"', FORBIDDEN_SOURCE_MARKERS["gateway/platforms/api_server.py"])

    def test_marker_fixture_proves_contract_and_rejects_false_stock_feature(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative_path, markers in REQUIRED_SOURCE_MARKERS.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(markers), encoding="utf-8")
            self.assertTrue(validate_source(root, require_exact=False)["ok"])

            api = root / "gateway/platforms/api_server.py"
            api.write_text(api.read_text(encoding="utf-8") + '\n"run_event_replay"', encoding="utf-8")
            failed = validate_source(root, require_exact=False)
            self.assertFalse(failed["ok"])
            self.assertIn('"run_event_replay"', failed["failures"][0]["unexpected"])


if __name__ == "__main__":
    unittest.main()
