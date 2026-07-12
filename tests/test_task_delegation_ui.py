from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")


class TaskDelegationUiTests(unittest.TestCase):
    def test_selected_task_offers_confirmed_delegation(self):
        self.assertIn('id="selected-task-delegate"', INDEX)
        self.assertIn('id="task-delegation-dialog"', INDEX)
        self.assertIn('id="task-delegation-review"', INDEX)
        self.assertIn('data-task-delegation-preview', INDEX)
        self.assertIn('data-task-delegation-confirm', INDEX)
        self.assertIn("async function reviewTaskDelegation()", APP)
        self.assertIn("async function submitTaskDelegation()", APP)
        self.assertIn("previewTaskDelegation", CORE)
        self.assertIn("confirmation_id", CORE)

    def test_task_inspector_exposes_linked_run_and_review_actions(self):
        self.assertIn("task-delegation-card", APP)
        self.assertIn('data-delegation-action="accept"', APP)
        self.assertIn('data-delegation-action="request_revision"', APP)
        self.assertIn('data-delegation-action="reply"', APP)
        self.assertIn('data-delegation-action="retry"', APP)
        self.assertIn('data-delegation-action="stop"', APP)
        self.assertIn("refreshTaskDelegation", CORE)
        self.assertIn("runTaskDelegationAction", CORE)

    def test_today_has_agent_activity_and_review_inbox(self):
        self.assertIn('id="agent-activity-panel"', INDEX)
        self.assertIn('id="agent-activity-list"', INDEX)
        self.assertIn("function renderAgentActivity", APP)
        self.assertIn("needs_input", APP)
        self.assertIn("ready_for_review", APP)
        self.assertIn("endpoints.agentActivity", APP)
        self.assertIn(".agent-activity-list", CSS)


if __name__ == "__main__":
    unittest.main()
