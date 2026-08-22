import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
PIVOT = (ROOT / "MENTAT_MULTI_AGENT_PIVOT.md").read_text(encoding="utf-8")
AGENT_GUIDE = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
PIVOT_PLAN = (ROOT / "MENTAT_PIVOT_IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")


class AgentRuntimeArchitectureTests(unittest.TestCase):
    def test_identity_authority_is_mentat_owned_and_runtime_refs_are_separate(self):
        self.assertIn("A Mentat **Agent** is the target canonical worker identity", ARCHITECTURE)
        self.assertIn("Runtime identities are implementation references", AGENT_GUIDE)
        self.assertIn("legacy browser `agent_id` field still", ARCHITECTURE)
        self.assertIn("without inventing profile-derived IDs", ARCHITECTURE)

    def test_pivot_keeps_hermes_behind_the_runtime_boundary(self):
        self.assertIn("Hermes is the first supported runtime", PIVOT)
        self.assertIn("Python is becoming the Mentat Local Bridge", PIVOT)
        self.assertIn("Hermes stays behind `HermesRuntime`", PIVOT)
        self.assertIn("Add Codex as a second runtime", PIVOT)

    def test_console_transport_and_routes_cross_the_runtime_registry(self):
        self.assertIn('AGENT_RUNTIME_REGISTRY.require("hermes")', SERVER)
        self.assertIn("HERMES_RUNTIME.bind_compatibility_handlers", SERVER)
        for method in (
            "start_compatibility",
            "message_compatibility",
            "response_compatibility",
            "stop_compatibility",
            "status_compatibility",
        ):
            self.assertIn(method, SERVER)

    def test_pivot_plan_closes_sqlite_cutover_and_tracks_frontend_slices(self):
        self.assertIn("| 1B | Complete |", PIVOT_PLAN)
        self.assertIn("| 1C-A to 1C-D | Complete |", PIVOT_PLAN)
        self.assertIn("| 2A-A | Complete |", PIVOT_PLAN)
        self.assertIn("| 2A-B | Complete |", PIVOT_PLAN)
        self.assertIn("| 2B-A | Proposed |", PIVOT_PLAN)
        self.assertIn("three desktop and three mobile Lighthouse runs", PIVOT_PLAN)
        self.assertIn("The legacy interface may be retired only after", PIVOT_PLAN)
        self.assertIn("reviews/2026-08-18-mentat-sqlite-task-cutover.md", PIVOT_PLAN)
        self.assertIn("Build on the existing `web/` app", PIVOT_PLAN)
        self.assertIn("MENTAT_PIVOT_IMPLEMENTATION_PLAN.md", AGENT_GUIDE)
        self.assertIn("/api/orchestration/agents", ARCHITECTURE)


if __name__ == "__main__":
    unittest.main()
