from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE_JS = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
DESIGN_DOC = (ROOT / "docs" / "compact-dark-dashboard-design.md").read_text(encoding="utf-8")


class VisualContractTests(unittest.TestCase):
    def test_compact_dark_board_design_doc_and_tokens_exist(self):
        self.assertIn("Mentat Compact Dark Dashboard Design", DESIGN_DOC)
        self.assertIn("Feature parity", DESIGN_DOC)
        self.assertIn("--radius: 2px", DESIGN_DOC)
        self.assertIn("Compact Dark Board Rewrite", CSS)
        compact_block = CSS[CSS.index("/* Compact Dark Board Rewrite") :]
        self.assertIn("--bg: #050505", compact_block)
        self.assertIn("--card: #121212", compact_block)
        self.assertIn("--radius: 2px", compact_block)
        self.assertIn("grid-template-columns: 1fr;", compact_block)
        self.assertIn("min-height: 72px", compact_block)
        self.assertIn("grid-auto-rows: 78px", compact_block)

    def test_hero_title_uses_jetbrains_mono_and_cool_theme_glow(self):
        self.assertIn("JetBrains Mono", CSS)
        hero_block = CSS[CSS.index(".command-header .hero-title") : CSS.index(".command-header .hero-title::after")]
        self.assertIn("JetBrains Mono", hero_block)
        self.assertIn("--hero-blue", hero_block)
        self.assertNotIn("--led-amber", hero_block)

    def test_sidebar_brand_contains_digitized_brain_not_plain_ao(self):
        brand_block = INDEX[INDEX.index('<div class="brand-block">') : INDEX.index('<nav class="nav-groups">')]
        header_block = INDEX[INDEX.index('<header class="command-header">') : INDEX.index('</header>')]
        self.assertIn("brain-brand", brand_block)
        self.assertIn("brain-frame", brand_block)
        self.assertIn("Digitized Mentat brain logo", brand_block)
        self.assertNotIn('class="brain-orb"', header_block)
        self.assertNotIn("15-frame cortex", header_block)
        self.assertNotIn(">AO</div>", brand_block)

    def test_brain_animation_is_low_frame_rate_and_respects_reduced_motion(self):
        self.assertIn("steps(15, end)", CSS)
        self.assertNotIn("15-frame cortex", INDEX)
        self.assertNotIn("15fps cortex", INDEX)
        self.assertIn("brain-spin", CSS)
        self.assertIn("prefers-reduced-motion", CSS)
        reduced_motion_block = CSS[CSS.index("prefers-reduced-motion") :]
        self.assertIn("animation: none !important", reduced_motion_block)
        self.assertNotIn("animation-name: brain-spin", reduced_motion_block)

    def test_projects_tasks_view_uses_refined_a_task_inspector(self):
        self.assertIn('id="selected-task-panel"', INDEX)
        self.assertIn('id="selected-task-detail"', INDEX)
        self.assertIn("Selected Task", INDEX)
        self.assertIn("function renderSelectedTaskInspector", APP_JS)
        self.assertIn("selectedTaskId", APP_JS)
        self.assertIn("task-list-item-button", APP_JS)
        self.assertIn("data-task-id", APP_JS)
        self.assertIn("aria-pressed", APP_JS)
        self.assertIn(".task-detail-card", CSS)
        self.assertIn(".task-list-item-button.active", CSS)

    def test_refined_a_mobile_fallback_avoids_duplicate_status_pill_in_detail_header(self):
        self.assertIn('id="selected-task-back"', INDEX)
        self.assertIn('"queue"\n      "status"', CSS)
        self.assertIn("task-detail-meta-row", APP_JS)
        self.assertNotIn("Status</small><strong", APP_JS)
        self.assertNotIn("selected-task-status-pill", INDEX + APP_JS)

    def test_task_status_dropdown_uses_native_select_surface(self):
        dropdown_block = CSS[CSS.index(".status-filter-select {") : CSS.index(".status-filter-select:focus-visible {")]
        self.assertIn("appearance: none", dropdown_block)
        self.assertIn("min-width: 12.4rem;", dropdown_block)
        self.assertIn("cursor: pointer;", dropdown_block)
        self.assertIn("background: rgba(4, 8, 14, .82)", dropdown_block)

    def test_projects_tasks_layout_gives_selected_task_more_room(self):
        layout_block = CSS[CSS.index(".project-command-grid {") : CSS.index("#projects-panel {")]
        self.assertIn("minmax(360px, .72fr)", layout_block)
        self.assertIn("gap: 14px;", layout_block)

    def test_agent_pulse_now_renders_live_heartbeat_registry(self):
        self.assertIn('id="agent-pulse-panel"', INDEX)
        self.assertIn('id="agent-pulse"', INDEX)
        self.assertIn('id="agent-pulse-pill"', INDEX)
        self.assertIn('renderAgentPulse(payload = {})', APP_JS)
        self.assertIn('endpoints.agents', APP_JS)
        self.assertIn('Heartbeat stale', APP_JS)
        self.assertIn('agent-pulse-guidance', APP_JS)
        self.assertIn('.agent-pulse-summary', CSS)
        self.assertIn('.agent-pulse-list', CSS)
        self.assertIn('.agent-pulse-item', CSS)
        self.assertIn('.agent-pulse-guidance', CSS)
        self.assertIn('.agent-pulse-command', CSS)

    def test_today_next_moves_support_project_filter_and_task_jump(self):
        self.assertIn('id="focus-task-list"', INDEX)
        self.assertNotIn('id="attention-panel"', INDEX)
        self.assertNotIn('id="attention-count"', INDEX)
        self.assertNotIn('id="attention-list"', INDEX)
        render_cards_block = APP_JS[APP_JS.index('function renderCards') : APP_JS.index('function renderAttention')]
        self.assertNotIn('#attention-panel', render_cards_block)
        self.assertIn('id="today-project-select"', APP_JS)
        self.assertIn('projectOptionsFromTasks', APP_JS)
        self.assertIn("activeView === 'today' || activeView === 'projects'", APP_JS)
        self.assertIn('focusTaskIndicator', APP_JS)
        self.assertIn('focus-task-indicator', APP_JS)
        self.assertIn("key: 'attention'", APP_JS)
        self.assertIn("key: 'due'", APP_JS)
        self.assertIn("key: 'completed'", APP_JS)
        self.assertIn("setView('projects')", APP_JS)
        self.assertIn('data-focus-task-id', APP_JS)
        self.assertIn('data-focus-task-area', APP_JS)
        self.assertIn('.today-project-select', CSS)
        self.assertIn('.focus-task-indicator', CSS)
        self.assertIn('.focus-task-attention', CSS)
        self.assertIn('.focus-task-due', CSS)
        self.assertIn('.focus-task-completed', CSS)

    def test_agents_sessions_detail_has_replay_tab_and_trace_sections(self):
        self.assertIn('id="session-select"', INDEX)
        self.assertIn('class="session-select"', INDEX)
        self.assertNotIn('id="session-analytics-panel"', INDEX)
        self.assertNotIn('id="session-list"', INDEX)
        self.assertIn('sessionSelect', APP_JS)
        self.assertIn('data-session-detail-tab="replay"', APP_JS)
        self.assertIn('data-session-detail-tab="transcript"', APP_JS)
        self.assertIn('function renderReplayView', APP_JS)
        self.assertIn('fetchSessionReplay', CORE_JS)
        self.assertIn('/replay', CORE_JS)
        self.assertLess(APP_JS.index('Run Summary'), APP_JS.index('User Intent'))
        self.assertLess(APP_JS.index('User Intent'), APP_JS.index('Outcome + Suggested Next Step'))
        self.assertLess(APP_JS.index('Outcome + Suggested Next Step'), APP_JS.index('Agent Actions'))
        self.assertIn('Error Blockers', APP_JS)
        self.assertIn('Code / File Summary', APP_JS)
        self.assertIn('Suggest first, write later', APP_JS)
        self.assertIn('.session-detail-tabs', CSS)
        self.assertIn('.session-controls-card', CSS)
        self.assertIn('.session-select', CSS)
        self.assertIn('.replay-summary-grid', CSS)
        self.assertIn('.trace-section-grid', CSS)


if __name__ == "__main__":
    unittest.main()
