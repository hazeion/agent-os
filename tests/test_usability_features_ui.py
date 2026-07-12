from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE = (ROOT / "public" / "core.js").read_text(encoding="utf-8")


class UsabilityFeaturesUiTests(unittest.TestCase):
    def test_notes_can_be_searched_opened_and_attached(self):
        self.assertIn('id="notes-search"', INDEX)
        self.assertIn('id="notes-count"', INDEX)
        self.assertIn('Open in Obsidian', APP)
        self.assertIn('data-attach-note', APP)
        self.assertIn('data-detach-note', APP)
        self.assertIn('attachNoteToTask', CORE)
        self.assertIn('detachNoteFromTask', CORE)

    def test_agent_post_creation_has_test_assign_and_advanced_controls(self):
        self.assertIn('data-agent-creator-test', APP)
        self.assertIn('data-agent-creator-assign-first-task', APP)
        self.assertIn('data-test-hermes-profile', APP)
        self.assertIn('data-assign-first-task', APP)
        self.assertIn('managed-agent-advanced', APP)
        self.assertIn('agent-onboarding-checklist', APP)
        self.assertIn('Identity check:', APP)

    def test_notifications_are_only_requested_by_explicit_button(self):
        self.assertIn('id="enable-reminders-button"', INDEX)
        listener = APP[APP.index("$('#enable-reminders-button')"):]
        self.assertIn('Notification.requestPermission()', listener)
        prefix = APP[:APP.index("$('#enable-reminders-button')")]
        self.assertNotIn('Notification.requestPermission()', prefix)
        self.assertIn('localStorage.setItem(key', APP)
        self.assertIn('id="reminder-list"', INDEX)

    def test_saved_views_include_daily_decision_states(self):
        for value in ('today', 'review', 'waiting', 'blocked', 'someday'):
            self.assertIn(f'<option value="{value}">', INDEX)
        self.assertIn("state.taskStatusFilter === 'review'", APP)


if __name__ == "__main__":
    unittest.main()
