from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE_JS = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
RUNTIME_CONFIG = (ROOT / "runtime_config.py").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


class NextPhaseReadinessTests(unittest.TestCase):
    def test_refresh_uses_view_gated_fetches_for_future_react_refactor(self):
        refresh_block = APP_JS[APP_JS.index("async function refresh") : APP_JS.index("function queueMessageSearch")]
        self.assertIn("const activeView = state.activeView", refresh_block)
        self.assertIn("activeView === 'calendar'", refresh_block)
        self.assertIn("activeView === 'today') requests.agentConsole", refresh_block)
        self.assertIn("activeView === 'today' || activeView === 'agents'", refresh_block)
        self.assertIn("activeView === 'projects'", refresh_block)

    def test_readme_documents_no_premature_frontend_build_step(self):
        self.assertIn("static HTML, CSS, and vanilla JavaScript", README)
        self.assertIn("There is currently **no npm install step**", README)
        self.assertIn("Agent Pulse live heartbeat registry", README)

    def test_dashboard_identity_is_project_owned_not_hardcoded(self):
        self.assertIn('read_json_file("dashboard.json", {})', SERVER)
        self.assertIn('env_value("DISPLAY_NAME")', RUNTIME_CONFIG)
        self.assertNotIn('"Brandon"', SERVER)

    def test_calendar_integration_stays_read_only_and_uses_seven_day_agenda(self):
        self.assertIn('GOOGLE_TOKEN = HERMES_HOME / "google_token.json"', SERVER)
        self.assertIn('https://www.googleapis.com/auth/calendar.readonly', SERVER)
        self.assertIn('def google_calendar_events(', SERVER)
        self.assertIn('days: int = 7', SERVER)
        self.assertIn('"stale": local_stale', SERVER)
        self.assertNotIn('GOOGLE_TOKEN.write_text', SERVER)
        calendar_view = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn('Operator Week', calendar_view)
        self.assertIn('id="calendar-week-grid"', calendar_view)
        self.assertIn('Read-only agenda; Mentat never writes calendar events.', APP_JS)
        self.assertIn('CALENDAR_CACHE_TTL_SECONDS = 300', SERVER)
        self.assertIn('cached_calendar_payload(cache_key)', SERVER)
        self.assertIn('"cache"', SERVER)

    def test_grouped_search_navigates_only_after_an_explicit_selection(self):
        self.assertIn('function renderGlobalSearchResults', APP_JS)
        self.assertIn('const payload = await searchDashboard(query)', APP_JS)
        self.assertIn('async function navigateGlobalSearchResult(result)', APP_JS)
        self.assertIn("await setView('projects')", APP_JS)
        input_block = APP_JS[
            APP_JS.index("globalSearch.addEventListener('input'") :
            APP_JS.index("globalSearch.addEventListener('keydown'")
        ]
        self.assertNotIn('setView(', input_block)

    def test_dashboard_json_writes_are_allowlisted_to_data_files(self):
        self.assertIn('ALLOWED_DATA_WRITES = {', SERVER)
        self.assertIn('allowlist = ALLOWED_DATA_WRITES if write else ALLOWED_DATA_READS', SERVER)
        self.assertIn('if name not in allowlist', SERVER)
        self.assertIn('"/" in name or "\\\\" in name', SERVER)
        self.assertIn('return _absolute_without_following(DATA_DIR) / name', SERVER)
        self.assertNotIn('(DATA_DIR / name).resolve()', SERVER)
        self.assertIn('update_json_file("attention.json", [], mutator)', SERVER)
    def test_core_script_loads_before_app_script(self):
        self.assertLess(INDEX.index('/core.js?v='), INDEX.index('/app.js?v='))

    def test_app_js_does_not_redefine_extracted_core_helpers(self):
        self.assertIn('const endpoints = {', CORE_JS)
        self.assertIn('const state = {', CORE_JS)
        self.assertIn('function escapeHtml', CORE_JS)
        self.assertIn('async function api', CORE_JS)
        self.assertNotIn('const endpoints = {', APP_JS)
        self.assertNotIn('const state = {', APP_JS)
        self.assertNotIn('function escapeHtml', APP_JS)
        self.assertNotIn('async function api', APP_JS)


if __name__ == "__main__":
    unittest.main()
