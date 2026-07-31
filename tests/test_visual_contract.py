from pathlib import Path
import re
import struct
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE_JS = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
LOGO = ROOT / "public" / "mentat-logo.png"
EMERALD_LOGO = ROOT / "public" / "mentat-mark-emerald.png"


def png_rgba_contract(path):
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError(f"{path.name} is not a PNG")

    chunks = []
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        chunks.append((kind, payload))
        offset += 12 + length

    ihdr = next(payload for kind, payload in chunks if kind == b"IHDR")
    width, height, bit_depth, color_type, compression, filtering, interlace = (
        struct.unpack(">IIBBBBB", ihdr)
    )
    if (bit_depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
        return width, height, color_type, False

    compressed = b"".join(payload for kind, payload in chunks if kind == b"IDAT")
    first_scanline = zlib.decompress(compressed)
    # The first pixel has no left or prior-row predictor under any PNG filter,
    # so its fourth byte is the decoded alpha value. The production mark keeps
    # the top-left background transparent.
    return width, height, color_type, first_scanline[4] < 255


class VisualContractTests(unittest.TestCase):
    def test_hidden_attribute_remains_authoritative_over_component_display_rules(self):
        hidden_rule = re.search(
            r"(?m)^\[hidden\]\s*\{\s*display:\s*none\s*!important;\s*\}",
            CSS,
        )
        self.assertIsNotNone(hidden_rule)
        self.assertIn('id="clear-project-filter" hidden', INDEX)
        self.assertNotIn('id="selected-task-cancel"', INDEX)
        self.assertEqual(INDEX.count('data-task-editor-cancel'), 0)
        self.assertEqual(APP_JS.count('data-task-editor-cancel'), 2)
        editor = APP_JS[
            APP_JS.index('<form id="task-editor-form"') : APP_JS.index(
                'syncTaskEditorControls(tasks);',
                APP_JS.index('<form id="task-editor-form"'),
            )
        ]
        self.assertEqual(editor.count('data-task-editor-cancel'), 1)
        self.assertLess(
            editor.index('data-task-editor-cancel'),
            editor.index('class="task-editor-grid"'),
        )
        self.assertIn("if (backButton) backButton.hidden = editorActive", APP_JS)

    def test_screen_reader_only_utility_is_globally_hidden(self):
        start = CSS.index(".sr-only {")
        sr_only = CSS[start : CSS.index("\n}", start)]
        self.assertIn("position: absolute", sr_only)
        self.assertIn("width: 1px", sr_only)
        self.assertIn("height: 1px", sr_only)
        self.assertIn("overflow: hidden", sr_only)
        self.assertIn("clip-path: inset(50%)", sr_only)
        self.assertIn("white-space: nowrap", sr_only)

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

    def test_phone_controls_share_reachable_targets_without_duplicate_theme_buttons(self):
        mobile_start = CSS.index("/* Mobile control ergonomics")
        mobile = CSS[mobile_start:].strip()
        expected = """/* Mobile control ergonomics: interactive controls share the same reachable
   target height, and the compact theme selector avoids a duplicate phone-only
   wall of theme buttons. */
@media (max-width: 640px) {
  :is(
    :root[data-ui-shell] .home-focus-scope .today-project-select,
    :root[data-ui-shell] .home-schedule-link,
    :root[data-ui-shell] .agent-console-runtime-row .agent-console-select,
    :root[data-ui-shell] .agent-console-command-bar .agent-console-form textarea,
    :root[data-ui-shell] .theme-select
  ) {
    min-height: 44px;
  }

  #view-settings .theme-preview-grid {
    display: none;
  }
}"""
        self.assertEqual(mobile, expected)
        self.assertEqual(INDEX.count('id="theme-select"'), 1)

    def test_phone_control_rule_has_enough_specificity_to_win_the_shell_cascade(self):
        mobile = CSS[CSS.index("/* Mobile control ergonomics") :]
        selector_pairs = (
            (
                ":root[data-ui-shell='emerald'] .home-focus-scope .today-project-select",
                ":root[data-ui-shell] .home-focus-scope .today-project-select",
            ),
            (
                ":root[data-ui-shell='emerald'] .agent-console-runtime-row .agent-console-select",
                ":root[data-ui-shell] .agent-console-runtime-row .agent-console-select",
            ),
            (
                ":root[data-ui-shell='emerald'] .agent-console-command-bar .agent-console-form textarea",
                ":root[data-ui-shell] .agent-console-command-bar .agent-console-form textarea",
            ),
            (".theme-select", ":root[data-ui-shell] .theme-select"),
        )

        def specificity(selector):
            ids = len(re.findall(r"#[\w-]+", selector))
            class_like = len(
                re.findall(r"\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+", selector)
            )
            elements = len(
                re.findall(r"(?:^|[ >+~])([a-z][\w-]*)", selector)
            )
            return ids, class_like, elements

        mobile_start = CSS.index("/* Mobile control ergonomics")
        for competing, selector in selector_pairs:
            with self.subTest(selector=selector):
                self.assertIn(selector, mobile)
                competing_start = CSS.index(f"{competing} {{")
                competing_end = CSS.index("}", competing_start)
                self.assertLess(competing_start, mobile_start)
                self.assertNotIn("!important", CSS[competing_start:competing_end])
                self.assertGreaterEqual(specificity(selector), specificity(competing))

        self.assertNotIn("\n    .agent-console-select,", mobile)

    def test_phone_shell_controls_complete_the_44px_target_contract(self):
        def subject_sizing_rules(css_text, class_name, properties):
            class_token = re.compile(rf"\.{re.escape(class_name)}(?![\w-])")
            declarations = "|".join(re.escape(prop) for prop in properties)
            sizing = re.compile(rf"(?:^|;)\s*(?:{declarations})\s*:", re.MULTILINE)
            overrides = []
            for selector_group, body in re.findall(
                r"([^{}]+)\{([^{}]*)\}", css_text
            ):
                if not sizing.search(body):
                    continue
                for selector in selector_group.split(","):
                    rightmost = re.split(r"\s+|[>+~]", selector.strip())[-1]
                    match = class_token.search(rightmost)
                    if match and not rightmost[match.end() :].startswith("::"):
                        overrides.append((selector.strip(), body))
            return overrides

        final_shell_start = CSS.index("/* Final shell overrides for the operations top bar")
        final_shell = CSS[final_shell_start:]
        phone_start = final_shell.index("@media (max-width: 640px)")
        phone = final_shell[phone_start : final_shell.index("/* The visible control box", phone_start)]
        connection = re.search(
            r":root\[data-ui-shell='emerald'\] \.connection-status-button\s*\{([^}]*)\}",
            phone,
        )
        self.assertIsNotNone(connection)
        self.assertIn("min-height: 44px", connection.group(1))
        absolute_phone_start = final_shell_start + phone_start
        preceding_connection_rules = re.findall(
            r":root\[data-ui-shell='emerald'\] \.connection-status-button\s*\{([^}]*)\}",
            CSS[:absolute_phone_start],
        )
        competing = next(
            rule
            for rule in reversed(preceding_connection_rules)
            if "min-height:" in rule
        )
        self.assertIn("min-height: 42px", competing)
        self.assertNotIn("!important", competing)
        self.assertNotIn("!important", connection.group(1))
        connection_selector = ":root[data-ui-shell='emerald'] .connection-status-button"
        connection_properties = (
            "height",
            "min-height",
            "max-height",
            "block-size",
            "min-block-size",
            "max-block-size",
        )
        connection_rules = subject_sizing_rules(
            CSS, "connection-status-button", connection_properties
        )
        self.assertEqual(
            [selector for selector, _body in connection_rules],
            [connection_selector, connection_selector, connection_selector],
        )
        self.assertEqual(
            [
                re.search(r"min-height:\s*(\d+px)", body).group(1)
                for _selector, body in connection_rules
            ],
            ["40px", "42px", "44px"],
        )
        self.assertTrue(all("!important" not in body for _, body in connection_rules))
        self.assertTrue(
            subject_sizing_rules(
                ".command-header .connection-status-button { min-height: 42px !important; }",
                "connection-status-button",
                ("min-height",),
            )
        )
        self.assertEqual(
            subject_sizing_rules(
                ".connection-status-button::after { height: 2px; }",
                "connection-status-button",
                ("height",),
            ),
            [],
        )

        drawer_start = CSS.index("/* Drawer shell")
        drawer_end = CSS.index("@media (max-width: 640px)", drawer_start)
        drawer = CSS[drawer_start:drawer_end]
        close = re.search(
            r":root\[data-ui-shell='emerald'\] \.mobile-nav-close\s*\{([^}]*)\}",
            drawer,
        )
        self.assertIsNotNone(close)
        self.assertIn("width: 44px", close.group(1))
        self.assertIn("height: 44px", close.group(1))
        self.assertIn("flex: 0 0 44px", close.group(1))
        close_properties = (
            "width",
            "height",
            "min-width",
            "min-height",
            "max-width",
            "max-height",
            "inline-size",
            "block-size",
            "min-inline-size",
            "min-block-size",
            "max-inline-size",
            "max-block-size",
            "flex",
            "flex-basis",
        )
        close_rules = subject_sizing_rules(CSS, "mobile-nav-close", close_properties)
        self.assertEqual(
            [selector for selector, _body in close_rules],
            [":root[data-ui-shell='emerald'] .mobile-nav-close"],
        )
        self.assertNotIn("!important", close_rules[0][1])
        self.assertTrue(
            subject_sizing_rules(
                ".sidebar .mobile-nav-close { width: 40px !important; }",
                "mobile-nav-close",
                close_properties,
            )
        )
        self.assertEqual(
            subject_sizing_rules(
                ".mobile-nav-close svg { width: 20px; }",
                "mobile-nav-close",
                close_properties,
            ),
            [],
        )

        icon = CSS[CSS.index(".mobile-nav-close svg {") :]
        icon = icon[: icon.index("}")]
        self.assertIn("width: 20px", icon)
        self.assertIn("height: 20px", icon)

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

    def test_product_brand_stays_mentat_and_home_keeps_an_accessible_page_heading(self):
        production_branding = INDEX + APP_JS
        self.assertNotIn("Mentat Operations", production_branding)
        self.assertNotIn("Mission Control", production_branding)
        self.assertRegex(INDEX, r'id="brand-name"[^>]*>Mentat<')
        self.assertRegex(INDEX, r'<h1[^>]*class="[^"]*\bhero-title\b')
        self.assertIn("hero.textContent = title", APP_JS)
        self.assertIn("hero.setAttribute('aria-label', title)", APP_JS)
        greeting_block = APP_JS[
            APP_JS.index("function renderGreeting") : APP_JS.index("function setView")
        ]
        self.assertIn("state.appName = 'Mentat'", greeting_block)
        self.assertIn("brand.textContent = 'Mentat'", greeting_block)
        self.assertIn("document.title = 'Mentat'", greeting_block)
        self.assertNotIn("identity.app_name", greeting_block)
        final_shell_css = CSS[CSS.index("/* Final shell overrides for the operations top bar") :]
        self.assertIn(".topbar-context .hero-title", final_shell_css)
        self.assertIn("clip-path: inset(50%)", final_shell_css)

    def test_shell_uses_transparent_emerald_portrait_and_keeps_source_logo(self):
        header_block = INDEX[
            INDEX.index('<header class="command-header">') : INDEX.index('</header>')
        ]
        self.assertTrue(LOGO.is_file())
        self.assertGreater(LOGO.stat().st_size, 10_000)
        self.assertTrue(EMERALD_LOGO.is_file())
        self.assertGreater(EMERALD_LOGO.stat().st_size, 10_000)
        self.assertNotEqual(LOGO.read_bytes(), EMERALD_LOGO.read_bytes())
        width, height, color_type, has_transparency = png_rgba_contract(EMERALD_LOGO)
        self.assertGreaterEqual(width, 256)
        self.assertGreaterEqual(height, 256)
        self.assertEqual(color_type, 6)
        self.assertTrue(has_transparency)
        self.assertIn('src="/mentat-mark-emerald.png"', INDEX)
        self.assertIn(
            'rel="icon" type="image/png" href="/mentat-mark-emerald.png"',
            INDEX,
        )
        self.assertNotIn('class="brain-orb"', header_block)
        self.assertNotIn("15-frame cortex", header_block)
        self.assertNotIn(">AO</div>", INDEX)

    def test_six_existing_view_keys_and_critical_mounts_remain_exactly_once(self):
        expected = ["today", "agents", "calendar", "projects", "notes", "settings"]
        self.assertEqual(re.findall(r'\bdata-view="([^"]+)"', INDEX), expected)
        panel_keys = re.findall(r'\bdata-view-panel="([^"]+)"', INDEX)
        self.assertEqual(len(panel_keys), len(expected))
        self.assertEqual(set(panel_keys), set(expected))
        critical_ids = (
            "main-content",
            "primary-navigation",
            "navigation-toggle",
            "home-operations-dashboard",
            "today-active-work-panel",
            "home-live-agents-panel",
            "today-calendar-panel",
            "home-projects-panel",
            "home-crons-panel",
            "focus-task-list",
            "home-live-agent-list",
            "home-project-stats",
            "home-project-queue",
            "home-cron-list",
            "project-list",
            "message-search-results",
            "global-search",
            "global-search-results",
            "health-dot",
            "health-label",
            "refresh-rate",
            "last-updated",
        )
        for element_id in critical_ids:
            self.assertEqual(
                len(re.findall(rf'\bid="{re.escape(element_id)}"', INDEX)),
                1,
                element_id,
            )

    def test_shell_accessibility_hooks_and_current_page_semantics_exist(self):
        self.assertRegex(
            INDEX,
            r'<a[^>]*class="[^"]*\bskip-link\b[^"]*"[^>]*href="#main-content"',
        )
        toggle = re.search(r'<button[^>]*id="navigation-toggle"[^>]*>', INDEX)
        self.assertIsNotNone(toggle)
        controlled = re.search(r'aria-controls="([^"]+)"', toggle.group(0))
        self.assertIsNotNone(controlled)
        self.assertEqual(INDEX.count(f'id="{controlled.group(1)}"'), 1)
        self.assertIn('id="primary-navigation"', INDEX)
        self.assertIn('aria-expanded="false"', toggle.group(0))
        self.assertRegex(toggle.group(0), r'aria-label="[^"]+"')
        self.assertIn("aria-current", APP_JS)
        self.assertIn("'page'", APP_JS)
        self.assertIn("event.key === 'Escape'", APP_JS)
        self.assertIn("navigationReturnFocus", APP_JS)
        self.assertIn("target?.focus()", APP_JS)
        header_block = INDEX[
            INDEX.index('<header class="command-header">') : INDEX.index("</header>")
        ]
        self.assertIn('id="navigation-toggle"', header_block)
        self.assertIn('role="group" aria-label="System status details" tabindex="0"', INDEX)
        self.assertIn(
            'id="health-label" role="status" aria-live="polite" aria-atomic="true"',
            INDEX,
        )
        focusables = APP_JS[
            APP_JS.index("function mobileNavigationFocusables")
            : APP_JS.index("function initializeMobileNavigation")
        ]
        self.assertNotIn("#navigation-toggle", focusables)
        self.assertIn("window.getComputedStyle(element)", focusables)
        self.assertIn("element.getClientRects().length > 0", focusables)
        self.assertIn("sidebar.setAttribute('role', 'dialog')", APP_JS)
        self.assertIn("sidebar.setAttribute('aria-modal', 'true')", APP_JS)

    def test_emerald_responsive_status_and_contrast_contracts(self):
        self.assertIn("@media (min-width: 901px) and (max-width: 1199px)", CSS)
        self.assertNotIn("@media (min-width: 900px) and (max-width: 1199px)", CSS)
        emerald_navigation = CSS[
            CSS.index(":root[data-ui-shell='emerald'] .nav-groups {")
            : CSS.index(":root[data-ui-shell='emerald'] .nav-groups section")
        ]
        self.assertIn("grid-template-columns: minmax(0, 1fr)", emerald_navigation)
        self.assertIn("grid-auto-flow: row", emerald_navigation)
        drawer = CSS[CSS.index("@media (max-width: 900px)") :]
        self.assertIn("position: sticky", drawer)
        self.assertIn(
            ".nav-item > span:last-child:not(:first-child)",
            drawer,
        )
        self.assertIn("display: inline", drawer)
        self.assertIn(".sidebar-footer:is(:hover, :focus-visible, :focus-within)", CSS)
        self.assertIn(":root[data-contrast='high']", CSS)
        self.assertIn("--operations-border-control: var(--operations-neutral-550)", CSS)
        self.assertIn("border: 1px solid var(--operations-border-control)", CSS)

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
        self.assertIn('id="agent-console-provider-select"', today_block)
        self.assertIn('id="agent-console-model-select"', today_block)
        self.assertIn('id="agent-console-tool-toggle"', today_block)
        self.assertNotIn('id="agent-console-apply-model"', today_block)
        self.assertIn('id="agent-console-transcript"', today_block)
        self.assertIn('id="agent-console-chat"', today_block)
        self.assertIn('id="agent-console-form"', today_block)
        self.assertIn('id="agent-console-prompt"', today_block)
        self.assertNotIn('id="agent-console-runtime-banner"', today_block)
        self.assertNotIn('id="calendar-panel"', today_block)
        self.assertNotIn('id="email-panel"', today_block)
        self.assertIn('function renderAgentConsole(payload = {})', APP_JS)
        self.assertIn('startAgentConsoleRun', CORE_JS)
        self.assertIn('stopAgentConsoleRun', CORE_JS)
        self.assertIn('previewAgentConsoleProvider', CORE_JS)
        self.assertIn('switchAgentConsoleProvider', CORE_JS)
        self.assertIn('.agent-console-chat', CSS)
        self.assertIn('.agent-console-runtime-row', CSS)
        self.assertIn('.agent-console-tool-activity', CSS)
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
        self.assertNotIn('id="overview-cards"', INDEX)
        self.assertNotIn('function renderCards', APP_JS)
        render_focus_block = APP_JS[
            APP_JS.index("function renderFocusTasks")
            : APP_JS.index("function dueTaskReminders")
        ]
        self.assertNotIn('#attention-panel', render_focus_block)
        self.assertIn('id="today-project-select"', APP_JS)
        self.assertIn('projectOptionsFromTasks', APP_JS)
        self.assertIn("data-home-open-view=\"projects\"", INDEX)
        self.assertIn('focusTaskIndicator', APP_JS)
        self.assertIn('home-focus-state', APP_JS)
        self.assertIn("key: 'attention'", APP_JS)
        self.assertIn("key: 'due'", APP_JS)
        self.assertIn("key: 'completed'", APP_JS)
        self.assertIn("setView('projects')", APP_JS)
        self.assertIn('data-focus-task-id', APP_JS)
        self.assertIn('data-focus-task-area', APP_JS)
        self.assertIn('.today-project-select', CSS)
        self.assertIn('.home-focus-state', CSS)
        self.assertIn('.home-focus-state.attention', CSS)
        self.assertIn('.home-focus-time.attention', CSS)
        self.assertIn('.home-focus-state.completed', CSS)
        self.assertIn('home-focus-item', render_focus_block)
        self.assertIn('Generated files', APP_JS)

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
        stylesheet_index = head_block.index('rel="stylesheet"')
        self.assertLess(head_block.index("mentat-theme"), stylesheet_index)
        self.assertLess(head_block.index("mentat-ui-shell-v1"), stylesheet_index)
        self.assertLess(head_block.index("mentat-contrast-v1"), stylesheet_index)
        self.assertRegex(head_block, r"let theme = ['\"]emerald['\"]")
        self.assertRegex(head_block, r"let shell = ['\"]emerald['\"]")
        self.assertIn("document.documentElement.dataset.theme = theme", head_block)
        self.assertIn("document.documentElement.dataset.uiShell = shell", head_block)
        self.assertIn("document.documentElement.dataset.contrast", head_block)
        self.assertIn("prefers-contrast: more", head_block)
        self.assertIn('/core.js?v=emerald-shell-1', INDEX)
        self.assertIn('/app.js?v=emerald-shell-1', INDEX)
        self.assertNotIn('compact-dark-board-1', INDEX)
        self.assertIn("applyTheme(saved || document.documentElement.dataset.theme || THEMES[0].id)", APP_JS)

    def test_settings_view_exposes_sitewide_theme_selector(self):
        self.assertIn('id="theme-select"', INDEX)
        self.assertIn('id="theme-preview-grid"', INDEX)
        self.assertIn('Theme Studio', INDEX)
        self.assertIn("THEME_STORAGE_KEY = 'mentat-theme'", APP_JS)
        self.assertIn("SHELL_STORAGE_KEY = 'mentat-ui-shell-v1'", APP_JS)
        self.assertIn("CONTRAST_STORAGE_KEY = 'mentat-contrast-v1'", APP_JS)
        self.assertIn("currentTheme: 'emerald'", CORE_JS)
        self.assertIn('function applyTheme(themeId = state.currentTheme || THEMES[0].id)', APP_JS)
        self.assertIn("document.documentElement.dataset.theme = theme.id", APP_JS)
        self.assertIn("localStorage.setItem(THEME_STORAGE_KEY, theme.id)", APP_JS)
        self.assertIn("localStorage.removeItem(CONTRAST_STORAGE_KEY)", APP_JS)
        self.assertIn('value="system"', INDEX)
        self.assertIn('value="standard"', INDEX)
        self.assertIn('value="high"', INDEX)
        self.assertIn('value="classic"', INDEX)
        dark_themes = ('emerald', 'compact-dark', 'catppuccin', 'nord', 'aurora', 'tokyo-night', 'gruvbox-dark', 'dracula', 'one-dark', 'solarized-dark')
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
