import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
ARCHITECTURE_FLAT = " ".join(ARCHITECTURE.split())
AGENT_GUIDE = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
IMPLEMENTATION_PLAN = (ROOT / "IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")


class AgentRuntimeArchitectureTests(unittest.TestCase):
    def test_identity_authority_is_mentat_owned_and_runtime_refs_are_separate(self):
        self.assertIn("A Mentat **Agent** is the target canonical worker identity", ARCHITECTURE)
        self.assertIn("Runtime identities are implementation references", AGENT_GUIDE)
        self.assertIn("legacy browser `agent_id` field still", ARCHITECTURE)
        self.assertIn("without inventing profile-derived IDs", ARCHITECTURE)

    def test_runtime_adapters_remain_behind_mentat_authority(self):
        self.assertIn(
            "Mentat is a local operations console for planning work and running agents",
            ARCHITECTURE_FLAT,
        )
        self.assertIn("`hermes_runtime.py` registers Hermes as the first runtime", ARCHITECTURE_FLAT)
        self.assertIn("Python Local Bridge", ARCHITECTURE)
        self.assertIn("registers the second runtime", ARCHITECTURE_FLAT)

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

    def test_codex_uses_the_same_private_runtime_boundary(self):
        self.assertIn("codex_runtime.py", AGENT_GUIDE)
        self.assertIn("Codex App Server's", ARCHITECTURE)
        self.assertIn("fixed `default` binding", ARCHITECTURE)
        self.assertIn("AGENT_RUNTIME_REGISTRY = AgentRuntimeRegistry", SERVER)
        self.assertIn("shutdown_agent_runtimes", SERVER)

    def test_implementation_plan_is_current_resume_map_with_safety_boundaries(self):
        for heading in (
            "## Destination",
            "## Current position",
            "## Next steps and dependencies",
            "## Operator inputs and independent work",
            "## Working rules",
        ):
            self.assertIn(heading, IMPLEMENTATION_PLAN)
        self.assertIn("https://github.com/hazeion/agent-os/issues/234", IMPLEMENTATION_PLAN)
        plan = " ".join(IMPLEMENTATION_PLAN.split())
        for boundary in (
            "one owner on an always-on Linux Mentat host, signing in from ordinary desktop/mobile browsers",
            "Python owns Tasks, Runs, context, files, credentials and runtime authority",
            "Browser access grants no provider consent",
            "Saving a plan or choosing a lead never starts work",
            "Unknown external outcomes never retry automatically",
            "A parser, owner edit, successful Run or Inbox acknowledgment cannot substitute for those proofs",
            "Detailed contracts, test counts and historical fixes belong in those records",
            "the explicit legacy UI rollback and truthful unknown outcomes",
            "Runtime identities remain private beneath Agents",
            "elapsed time never approves credential changes or execution",
        ):
            self.assertIn(boundary, plan)
        self.assertIn("IMPLEMENTATION_PLAN.md", AGENT_GUIDE)
        self.assertIn("/api/orchestration/agents", ARCHITECTURE)


if __name__ == "__main__":
    unittest.main()
