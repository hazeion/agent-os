from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE = (ROOT / "public" / "core.js").read_text(encoding="utf-8")


class DailyWorkflowUiTests(unittest.TestCase):
    def test_today_centers_plan_calendar_activity_and_capture(self):
        self.assertIn('id="quick-capture-form"', INDEX)
        self.assertIn('id="today-calendar-panel"', INDEX)
        self.assertIn('id="calendar-list"', INDEX)
        self.assertIn('id="agent-activity-panel"', INDEX)
        self.assertIn("planned_for_today", APP)
        self.assertIn("manual_rank", APP)
        self.assertIn("reorderTodayTask", CORE)

    def test_task_editor_exposes_personal_planning_depth(self):
        for field in ("estimated_minutes", "scheduled_start", "scheduled_end", "reminder_at", "recurrence_frequency", "subtasks", "depends_on"):
            self.assertIn(f'name="{field}"', APP)
        self.assertIn("data-subtask-toggle", APP)

    def test_calendar_actions_create_and_link_tasks(self):
        self.assertIn("data-calendar-create-task", APP)
        self.assertIn("data-calendar-link-task", APP)
        self.assertIn("createTaskFromCalendarEvent", CORE)
        self.assertIn("linkTaskToCalendarEvent", CORE)

    def test_global_search_is_grouped_and_does_not_navigate_on_input(self):
        self.assertIn('id="global-search-results"', INDEX)
        self.assertIn('role="combobox"', INDEX)
        self.assertIn("function renderGlobalSearchResults", APP)
        self.assertIn("navigateGlobalSearchResult", APP)
        input_block = APP[APP.index("globalSearch.addEventListener('input'"):APP.index("globalSearch.addEventListener('keydown'")]
        self.assertNotIn("setView(", input_block)


if __name__ == "__main__":
    unittest.main()
