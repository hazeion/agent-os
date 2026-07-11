from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
STYLES_CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")


class FrontendWorkflowFeedbackTests(unittest.TestCase):
    def test_unsupported_provider_switch_keeps_agent_execution_ready(self):
        render_start = APP_JS.index("function renderAgentConsole(payload = {})")
        render_end = APP_JS.index("function scheduleAgentConsolePoll", render_start)
        render_block = APP_JS[render_start:render_end]

        self.assertIn("provider switching unsupported by this Hermes runtime", render_block)
        self.assertIn("Agent execution remains available with the current provider and model.", render_block)
        self.assertIn("if (prompt) prompt.disabled = !available || Boolean(activeRun);", render_block)
        self.assertIn("if (send) send.disabled = !available || Boolean(activeRun);", render_block)
        self.assertNotIn(
            "if (send) send.disabled = !available || !providerSwitchAvailable",
            render_block,
        )

    def test_cron_queue_success_is_preserved_on_the_refreshed_card(self):
        render_start = APP_JS.index("function renderCrons(payload = {})")
        render_end = APP_JS.index("function sessionMatches", render_start)
        render_block = APP_JS[render_start:render_end]

        self.assertIn("job.next_run ? ` · next ${humanDate(job.next_run)}`", render_block)
        self.assertIn("state.cronTriggerFeedback?.jobId === job.id", render_block)
        self.assertIn('class="item-meta mono" role="status"', render_block)
        self.assertIn("state.cronTriggerFeedback = {", render_block)
        self.assertIn("result.message", render_block)

    def test_cron_queue_controls_fail_closed_without_atomic_runtime_capability(self):
        render_start = APP_JS.index("function renderCrons(payload = {})")
        render_end = APP_JS.index("function sessionMatches", render_start)
        render_block = APP_JS[render_start:render_end]

        self.assertIn("payload.capabilities?.['crons.queue_enabled'] === true", render_block)
        self.assertIn("const triggerBlocked = !queueAvailable || consoleBusy || !job.enabled;", render_block)
        self.assertIn("does not expose a safe atomic cron queue operation", render_block)
        self.assertIn("payload.queue_error", render_block)

    def test_managed_profile_console_handoff_reports_load_failures(self):
        helper_start = APP_JS.index("async function useHermesProfileInConsole")
        helper_end = APP_JS.index("function sessionMatches", helper_start)
        helper_block = APP_JS[helper_start:helper_end]

        self.assertIn("const consolePayload = await api(endpoints.agentConsole);", helper_block)
        self.assertIn("agent.id === requestedProfileId", helper_block)
        self.assertIn("state.agentConsoleSelectedAgentId !== requestedProfileId", helper_block)
        self.assertIn("const catalog = await refreshAgentConsoleModelCatalog", helper_block)
        self.assertIn("if (!catalog)", helper_block)
        self.assertIn("Could not open ${requestedProfileId} in Agent Console", helper_block)
        self.assertIn("return false;", helper_block)
        self.assertIn(
            "await useHermesProfileInConsole(useProfile.dataset.useHermesProfile || 'default');",
            APP_JS,
        )

    def test_settings_refresh_renders_the_public_safe_configuration_summary(self):
        refresh_start = APP_JS.index("async function refresh()")
        refresh_end = APP_JS.index("function queueMessageSearch", refresh_start)
        refresh_block = APP_JS[refresh_start:refresh_end]

        self.assertIn("requests.config = api(endpoints.config)", refresh_block)
        self.assertIn("renderIfChanged('config', data.config, renderConfig)", refresh_block)
        self.assertIn("public-safe Hermes configuration summary", INDEX_HTML)
        self.assertNotIn("load the masked Hermes config", INDEX_HTML)

    def test_compact_navigation_keeps_descriptive_accessible_names(self):
        for label in (
            "Today View",
            "Agents / Sessions",
            "Calendar",
            "Projects / Tasks",
            "Notes",
            "Settings",
        ):
            self.assertIn(f'aria-label="{label}"', INDEX_HTML)

    def test_delete_previews_ignore_cancelled_or_superseded_responses(self):
        task_start = APP_JS.index("function closeTaskDeletion()")
        task_end = APP_JS.index("async function submitTaskDeletion", task_start)
        task_block = APP_JS[task_start:task_end]
        agent_start = APP_JS.index("function closeAgentDeletion()")
        agent_end = APP_JS.index("async function submitAgentDeletion", agent_start)
        agent_block = APP_JS[agent_start:agent_end]

        self.assertIn("state.taskDeletionRequestToken += 1", task_block)
        self.assertIn("const requestToken = ++state.taskDeletionRequestToken", task_block)
        self.assertIn("requestToken !== state.taskDeletionRequestToken || !dialog.open", task_block)
        self.assertIn("state.agentDeletionRequestToken += 1", agent_block)
        self.assertIn("const requestToken = ++state.agentDeletionRequestToken", agent_block)
        self.assertIn("requestToken !== state.agentDeletionRequestToken || !dialog.open", agent_block)
        self.assertGreaterEqual(
            agent_block.count("requestToken !== state.agentDeletionRequestToken || !dialog.open"),
            2,
        )
        self.assertIn("if (confirm) confirm.disabled = true", agent_block)

        stop_start = APP_JS.index("$('#agent-console-stop')?.addEventListener")
        stop_end = APP_JS.index("$('#project-scroll-left')", stop_start)
        stop_block = APP_JS[stop_start:stop_end]
        self.assertNotIn("requestToken", stop_block)
        self.assertIn("if (status) status.textContent = err.message", stop_block)

    def test_config_errors_render_before_missing_state(self):
        render_start = APP_JS.index("function renderConfig(payload = {})")
        render_end = APP_JS.index("function replayStatusTone", render_start)
        render_block = APP_JS[render_start:render_end]

        self.assertLess(render_block.index("if (payload.error)"), render_block.index("if (!payload.exists)"))

    def test_wrapped_header_removes_health_width_caps(self):
        breakpoint_start = STYLES_CSS.rindex("@media (max-width: 1120px)")
        breakpoint_end = STYLES_CSS.index("@media (max-width: 760px)", breakpoint_start)
        breakpoint_block = STYLES_CSS[breakpoint_start:breakpoint_end]

        self.assertIn(".sidebar-footer { width: 100%; max-width: none;", breakpoint_block)
        self.assertIn(".sidebar-footer #health-label { max-width: 100%; }", breakpoint_block)

    def test_model_command_uses_confirmed_provider_workflow_or_fails_closed(self):
        prompt_start = APP_JS.index("async function submitAgentConsolePrompt()")
        prompt_end = APP_JS.index("function renderCrons", prompt_start)
        prompt_block = APP_JS[prompt_start:prompt_end]

        self.assertIn("state.agentConsoleProviderInventory.capabilities?.['providers.switch'] === true", prompt_block)
        self.assertIn("Choose Review Change to preview and confirm", prompt_block)
        self.assertIn("does not expose supported provider/model switching", prompt_block)
        self.assertNotIn("Apply Model to update Hermes", prompt_block)


if __name__ == "__main__":
    unittest.main()
