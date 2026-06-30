from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE_JS = (ROOT / "public" / "core.js").read_text(encoding="utf-8")


class VisualContractTests(unittest.TestCase):
    def test_compact_dark_board_tokens_exist(self):
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

    def test_project_portfolio_cards_stay_compact_without_progress_bars(self):
        render_projects_block = APP_JS[APP_JS.index("function renderProjects") : APP_JS.index("function isDateOnly")]
        render_scope_block = APP_JS[APP_JS.index("function renderProjectStatus") : APP_JS.index("function renderProjects")]
        self.assertIn("project-progress-text", render_projects_block)
        self.assertNotIn("progress-track mini", render_projects_block)
        self.assertIn("progress-track mini", render_scope_block)
        self.assertIn('id="project-scroll-left" aria-label="Scroll projects left" hidden', INDEX)
        self.assertIn('id="project-scroll-right" aria-label="Scroll projects right" hidden', INDEX)
        self.assertIn(".rail-arrow[hidden]", CSS)
        self.assertIn("contentWidth > availableWidth + 4", APP_JS)

    def test_selected_task_header_omits_detail_context_label(self):
        self.assertNotIn('id="selected-task-context"', INDEX)
        self.assertNotIn("selected detail", APP_JS)
        self.assertNotIn("history detail", APP_JS)

    def test_model_usage_pie_replaces_todays_agent_pulse_panel(self):
        self.assertNotIn('id="calendar-source-pill"', INDEX)
        self.assertNotIn('id="agent-pulse"', INDEX)
        self.assertNotIn('id="agent-pulse-pill"', INDEX)
        self.assertIn('id="model-usage-panel"', INDEX)
        self.assertIn('id="model-usage"', INDEX)
        self.assertIn('Model Usage (by Tokens)', INDEX)
        self.assertNotIn('id="model-usage-pill"', INDEX)
        self.assertIn('renderModelUsageChart(payload = {})', APP_JS)
        self.assertIn('conic-gradient', APP_JS)
        self.assertIn('endpoints.sessions', APP_JS)
        self.assertIn('renderAgentPulse(payload = {})', APP_JS)
        self.assertIn('.model-usage-shell', CSS)
        self.assertIn('.model-pie', CSS)
        self.assertIn('.model-usage-table', CSS)
        self.assertIn('.model-usage-table-scroll', CSS)
        self.assertIn('.model-usage-grid', CSS)

    def test_today_next_moves_support_project_filter_and_task_jump(self):
        self.assertIn('id="focus-task-list"', INDEX)
        self.assertNotIn('id="attention-panel"', INDEX)
        self.assertNotIn('id="attention-count"', INDEX)
        self.assertNotIn('id="attention-list"', INDEX)
        render_cards_end = APP_JS.index('function renderFocusTasks')
        render_cards_block = APP_JS[APP_JS.index('function renderCards') : render_cards_end]
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
        self.assertIn('replay-token-card', APP_JS)
        self.assertIn('summary.usage', APP_JS)
        self.assertIn('humanNumber(totalTokens)', APP_JS)
        self.assertIn('humanCost(usage.estimated_cost_usd)', APP_JS)
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
        replay_grid_block = CSS[CSS.index('.replay-summary-grid {') : CSS.index('.replay-summary-card,')]
        self.assertIn('repeat(auto-fit, minmax(128px, 1fr))', replay_grid_block)
        self.assertIn('.trace-section-grid', CSS)

    def test_theme_preinit_applies_saved_theme_before_css(self):
        head_block = INDEX[INDEX.index('<head>') : INDEX.index('</head>')]
        self.assertLess(head_block.index("localStorage.getItem(key)"), head_block.index('/styles.css?v=theme-studio-2'))
        self.assertIn("document.documentElement.dataset.theme = theme", head_block)
        self.assertIn('/core.js?v=theme-studio-2', INDEX)
        self.assertIn('/app.js?v=theme-studio-2', INDEX)
        self.assertNotIn('compact-dark-board-1', INDEX)
        self.assertIn("applyTheme(saved || document.documentElement.dataset.theme || THEMES[0].id)", APP_JS)

    def test_settings_view_exposes_sitewide_theme_selector(self):
        self.assertIn('id="theme-select"', INDEX)
        self.assertIn('id="theme-preview-grid"', INDEX)
        self.assertIn('Theme Studio', INDEX)
        self.assertIn("THEME_STORAGE_KEY = 'mentat-theme'", APP_JS)
        self.assertIn('function applyTheme(themeId = state.currentTheme || THEMES[0].id)', APP_JS)
        self.assertIn("document.documentElement.dataset.theme = theme.id", APP_JS)
        self.assertIn("localStorage.setItem(THEME_STORAGE_KEY, theme.id)", APP_JS)
        self.assertIn(":root[data-theme='light']", CSS)
        self.assertIn(":root[data-theme='catppuccin']", CSS)
        self.assertIn(":root[data-theme='nord']", CSS)
        self.assertIn(":root[data-theme='aurora']", CSS)
        self.assertIn('.theme-preview-grid', CSS)
        self.assertIn('.theme-swatch.active', CSS)
        self.assertIn('--header-bg:', CSS)
        self.assertIn('--panel-bg:', CSS)
        self.assertIn('background: var(--panel-bg)', CSS)
        self.assertIn('color: var(--text-secondary)', CSS)
        self.assertIn('scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track)', CSS)


if __name__ == "__main__":
    unittest.main()
