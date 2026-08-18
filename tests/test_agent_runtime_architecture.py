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

    def test_first_slice_remains_additive_and_hermes_only(self):
        status = PIVOT.split("### Implementation status", 1)[1]
        self.assertIn("runtime-neutral domain/protocol contracts", status)
        self.assertIn("Durable Mentat Agent", status)
        self.assertIn("remain separate follow-up slices", status)

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

    def test_pivot_plan_marks_only_the_approved_registry_slice_active(self):
        self.assertIn("| 1B | In progress |", PIVOT_PLAN)
        self.assertIn("| 1C | Provisional |", PIVOT_PLAN)
        self.assertIn("Next.js + React + TypeScript", PIVOT_PLAN)
        self.assertIn("MENTAT_PIVOT_IMPLEMENTATION_PLAN.md", AGENT_GUIDE)
        self.assertIn("/api/orchestration/agents", ARCHITECTURE)


if __name__ == "__main__":
    unittest.main()
