from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE_JS = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
LOGO = ROOT / "public" / "mentat-logo.png"


class VisualContractTests(unittest.TestCase):
    def test_dashboard_action_groups_use_edge_alignment_without_button_distribution(self):
        panel_controls = CSS[CSS.index(".panel-controls {") : CSS.index(".task-status-filter-shell")]
        item_actions = CSS[CSS.index(".item-actions {") : CSS.index(".action-button")]
        editor_start = CSS.rindex("\n.task-editor-actions {\n  align-items:") + 1
        editor_actions = CSS[editor_start : CSS.index(".config-pre", editor_start)]
        calendar_actions = CSS[
            CSS.index(".calendar-task-actions {") : CSS.index(".global-search-wrap")
        ]

        self.assertIn("justify-content: flex-end", panel_controls)
        self.assertIn("justify-content: flex-end", item_actions)
        self.assertIn("justify-content: flex-start", editor_actions)
        self.assertIn("justify-content: flex-start", calendar_actions)
        self.assertNotIn("justify-content: space-between", editor_actions)
        self.assertIn("flex-wrap: wrap", item_actions)
        self.assertIn("flex-wrap: wrap", calendar_actions)

    def test_legacy_agent_messages_ui_is_retired_but_context_packs_are_visible(self):
        self.assertNotIn("Agent Messages", INDEX)
        self.assertNotIn('id="agent-message-panel"', INDEX)
        self.assertNotIn("agentMessages", APP_JS)
        self.assertIn("Context Packs", INDEX)
        self.assertIn('id="context-pack-list"', INDEX)
        self.assertIn("stageContextPack", CORE_JS)

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

    def test_sidebar_and_browser_use_mentat_portrait_logo(self):
        brand_block = INDEX[INDEX.index('<div class="brand-block">') : INDEX.index('<nav class="nav-groups">')]
        header_block = INDEX[INDEX.index('<header class="command-header">') : INDEX.index('</header>')]
        self.assertTrue(LOGO.is_file())
        self.assertGreater(LOGO.stat().st_size, 10_000)
        self.assertIn("mentat-brand", brand_block)
        self.assertIn("Mentat portrait logo", brand_block)
        self.assertIn('src="/mentat-logo.png"', brand_block)
        self.assertIn('rel="icon" type="image/png" href="/mentat-logo.png"', INDEX)
        self.assertNotIn('class="brain-orb"', header_block)
        self.assertNotIn("15-frame cortex", header_block)
        self.assertNotIn(">AO</div>", brand_block)

    def test_portrait_logo_is_static_and_old_brain_art_is_retired(self):
        logo_block = CSS[CSS.index(".mentat-brand {") : CSS.index(".brand-name")]
        self.assertNotIn("animation:", logo_block)
        self.assertNotIn("brain-spin", CSS)
        self.assertNotIn("brain-frame", INDEX)
        self.assertNotIn("15-frame cortex", INDEX)
        self.assertIn("prefers-reduced-motion", CSS)

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

    def test_today_agent_console_replaces_calendar_and_email_panes(self):
        today_block = INDEX[INDEX.index('id="view-today"') : INDEX.index('id="view-agents"')]
        self.assertIn('id="agent-console-panel"', today_block)
        self.assertIn('id="agent-console-agent"', today_block)
        self.assertIn('id="agent-console-model-select"', today_block)
        self.assertIn('id="agent-console-apply-model"', today_block)
        self.assertIn('id="agent-console-chat"', today_block)
        self.assertIn('id="agent-console-form"', today_block)
        self.assertIn('id="agent-console-prompt"', today_block)
        self.assertNotIn('id="calendar-panel"', today_block)
        self.assertNotIn('id="email-panel"', today_block)
        self.assertIn('function renderAgentConsole(payload = {})', APP_JS)
        self.assertIn('startAgentConsoleRun', CORE_JS)
        self.assertIn('stopAgentConsoleRun', CORE_JS)
        self.assertIn('previewAgentConsoleProvider', CORE_JS)
        self.assertIn('switchAgentConsoleProvider', CORE_JS)
        self.assertIn('.agent-console-chat', CSS)
        self.assertIn('.agent-console-working-mark', CSS)
        self.assertIn('agent-console-log-row', APP_JS)
        self.assertIn('agentConsoleCommands', APP_JS)
        self.assertNotIn('id="agent-console-status-pill"', today_block)

    def test_calendar_view_uses_responsive_operator_week_shell(self):
        calendar_block = INDEX[INDEX.index('id="view-calendar"') : INDEX.index('id="view-notes"')]
        required_ids = (
            'calendar-operator-panel',
            'calendar-week-label',
            'calendar-week-range',
            'calendar-week-previous',
            'calendar-week-today',
            'calendar-week-next',
            'calendar-source-status',
            'calendar-timezone',
            'calendar-week-scroll',
            'calendar-week-days',
            'calendar-all-day-events',
            'calendar-time-labels',
            'calendar-week-grid',
            'calendar-week-events',
            'calendar-now-line',
            'calendar-event-inspector',
            'calendar-inspector-close',
            'calendar-inspector-content',
        )
        for element_id in required_ids:
            self.assertIn(f'id="{element_id}"', calendar_block)

        self.assertIn('data-calendar-week-nav="previous"', calendar_block)
        self.assertIn('data-calendar-week-nav="today"', calendar_block)
        self.assertIn('data-calendar-week-nav="next"', calendar_block)
        self.assertIn('Calendar · read-only', calendar_block)
        self.assertNotIn('id="calendar-full-list"', calendar_block)
        self.assertNotIn('#calendar-full-list', CSS)
        self.assertNotIn('.calendar-week-host', CSS)
        self.assertNotIn('.calendar-operator-layout.inspector-open', CSS)
        self.assertNotIn('--calendar-day-min:', CSS)

        operator_css = CSS[CSS.index('/* Operator Week calendar */') : CSS.index('.agents-session-layout {')]
        self.assertIn('.calendar-week-day-headers,', operator_css)
        self.assertIn('repeat(7, minmax(0, 1fr))', operator_css)
        self.assertIn('overflow-x: auto', operator_css)
        self.assertIn('--calendar-week-min: 772px', operator_css)
        self.assertIn('--calendar-week-min: 876px', operator_css)
        self.assertIn('.calendar-week-now-line', operator_css)
        self.assertIn('.calendar-week-event', operator_css)
        self.assertIn('.calendar-event-inspector[hidden]', operator_css)

        header_actions = operator_css[
            operator_css.index('.calendar-header-actions {') : operator_css.index('.calendar-week-nav,')
        ]
        self.assertIn('justify-content: flex-end', header_actions)
        self.assertIn('flex-wrap: wrap', header_actions)
        self.assertNotIn('justify-content: space-between', header_actions)

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

    def test_session_history_contains_long_replays_in_its_own_scroller(self):
        self.assertIn('#conversation-library-panel {', CSS)
        self.assertIn('#conversation-library-panel .session-detail {', CSS)
        self.assertNotIn('#model-usage-panel {\n  grid-area: model;', CSS)
        self.assertIn('max-height: min(72vh, 900px);', CSS)
        self.assertIn('overscroll-behavior: contain;', CSS)
        session_rule = CSS[CSS.index('#conversation-library-panel .session-detail {'):]
        self.assertIn('overflow: auto;', session_rule.split('}', 1)[0])
        self.assertIn('.session-controls-card', CSS)
        self.assertIn('.session-select', CSS)
        self.assertIn('.replay-summary-grid', CSS)
        replay_grid_block = CSS[CSS.index('.replay-summary-grid {') : CSS.index('.replay-summary-card,')]
        self.assertIn('repeat(auto-fit, minmax(128px, 1fr))', replay_grid_block)
        self.assertIn('.trace-section-grid', CSS)

    def test_theme_preinit_applies_saved_theme_before_css(self):
        head_block = INDEX[INDEX.index('<head>') : INDEX.index('</head>')]
        self.assertLess(head_block.index("localStorage.getItem(key)"), head_block.index('/styles.css?v=context-packs-2'))
        self.assertIn("document.documentElement.dataset.theme = theme", head_block)
        self.assertIn('/core.js?v=context-packs-2', INDEX)
        self.assertIn('/app.js?v=context-packs-2', INDEX)
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
        dark_themes = ('compact-dark', 'catppuccin', 'nord', 'aurora', 'tokyo-night', 'gruvbox-dark', 'dracula', 'one-dark', 'solarized-dark')
        light_themes = ('light', 'github-light', 'gruvbox-light', 'solarized-light', 'catppuccin-latte', 'rose-pine-dawn')
        for theme in dark_themes + light_themes:
            self.assertIn(f"id: '{theme}'", APP_JS)
            self.assertIn(f'value="{theme}"', INDEX)
            if theme != 'compact-dark':
                self.assertIn(f":root[data-theme='{theme}']", CSS)
            self.assertIn(f'.theme-swatch-chip.theme-{theme}', CSS)
        self.assertEqual(APP_JS.count("mode: 'dark' },"), len(dark_themes))
        self.assertEqual(APP_JS.count("mode: 'light' },"), len(light_themes))
        self.assertIn('<optgroup label="Dark themes">', INDEX)
        self.assertIn('<optgroup label="Light themes">', INDEX)
        self.assertIn('.theme-preview-group', CSS)
        self.assertIn('.theme-preview-list', CSS)
        self.assertIn('.theme-preview-grid', CSS)
        self.assertIn('.theme-swatch.active', CSS)
        soft_light = CSS[CSS.index(":root[data-theme='light'] {") : CSS.index(":root[data-theme='catppuccin'] {")]
        self.assertIn('--bg: #dfe5ec;', soft_light)
        self.assertNotIn('--bg-elevated: #ffffff;', soft_light)
        self.assertIn('--header-bg:', CSS)
        self.assertIn('--panel-bg:', CSS)
        self.assertIn('--button-text: var(--text);', CSS)
        self.assertIn('color: var(--button-text);', CSS)
        self.assertNotIn('color: #e4e6ea;', CSS)
        self.assertIn('--calendar-fallback-bg:', CSS)
        self.assertIn('background: var(--calendar-fallback-bg);', CSS)
        self.assertIn('background: var(--calendar-local-event-bg);', CSS)
        self.assertIn('background: var(--panel-bg)', CSS)
        self.assertIn('color: var(--text-secondary)', CSS)
        self.assertNotIn('color: #b8b8bd;', CSS)
        self.assertIn('scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track)', CSS)


if __name__ == "__main__":
    unittest.main()
