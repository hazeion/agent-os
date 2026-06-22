from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
REACT_NOTES = (ROOT / "docs" / "react-readiness.md").read_text(encoding="utf-8")


class NextPhaseReadinessTests(unittest.TestCase):
    def test_refresh_uses_view_gated_fetches_for_future_react_refactor(self):
        refresh_block = APP_JS[APP_JS.index("async function refresh") : APP_JS.index("function queueMessageSearch")]
        self.assertIn("const activeView = state.activeView", refresh_block)
        self.assertIn("activeView === 'today' || activeView === 'calendar'", refresh_block)
        self.assertIn("activeView === 'today' || activeView === 'agents'", refresh_block)
        self.assertIn("activeView === 'projects'", refresh_block)

    def test_react_readiness_notes_document_no_premature_refactor(self):
        self.assertIn("Do **not** migrate to React yet", REACT_NOTES)
        self.assertIn("Dashboard-native project/task create/edit forms", REACT_NOTES)
        self.assertIn("Live Agent Pulse 2.0 heartbeat", REACT_NOTES)

    def test_dashboard_identity_is_project_owned_not_hardcoded(self):
        self.assertIn('read_json_file("dashboard.json", {})', SERVER)
        self.assertIn("AGENT_OS_DISPLAY_NAME", SERVER)
        self.assertNotIn('"Brandon"', SERVER)

    def test_calendar_integration_stays_read_only_and_uses_seven_day_agenda(self):
        self.assertIn('GOOGLE_TOKEN = HERMES_HOME / "google_token.json"', SERVER)
        self.assertIn('https://www.googleapis.com/auth/calendar.readonly', SERVER)
        self.assertIn('def google_calendar_events(days: int = 7', SERVER)
        self.assertIn('"stale": local_stale', SERVER)
        self.assertNotIn('GOOGLE_TOKEN.write_text', SERVER)
        self.assertIn('Next 7 Days', (ROOT / "public" / "index.html").read_text(encoding="utf-8"))
        self.assertIn('Read-only agenda; Agent OS never writes calendar events.', APP_JS)
        self.assertIn('CALENDAR_CACHE_TTL_SECONDS = 300', SERVER)
        self.assertIn('cached_calendar_payload(cache_key)', SERVER)
        self.assertIn('"cache"', SERVER)

    def test_project_search_hydrates_project_data_without_full_refresh(self):
        self.assertIn('async function ensureProjectsLoaded()', APP_JS)
        self.assertIn('await ensureProjectsLoaded()', APP_JS)
        self.assertIn("await setView('projects', { refreshOnChange: false })", APP_JS)
        self.assertIn('state.projectsLoaded = true', APP_JS)

    def test_dashboard_json_writes_are_allowlisted_to_data_files(self):
        self.assertIn('ALLOWED_DATA_WRITES = {', SERVER)
        self.assertIn('if name not in ALLOWED_DATA_WRITES', SERVER)
        self.assertIn('path.parent != data_root', SERVER)
        self.assertIn('write_json_file("attention.json", attention)', SERVER)


if __name__ == "__main__":
    unittest.main()
