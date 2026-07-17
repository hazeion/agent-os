from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LICENSE = (ROOT / "LICENSE").read_text(encoding="utf-8")
ROADMAP = (ROOT / "ROAD_TO_BETA.md").read_text(encoding="utf-8")
ARCHITECTURE = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
REMOTE_HERMES = (ROOT / "REMOTE_HERMES.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


class BetaContractTests(unittest.TestCase):
    def test_standard_mit_license_uses_approved_holder(self):
        self.assertTrue(LICENSE.startswith("MIT License\n"))
        self.assertIn("Copyright (c) 2026 Brandon Thomas", LICENSE)
        self.assertIn("Permission is hereby granted, free of charge", LICENSE)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', LICENSE)

    def test_milestone_zero_records_only_the_approved_decisions(self):
        self.assertIn("Status: Milestone 0 in progress", ROADMAP)
        self.assertIn("Remote architecture and license decisions approved: 2026-07-16", ROADMAP)
        self.assertIn("| License | MIT | Approved 2026-07-16 |", ROADMAP)
        self.assertIn("| Tier-one platforms | macOS and Windows | Recommended; approval pending |", ROADMAP)
        self.assertIn("| Python | 3.11 through 3.13 | Recommended; approval pending |", ROADMAP)
        self.assertIn("one active local or remote Hermes endpoint", ROADMAP)

    def test_remote_contract_records_required_parity_and_safe_degradation(self):
        for required in (
            "Agent Console conversation and streaming",
            "cancellation, and stopping",
            "Clarification requests and responses",
            "Session list, replay, continuation, and search",
            "Read-only agent/profile discovery",
            "Skill and toolset visibility",
            "Durable Kanban delegation and follow-up",
        ):
            self.assertIn(required, REMOTE_HERMES)
        self.assertIn("**Required**; upstream authenticated capability blocker", REMOTE_HERMES)
        self.assertIn("Clarification handling", REMOTE_HERMES)
        self.assertIn("**Graceful degradation**", REMOTE_HERMES)

    def test_remote_contract_inventories_all_current_hermes_adapters(self):
        adapters = {path.name for path in ROOT.glob("hermes_*.py")}
        adapters.update({
            "server.py",
            "agent_run_history.py",
            "runtime_config.py",
            "health_checks.py",
            "scripts/mentat_setup.py",
        })
        for adapter in adapters:
            self.assertIn(f"`{adapter}`", REMOTE_HERMES)

    def test_remote_security_boundary_is_fail_closed(self):
        normalized_contract = " ".join(REMOTE_HERMES.split())
        for requirement in (
            "one active Hermes connection at a time",
            "must use `https`",
            "Certificate verification is mandatory",
            "The browser never calls Hermes directly",
            "fail closed",
            "Mentat must not invoke SSH",
            "must never be returned to the browser",
        ):
            self.assertIn(requirement, normalized_contract)
        self.assertIn("unauthenticated loopback plugin HTTP route", normalized_contract)
        self.assertNotIn("behind dashboard session auth", normalized_contract)
        normalized_architecture = " ".join(ARCHITECTURE.split())
        self.assertIn("never collects Hermes-owned provider/model credentials", normalized_architecture)
        self.assertIn("operator-supplied API key", normalized_architecture)

    def test_primary_docs_link_the_remote_contract(self):
        link = "[REMOTE_HERMES.md](REMOTE_HERMES.md)"
        self.assertIn(link, ROADMAP)
        self.assertIn(link, ARCHITECTURE)
        self.assertIn(link, README)

    def test_roadmap_uses_verified_ready_pull_requests(self):
        self.assertIn("ready pull request", ROADMAP)
        self.assertNotIn("draft pull request", ROADMAP)
        self.assertLess(
            ROADMAP.index("Secure remote Hermes parity"),
            ROADMAP.index("Run a limited external beta"),
        )


if __name__ == "__main__":
    unittest.main()
