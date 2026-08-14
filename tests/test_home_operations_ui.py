from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")


class HomeOperationsUiTests(unittest.TestCase):
    def app_block(self, start: str, end: str) -> str:
        start_at = APP.index(start)
        return APP[start_at : APP.index(end, start_at)]

    def test_home_uses_reference_panel_order_without_metric_hero_cards(self):
        home = INDEX[
            INDEX.index('id="home-operations-dashboard"')
            : INDEX.index('id="view-agents"')
        ]
        ordered_mounts = (
            'id="today-active-work-panel"',
            'id="home-live-agents-panel"',
            'id="today-calendar-panel"',
            'id="home-projects-panel"',
            'id="home-crons-panel"',
            'id="agent-console-panel"',
        )
        positions = [home.index(mount) for mount in ordered_mounts]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('id="overview-cards"', INDEX)
        self.assertNotIn('function renderCards', APP)
        self.assertNotIn("#overview-cards", APP)

    def test_home_reserves_async_panel_height_and_describes_the_document(self):
        self.assertIn(
            '<meta name="description" content="Mentat is a local-first planning and operations dashboard for Hermes-powered workflows." />',
            INDEX,
        )
        focus_css = CSS[
            CSS.index(":root[data-ui-shell='emerald'] .home-focus-panel {")
            : CSS.index(":root[data-ui-shell='emerald'] #today-active-work-panel.home-focus-panel {")
        ]
        agents_css = CSS[
            CSS.index(":root[data-ui-shell='emerald'] .home-live-agents-panel {")
            : CSS.index(":root[data-ui-shell='emerald'] .home-today-panel {")
        ]
        self.assertIn("min-height: 430px", focus_css)
        self.assertIn("min-height: 430px", agents_css)
        mobile_start = CSS.index("@media (max-width: 900px)")
        mobile_rule_start = CSS.index(
            ":root[data-ui-shell='emerald'] .home-focus-panel,",
            mobile_start,
        )
        mobile_rule = CSS[
            mobile_rule_start
            : CSS.index(
                ":root[data-ui-shell='emerald'] .home-context-stack {",
                mobile_rule_start,
            )
        ]
        self.assertIn(".home-focus-panel,", mobile_rule)
        self.assertIn(".home-live-agents-panel,", mobile_rule)
        self.assertIn(".home-today-panel", mobile_rule)
        self.assertIn("min-height: 0", mobile_rule)

    def test_home_refresh_loads_real_operational_sources_and_degrades_optional_inventory(self):
        refresh = self.app_block("async function refresh()", "async function runMessageSearchRequest")
        for source in (
            "endpoints.tasks",
            "endpoints.calendar",
            "endpoints.projects",
            "endpoints.agentConsole",
            "endpoints.agentActivity",
            "endpoints.agents",
            "endpoints.crons",
        ):
            self.assertIn(source, refresh)
        self.assertIn("activeView === 'today'", refresh)
        self.assertIn("api(endpoints.agents).catch", refresh)
        self.assertIn("api(endpoints.crons).catch", refresh)
        self.assertIn("Hermes CRON inventory is temporarily unavailable.", refresh)

    def test_today_schedule_action_stays_below_utility_disclosures(self):
        class FooterStructureParser(HTMLParser):
            VOID_ELEMENTS = {
                "area",
                "base",
                "br",
                "col",
                "embed",
                "hr",
                "img",
                "input",
                "link",
                "meta",
                "param",
                "source",
                "track",
                "wbr",
            }

            def __init__(self):
                super().__init__()
                self.stack = []
                self.footer = None

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                node = {
                    "tag": tag,
                    "attrs": attributes,
                    "children": [],
                    "text": "",
                }
                if self.stack:
                    self.stack[-1]["children"].append(node)
                if (
                    tag == "div"
                    and "home-panel-footer"
                    in attributes.get("class", "").split()
                ):
                    self.footer = node
                if tag not in self.VOID_ELEMENTS:
                    self.stack.append(node)

            def handle_endtag(self, tag):
                if self.stack and self.stack[-1]["tag"] == tag:
                    self.stack.pop()

            def handle_data(self, data):
                if self.stack:
                    self.stack[-1]["text"] += data

        def classes(node):
            return set(node["attrs"].get("class", "").split())

        parser = FooterStructureParser()
        parser.feed(INDEX)
        self.assertIsNotNone(parser.footer)
        self.assertEqual(len(parser.footer["children"]), 2)

        utility_row, schedule_link = parser.footer["children"]
        self.assertEqual(utility_row["tag"], "div")
        self.assertIn("home-panel-utility-row", classes(utility_row))
        self.assertEqual(schedule_link["tag"], "a")
        self.assertIn("home-schedule-link", classes(schedule_link))
        self.assertEqual(
            schedule_link["attrs"].get("href"),
            "#today-calendar-panel",
        )

        disclosures = utility_row["children"]
        self.assertEqual([node["tag"] for node in disclosures], ["details", "details"])
        summaries = [
            next(
                child["text"].strip()
                for child in disclosure["children"]
                if child["tag"] == "summary"
            )
            for disclosure in disclosures
        ]
        self.assertEqual(summaries, ["Quick add", "Completed work"])

        footer_css = CSS[
            CSS.index(":root[data-ui-shell='emerald'] .home-panel-footer {")
            : CSS.index(":root[data-ui-shell='emerald'] .home-utility-disclosure {")
        ]
        self.assertIn("flex-direction: column", footer_css)
        self.assertIn(".home-panel-utility-row", footer_css)

    def test_operational_focus_prioritizes_today_and_reports_real_completion(self):
        focus = self.app_block("function renderFocusTasks", "function dueTaskReminders")
        self.assertIn("task.planned_for_today", focus)
        self.assertIn("manual_rank", focus)
        self.assertIn("const completedPlanned", focus)
        self.assertIn("completedPlanned.length / plannedTotal", focus)
        self.assertIn("artifactAttention", focus)
        self.assertIn("[...artifactAttention, ...focusSource]", focus)
        self.assertIn(".slice(0, 3)", focus)
        self.assertIn("data-focus-task-id", focus)
        self.assertIn("aria-valuenow", focus)
        self.assertIn("aria-label", focus)

    def test_live_agents_are_canonical_profiles_annotated_by_observations_and_runs(self):
        presentation = self.app_block(
            "function homeAgentObservation",
            "function renderHomeProjects",
        )
        renderer = self.app_block(
            "function renderHomeLiveAgents",
            "function renderHomeProjects",
        )
        self.assertIn("state.agentConsoleAgents", renderer)
        self.assertIn("state.agents", presentation)
        self.assertIn("currentAgentConsoleRuns()", presentation)
        self.assertIn("agentConsoleRunIsActive", presentation)
        self.assertIn("latestRun?.action_required?.kind", presentation)
        self.assertIn("['failed', 'blocked', 'error']", presentation)
        for status in ("Needs attention", "Working", "Ready", "Unavailable"):
            self.assertIn(status, presentation)
        self.assertIn("runs.map((run) => run.session_id).filter(Boolean)", presentation)
        self.assertIn("const toneRank", renderer)
        self.assertIn("unavailable: 3", renderer)
        self.assertLess(renderer.index(".sort("), renderer.index(".slice(0, 3)"))
        self.assertIn("Last activity:", renderer)
        self.assertIn("Health:", renderer)
        self.assertNotIn("researcher", renderer.lower())
        self.assertNotIn("analyst", renderer.lower())

    def test_console_active_states_and_home_runs_are_connection_bound(self):
        helpers = self.app_block(
            "const agentConsoleActiveStatuses",
            "function agentConsoleEventCursor",
        )
        for status in (
            "queued",
            "running",
            "cancelling",
            "waiting_for_approval",
            "waiting_for_clarification",
        ):
            self.assertIn(status, helpers)
        self.assertIn("run.transport_mode", helpers)
        self.assertIn("run.connection_binding_id", helpers)
        self.assertIn("state.agentConsoleTransportBinding", helpers)
        console = self.app_block("function renderAgentConsole(payload", "function scheduleAgentConsolePoll")
        self.assertIn("runs.filter(agentConsoleRunMatchesCurrentBinding)", console)
        self.assertIn("waiting for approval", console)
        self.assertIn("waiting for clarification", console)

    def test_projects_use_supported_statuses_and_crons_remain_read_only(self):
        projects = self.app_block("function renderHomeProjects", "function renderHomeCrons")
        crons = self.app_block("function renderHomeCrons", "function renderHomeSchedule")
        for status in ("active", "paused", "archived"):
            self.assertIn(status, projects)
        self.assertIn("Tasks done", projects)
        self.assertIn("ordered.slice(0, 2)", crons)
        self.assertIn("job.enabled", crons)
        self.assertIn("Enabled", crons)
        self.assertIn("Disabled", crons)
        self.assertNotIn("triggerCron", crons)
        self.assertNotIn("previewCronTrigger", crons)
        self.assertNotIn("data-cron-trigger", crons)
        home_crons = INDEX[
            INDEX.index('id="home-crons-panel"')
            : INDEX.index('id="agent-console-panel"')
        ]
        self.assertIn("Read-only Hermes CRON inventory.", home_crons)
        self.assertNotIn("Run now", home_crons)
        self.assertNotIn("Queue", home_crons)

    def test_today_schedule_stays_on_today_and_lays_out_all_valid_events(self):
        schedule = self.app_block("function homeCalendarStatus", "function hasAttentionTag")
        self.assertIn("const selectedDate = today", schedule)
        self.assertIn("start < dayEnd && end > dayStart", schedule)
        self.assertNotIn("firstDate || today", schedule)
        self.assertIn("payload.summary?.stale", schedule)
        self.assertIn("payload.error", schedule)
        self.assertIn("const visualLaneEnds", schedule)
        self.assertIn("visualLaneEnds.findIndex((laneEnd) => laneEnd <= left)", schedule)
        self.assertIn("visualLaneEnds.push(right)", schedule)
        self.assertIn("--event-lane", schedule)
        self.assertIn("const tickStep", schedule)
        self.assertIn("Math.min(100 - width, naturalLeft)", schedule)
        self.assertNotIn("endHour = startHour + 12", schedule)

    def test_compact_console_places_visible_transcript_above_prompt(self):
        console = INDEX[
            INDEX.index('id="agent-console-panel"')
            : INDEX.index('id="view-agents"')
        ]
        for element_id in (
            "agent-console-agent",
            "agent-console-model-select",
            "agent-console-form",
            "agent-console-prompt",
            "agent-console-attach",
            "agent-console-stop",
            "agent-console-state",
            "agent-console-form-status",
            "agent-console-provider-select",
            "agent-console-new-session",
            "agent-console-tool-toggle",
            "agent-console-chat",
        ):
            self.assertEqual(console.count(f'id="{element_id}"'), 1, element_id)
        self.assertEqual(console.count("agent-console-send"), 1)
        transcript_start = console.index('id="agent-console-transcript"')
        runtime_row = console[
            console.index('<div class="agent-console-runtime-row">')
            : transcript_start
        ]
        self.assertLess(runtime_row.index('id="agent-console-agent"'), runtime_row.index('id="agent-console-provider-select"'))
        self.assertLess(runtime_row.index('id="agent-console-provider-select"'), runtime_row.index('id="agent-console-model-select"'))
        self.assertLess(console.index('id="agent-console-provider-select"'), transcript_start)
        self.assertLess(console.index('id="agent-console-model-select"'), transcript_start)
        self.assertLess(transcript_start, console.index('id="agent-console-chat"'))
        self.assertLess(console.index('id="agent-console-chat"'), console.index('id="agent-console-form"'))
        self.assertNotIn('id="agent-console-details"', console)
        self.assertNotIn("<summary>Console history</summary>", console)
        self.assertNotIn('id="agent-console-runtime-banner"', console)
        self.assertNotIn('id="agent-console-apply-model"', console)

    def test_home_grid_matches_reference_and_stacks_in_reading_order(self):
        operations = CSS[
            CSS.index("/* Reference-aligned Mentat Home")
            : CSS.index("@media (min-width: 901px)", CSS.index("/* Reference-aligned Mentat Home"))
        ]
        self.assertIn("minmax(420px, 1.174fr) minmax(360px, 1fr)", operations)
        self.assertIn('"focus agents"', operations)
        self.assertIn('"schedule context"', operations)
        self.assertIn('"console console"', operations)
        responsive = CSS[
            CSS.index("@media (max-width: 900px)", CSS.index("/* Reference-aligned Mentat Home"))
            : CSS.index("@media (max-width: 640px)", CSS.index("/* Reference-aligned Mentat Home"))
        ]
        for area in ('"focus"', '"agents"', '"schedule"', '"context"', '"console"'):
            self.assertIn(area, responsive)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", responsive)
        self.assertNotIn("Classic remains a functional visual rollback", CSS)
        self.assertNotIn("data-ui-shell='classic'", CSS)
        phone = CSS[
            CSS.index("@media (max-width: 640px)", CSS.index("/* Reference-aligned Mentat Home"))
            :
        ]
        self.assertIn(".home-schedule-event", phone)
        self.assertIn("max-width: none", phone)

    def test_mobile_agent_console_does_not_reserve_retired_history_rows(self):
        mobile = CSS[
            CSS.index("@media (max-width: 760px)")
            : CSS.index("@media (max-width: 640px)", CSS.index("@media (max-width: 760px)"))
        ]
        console = mobile[
            mobile.index(".agent-console {")
            : mobile.index(".agent-console-toolbar")
        ]
        self.assertIn("grid-template-rows: auto", console)
        self.assertNotIn("300px", console)

    def test_home_disclosures_are_panel_bounded_when_open(self):
        operations = CSS[
            CSS.index("/* Reference-aligned Mentat Home")
            : CSS.index("@media (min-width: 901px)", CSS.index("/* Reference-aligned Mentat Home"))
        ]
        self.assertIn(".home-utility-disclosure[open]", operations)
        self.assertIn("flex: 1 0 100%", operations)
        self.assertIn("width: 100%", operations)
        self.assertIn("min-width: 0", operations)
        self.assertNotIn("min-width: min(560px", operations)

    def test_polling_lists_do_not_announce_whole_dashboard_replacements(self):
        home_agents = INDEX[
            INDEX.index('id="home-live-agent-list"')
            : INDEX.index('id="agent-activity-panel"')
        ]
        self.assertNotIn('aria-live=', home_agents)
        progress = INDEX[
            INDEX.index('id="home-focus-completion-ring"') - 180
            : INDEX.index('id="home-focus-completion-ring"') + 400
        ]
        self.assertIn('role="progressbar"', progress)
        self.assertIn('aria-valuenow="0"', progress)


if __name__ == "__main__":
    unittest.main()
