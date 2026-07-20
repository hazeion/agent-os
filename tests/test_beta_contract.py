from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LICENSE = (ROOT / "LICENSE").read_text(encoding="utf-8")
ROADMAP = (ROOT / "ROAD_TO_BETA.md").read_text(encoding="utf-8")
ARCHITECTURE = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
REMOTE_HERMES = (ROOT / "REMOTE_HERMES.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def normalized_section(text: str, start: str, end: str) -> str:
    return " ".join(section(text, start, end).split())


class BetaContractTests(unittest.TestCase):
    def test_standard_mit_license_uses_approved_holder(self):
        self.assertTrue(LICENSE.startswith("MIT License\n"))
        self.assertIn("Copyright (c) 2026 Brandon Thomas", LICENSE)
        self.assertIn("Permission is hereby granted, free of charge", LICENSE)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', LICENSE)

    def test_milestone_zero_records_the_complete_approved_contract(self):
        decisions = section(ROADMAP, "## Beta contract decisions", "## Current baseline")
        milestone = section(ROADMAP, "## Milestone 0", "## Milestone 1")

        self.assertIn("Milestone 0 is complete", ROADMAP)
        self.assertIn("Beta release contract approved: 2026-07-17", ROADMAP)
        self.assertIn("| Audience | Hermes operators comfortable installing local software | Approved 2026-07-17 |", decisions)
        self.assertIn("| Tier-one platforms | macOS and Windows | Approved 2026-07-17 |", decisions)
        self.assertIn("| Preview platform | Linux, covered by CI but not initially promised at the same support level | Approved 2026-07-17 |", decisions)
        self.assertIn("| Python | 3.11 through 3.13 | Approved 2026-07-17 |", decisions)
        self.assertIn("| Update model | Manual, versioned upgrades with a pre-upgrade backup | Approved 2026-07-17 |", decisions)
        self.assertIn("| Telemetry | Off and absent by default | Approved 2026-07-17 |", decisions)
        self.assertIn("| First version | `0.1.0b1`, displayed to users as `v0.1.0-beta.1` | Approved 2026-07-17 |", decisions)
        self.assertIn("| License | MIT | Approved 2026-07-16 |", decisions)
        self.assertIn("Native installers are primary on tier-one platforms", decisions)
        self.assertIn("`pipx` from a tagged release remains supported", decisions)
        self.assertNotIn("approval pending", decisions.lower())
        self.assertNotIn("pending", milestone.lower())

    def test_native_installers_and_pipx_are_consistent_beta_channels(self):
        milestone_three = normalized_section(ROADMAP, "## Milestone 3", "## Milestone 4")
        milestone_four = normalized_section(ROADMAP, "## Milestone 4", "## Milestone 5")
        milestone_six = normalized_section(ROADMAP, "## Milestone 6", "## Milestone 7")
        milestone_eight = normalized_section(ROADMAP, "## Milestone 8", "## Public beta definition of done")
        definition_of_done = normalized_section(ROADMAP, "## Public beta definition of done", "## Work intentionally deferred")

        for requirement in (
            "signed and notarized native installer for macOS",
            "signed native installer for Windows",
            "`pipx`",
        ):
            self.assertIn(requirement, ROADMAP)
        self.assertIn("Exact installer formats and tooling", ROADMAP)
        for milestone in (
            milestone_three,
            milestone_four,
            milestone_six,
            milestone_eight,
            definition_of_done,
        ):
            self.assertIn("signed and notarized native installer for macOS", milestone)
            self.assertIn("signed native installer for Windows", milestone)
            self.assertIn("`pipx`", milestone)
        self.assertIn("native installers", section(ROADMAP, "## Milestone map", "## Milestone 0").lower())
        normalized_roadmap = " ".join(ROADMAP.lower().split())
        self.assertNotIn("| native installers | deferred", normalized_roadmap)
        self.assertNotIn("native installers are deferred", normalized_roadmap)
        self.assertNotIn("native signed installers and automatic updates", normalized_roadmap)

    def test_severity_feedback_and_next_slice_order_are_approved(self):
        milestone = section(ROADMAP, "## Milestone 0", "## Milestone 1")
        deferred_work = normalized_section(
            ROADMAP,
            "## Work intentionally deferred",
            "## Current next actions",
        )
        next_actions = ROADMAP.split("## Current next actions", 1)[1]

        for policy in (
            "P0: data loss, secret exposure, unsafe mutation, or app-wide unusability",
            "P1: a core workflow is unusable with no reasonable workaround",
            "P2: degraded behavior with a workaround",
            "P3: polish, documentation, or minor inconvenience",
            "P0 and P1 issues block a release",
            "P2 and P3 issues are prioritized by frequency and operator impact",
            "ordinary reports use GitHub Issues after the public issue path opens",
            "security reports use the private channel established in Milestone 5",
            "beta support is best effort with no guaranteed response-time SLA",
            "reports must exclude credentials and private operator content",
            "explicit beta non-goals are maintained in the deferred-work section",
        ):
            self.assertIn(policy, milestone)
        for non_goal in (
            "non-loopback or hosted Mentat access",
            "authentication, multi-user accounts, or multi-tenancy",
            "automatic updates",
            "telemetry or analytics by default",
            "large new product surfaces that do not close a beta acceptance gap",
        ):
            self.assertIn(non_goal, deferred_work)
        self.assertIn("Approved 2026-07-17", milestone)
        self.assertTrue(next_actions.lstrip().startswith("1. Continue Milestone 2"))
        self.assertIn("remote session list, replay, and continuation", next_actions)
        self.assertIn("Keep approval response unavailable", next_actions)
        self.assertIn("exact authenticated capabilities", next_actions)
        self.assertIn("bounded Context Pack text", next_actions)
        self.assertNotIn("early CI guardrail", next_actions)
        self.assertNotIn("Finish the remaining Milestone 0", next_actions)

    def test_docs_do_not_claim_native_installers_already_exist(self):
        normalized_readme = " ".join(README.replace(">", "").split())
        self.assertIn("native installers are still on the way", normalized_readme)
        self.assertIn("## Quick start", README)
        self.assertIn("[Python 3.11–3.13]", README)
        for first_run_step in (
            "git clone https://github.com/hazeion/agent-os.git",
            "python -m pip install -r requirements.txt",
            "python scripts/mentat_setup.py",
            "./run.sh",
        ):
            self.assertIn(first_run_step, README)

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
        self.assertIn("`remote_hermes.py`", REMOTE_HERMES)

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
        self.assertIn("(REMOTE_HERMES.md)", README)

    def test_roadmap_uses_verified_ready_pull_requests(self):
        self.assertIn("ready pull request", ROADMAP)
        self.assertNotIn("draft pull request", ROADMAP)
        self.assertLess(
            ROADMAP.index("Secure remote Hermes parity"),
            ROADMAP.index("Run a limited external beta"),
        )


if __name__ == "__main__":
    unittest.main()
