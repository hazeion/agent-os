from pathlib import Path
import unittest

from hermes_webhooks import ALLOWED_EVENTS


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
ARCHITECTURE_FLAT = " ".join(ARCHITECTURE.split())


class Hermes020BoundaryTests(unittest.TestCase):
    def test_receiver_preserves_the_original_qualified_lifecycle_events(self):
        self.assertTrue(
            {
                "on_session_start",
                "on_session_end",
                "subagent_start",
                "subagent_stop",
            }
            <= ALLOWED_EVENTS
        )

    def test_optional_hermes_features_do_not_inherit_webhook_authority(self):
        for phrase in (
            "A2A, grounded-citation, deliverable-artifact, and voice features",
            "do not inherit webhook authority",
            "A2A is a separate bidirectional execution boundary",
            "Citations remain untrusted response Markdown",
            "stock 0.20.1 degrades to summary-only",
            "Voice remains unavailable",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, ARCHITECTURE_FLAT)

    def test_model_prose_cannot_grant_file_or_provenance_authority(self):
        for phrase in (
            "does not parse assistant prose for local paths",
            "`MEDIA:` directives",
            "citation authority",
            "audio, or transcripts",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, ARCHITECTURE_FLAT)


if __name__ == "__main__":
    unittest.main()
