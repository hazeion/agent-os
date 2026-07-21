from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
REMOTE_CONTRACT = (ROOT / "REMOTE_HERMES.md").read_text(encoding="utf-8")


class LimitedBetaReadinessTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_tester_guide_is_short_safe_and_actionable(self):
        guide = self.read("BETA_TESTING.md")
        normalized = " ".join(guide.split())
        self.assertIn("## Your checklist", guide)
        self.assertIn("about two weeks", guide)
        self.assertIn("without maintainer help", guide)
        self.assertIn("first useful workflow", guide)
        self.assertIn("local or remote Hermes", normalized)
        self.assertIn("backup and recovery", guide)
        self.assertIn("migration or recovery", guide)
        self.assertIn("endpoints, hostnames, IP addresses", guide)
        self.assertIn("versioned remote check guide", guide)
        self.assertIn("blocker through the beta feedback form immediately", normalized)
        self.assertLess(normalized.index("blocker through the beta feedback form immediately"), normalized.index("Use Mentat normally"))
        self.assertIn("beta_feedback.yml", guide)
        self.assertIn("security/advisories/new", guide)
        self.assertIn("Never post", guide)
        self.assertLess(len(guide.split()), 900)

    def test_cohort_runbook_keeps_private_evidence_out_of_git(self):
        runbook = self.read("BETA_COHORT.md")
        normalized = " ".join(runbook.split())
        for requirement in (
            "Milestone 6",
            "at least 10 external testers",
            "roughly two weeks",
            "without maintainer intervention",
            "time to first useful workflow",
            "backup and recovery",
            "local and remote Hermes",
            "P0 and P1",
            "Milestone 6 is marked complete",
            "Intel macOS",
            "Apple Silicon with Rosetta",
            "exact verified Hermes runtime/build",
            "Do not commit",
            "aggregate",
        ):
            self.assertIn(requirement, normalized)
        for private_field in ("names", "email addresses", "credentials", "conversation content"):
            self.assertIn(private_field, normalized)
        self.assertIn("Remote evidence matrix v1", normalized)
        self.assertIn("at least 80%", normalized)
        self.assertIn("not reached", normalized)
        self.assertIn("pass-with-help", normalized)
        self.assertIn("First-workflow time-bucket counts", normalized)
        self.assertNotIn("Median and range for time", normalized)

    def test_feedback_form_collects_exit_evidence_and_requires_privacy_check(self):
        form = self.read(".github/ISSUE_TEMPLATE/beta_feedback.yml")
        for field_id in (
            "id: version",
            "id: platform",
            "id: install_channel",
            "id: experience",
            "id: hermes_mode",
            "id: hermes_runtime",
            "id: install_result",
            "id: maintainer_help",
            "id: first_workflow_time",
            "id: integrations",
            "id: recovery",
            "id: migration",
            "id: remote_matrix",
            "id: privacy",
        ):
            self.assertIn(field_id, form)
        self.assertIn("required: true", form)
        self.assertIn("private security advisory", form)
        self.assertIn("Never include credentials", form)
        self.assertIn("endpoints, hostnames, IP addresses", form)
        self.assertIn('options: ["No", "Yes"]', form)

        # GitHub dropdown options must be strings. Catch YAML 1.1 boolean-like
        # scalars even when a generic YAML parser accepts the document.
        for options in re.findall(r"^\s*options: \[(.*)\]$", form, re.MULTILINE):
            values = [value.strip() for value in options.split(",")]
            for value in values:
                if value.strip('"\'').lower() in {"yes", "no", "true", "false", "on", "off"}:
                    self.assertTrue(value.startswith(('"', "'")) and value.endswith(('"', "'")))

    def test_remote_evidence_matrix_tracks_every_required_contract_row(self):
        runbook = self.read("BETA_COHORT.md")
        form = self.read(".github/ISSUE_TEMPLATE/beta_feedback.yml")
        procedure = self.read("REMOTE_BETA_MATRIX.md")
        required = {
            line.split("|", 2)[1].strip()
            for line in REMOTE_CONTRACT.splitlines()
            if line.startswith("|") and "**Required**" in line
        }
        matrix = runbook.split("### Remote evidence matrix v1", 1)[1].split(
            "Aggregate by matrix version", 1
        )[0]
        recorded = {
            line.split("|", 2)[1].strip()
            for line in matrix.splitlines()
            if line.startswith("|") and line not in {"| Required capability |", "| --- |"}
        }
        self.assertEqual(recorded, required)
        for capability in required:
            self.assertIn(f"{capability}: not-run", form)
            section = procedure.split(f"## {capability}", 1)[1].split("\n## ", 1)[0]
            self.assertIn("- Performer:", section)
            action_numbers = re.findall(r"^- Action (\d+):", section, re.MULTILINE)
            pass_numbers = re.findall(r"^- Pass (\d+):", section, re.MULTILINE)
            self.assertTrue(action_numbers)
            self.assertEqual(action_numbers, pass_numbers)
        self.assertEqual(
            {
                line[3:]
                for line in procedure.splitlines()
                if line.startswith("## ") and line != "## Automated-only boundary evidence"
            },
            required,
        )
        for evidence in (
            "tests/test_remote_hermes.py",
            "tests/test_remote_capability_inventory.py",
            "tests/test_remote_console_runs.py",
            "tests/test_remote_sessions.py",
            "tests/test_hermes_kanban.py",
            "tests/test_task_delegation.py",
        ):
            self.assertIn(evidence, procedure)

    def test_install_gate_separates_workflow_and_requires_channel_floors(self):
        runbook = self.read("BETA_COHORT.md")
        roadmap = self.read("ROAD_TO_BETA.md")
        for text in (runbook, roadmap):
            normalized = " ".join(text.split())
            self.assertIn("at least 80%", normalized)
            self.assertIn("Intel Mac native", normalized)
            self.assertIn("Apple Silicon with Rosetta native", normalized)
            self.assertIn("Windows native", normalized)
            self.assertIn("supported `pipx`", normalized)
            self.assertIn("first-workflow", normalized)
        self.assertIn("does not rewrite a completed install", runbook)

    def test_support_links_the_limited_beta_guide_without_claiming_it_started(self):
        support = self.read("SUPPORT.md")
        roadmap = self.read("ROAD_TO_BETA.md")
        self.assertIn("BETA_TESTING.md", support)
        milestone = roadmap.split("## Milestone 7", 1)[1].split("## Milestone 8", 1)[0]
        self.assertIn("Repository preparation status:", milestone)
        self.assertIn("cohort has not started", milestone)
        self.assertIn("at least 80%", milestone)
        self.assertIn("denominator", milestone)

    def test_known_issues_surface_has_owner_cadence_and_privacy_rules(self):
        known = self.read("KNOWN_ISSUES.md")
        normalized = " ".join(known.split())
        support = self.read("SUPPORT.md")
        for requirement in (
            "maintainer owns it",
            "at least twice a week",
            "affected version",
            "status",
            "safe workaround",
            "fixed version",
            "Resolved",
            "private security advisories",
            "endpoints, hostnames, IP addresses",
        ):
            self.assertIn(requirement, normalized)
        self.assertIn("KNOWN_ISSUES.md", support)


if __name__ == "__main__":
    unittest.main()
