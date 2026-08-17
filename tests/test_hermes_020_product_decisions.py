from pathlib import Path
import unittest

from hermes_webhooks import ALLOWED_EVENTS


ROOT = Path(__file__).resolve().parents[1]
DECISIONS = (ROOT / "HERMES_020_PRODUCT_DECISIONS.md").read_text(encoding="utf-8")
PLAN = (ROOT / "MILESTONE_9_WEBHOOK_IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
ARCHITECTURE = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
DECISIONS_FLAT = " ".join(DECISIONS.split())
PLAN_FLAT = " ".join(PLAN.split())


class Hermes020ProductDecisionTests(unittest.TestCase):
    def test_decisions_are_bound_to_the_qualified_stock_release(self):
        self.assertIn("v2026.8.13", DECISIONS)
        self.assertIn("f80f453ae0679347e38abc917c7f94f717bf96c5", DECISIONS)
        for source in (
            "plugins/platforms/a2a/",
            "skills/research/grounded-citations/SKILL.md",
            "website/docs/user-guide/features/deliverable-mode.md",
            "website/docs/user-guide/features/voice-mode.md",
        ):
            with self.subTest(source=source):
                self.assertIn(source, DECISIONS)

    def test_every_remaining_surface_has_an_explicit_non_webhook_decision(self):
        rows = {
            "A2A v1.0": "Native Hermes only; defer a Mentat control surface.",
            "Grounded citations": "Compatible as response Markdown; defer structured citation UI.",
            "Desktop and deliverable artifacts": "Keep Mentat's existing owned artifact boundary; reject response-path discovery.",
            "Voice": "Defer a Mentat voice surface.",
        }
        for surface, decision in rows.items():
            with self.subTest(surface=surface):
                self.assertIn(f"| {surface} | **{decision}**", DECISIONS)
        self.assertIn("not a mentat webhook event", DECISIONS.lower())
        self.assertIn("not an event", DECISIONS.lower())
        self.assertIn("not lifecycle wakeups", DECISIONS.lower())

    def test_a2a_does_not_gain_mentat_execution_or_config_authority(self):
        for phrase in (
            "does not add an A2A server, client, peer editor, task proxy",
            "does not read or write its configuration, credentials",
            "supported capability-advertised API rather than direct config/file access",
            "configured, authenticated peer aliases only",
            "no browser-supplied URL",
            "executable negative-path tests that independently reject redirects",
            "DNS rebinding, private, loopback, link-local, metadata-service",
            "only configured peer aliases can select a destination",
            "mandatory callback signing secret",
            "reject missing or invalid signatures",
            "verified HMAC binds the exact task, context, and peer before authoritative read-back",
            "exact task preview, confirmation, cancellation semantics, read-back",
        ):
            self.assertIn(phrase, DECISIONS_FLAT)

    def test_citations_remain_untrusted_markdown_without_structured_provenance(self):
        self.assertIn("ordinary assistant Markdown", DECISIONS_FLAT)
        self.assertIn("must not parse assistant prose into trusted provenance records", DECISIONS_FLAT)
        self.assertIn("`degraded: false` alone is insufficient", DECISIONS_FLAT)
        self.assertIn("provider-independent citation API", DECISIONS_FLAT)
        self.assertIn("stable source IDs", DECISIONS_FLAT)
        self.assertIn("model-provided versus independently verified evidence", DECISIONS_FLAT)

    def test_artifacts_keep_the_run_owned_and_authenticated_boundaries(self):
        for phrase in (
            "run-owned export directory",
            "authenticated, digest-aware custom-host capability",
            "summary-only for remote Kanban artifacts",
            "does not scan response text for absolute paths",
            "`MEDIA:` tokens",
            "does not open a path merely because Hermes or model prose mentions it",
        ):
            self.assertIn(phrase, DECISIONS_FLAT)

    def test_voice_requires_browser_privacy_and_verified_transport_semantics(self):
        for phrase in (
            "explicit browser microphone permission",
            "strict byte/duration limits",
            "no retained recording by default",
            "explicit opt-in before cloud processing",
            "transcript preview/correction",
            "post-verified steer/interrupt semantics",
            "Stop remaining distinct",
        ):
            self.assertIn(phrase, DECISIONS_FLAT)

    def test_receiver_preserves_the_four_original_qualified_lifecycle_events(self):
        self.assertTrue(
            {
                "on_session_start", "on_session_end",
                "subagent_start", "subagent_stop",
            } <= ALLOWED_EVENTS
        )

    def test_detailed_plan_preserves_native_migration_and_retirement_slices(self):
        start_9h = PLAN.index("### 9H — Native event migration")
        start_9i = PLAN.index("### 9I — Fallback retirement and fork audit")
        end_9i = PLAN.index("### Recommended implementation total")
        section_9h = " ".join(PLAN[start_9h:start_9i].split())
        section_9i = " ".join(PLAN[start_9i:end_9i].split())

        self.assertIn("Status: **Implemented and reviewed.**", section_9h)
        self.assertIn("lifecycle, API-usage, tool, model/provider, subagent, and Kanban", section_9h)
        self.assertIn("Mentat-to-browser push channel before reducing browser polling", section_9h)
        self.assertIn("authoritative read-backs", section_9h)
        self.assertIn("Prompts, tool arguments/results, paths, response text", section_9h)
        self.assertIn("event-to-transition matrix", section_9h)
        self.assertIn("dispatcher/worker process-registration proof", section_9h)
        self.assertIn("Periodic reconciliation must converge", section_9h)

        self.assertIn("Status: **Implemented and reviewed.**", section_9i)
        self.assertIn("qualified native event path has actually superseded", section_9i)
        self.assertIn("Audit every remaining custom-fork contract separately", section_9i)
        self.assertIn("not approvals, continuation, provider mutation, artifact download, Kanban mutation", section_9i)
        self.assertIn("upstream equivalent, a supported fallback, or an explicitly approved product removal", section_9i)
        self.assertIn("Compatibility, rollback, dropped-event convergence, and soak evidence", section_9i)

    def test_architecture_links_the_decision_authority(self):
        self.assertIn("[HERMES_020_PRODUCT_DECISIONS.md]", ARCHITECTURE)
        self.assertIn("do not inherit webhook authority", ARCHITECTURE)
        self.assertIn("does not\nparse assistant prose for local paths", ARCHITECTURE)


if __name__ == "__main__":
    unittest.main()
