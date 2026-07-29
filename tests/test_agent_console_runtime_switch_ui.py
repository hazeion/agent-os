import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")


class AgentConsoleRuntimeSwitchUiTests(unittest.TestCase):
    def app_block(self, start, end):
        start_index = APP.index(start)
        return APP[start_index:APP.index(end, start_index)]

    def test_runtime_controls_share_one_row_before_the_prompt(self):
        console = INDEX[
            INDEX.index('id="agent-console-panel"')
            : INDEX.index('id="view-agents"')
        ]
        runtime = console[
            console.index('<div class="agent-console-runtime-row">')
            : console.index('<form id="agent-console-form"')
        ]
        ids = (
            'id="agent-console-agent"',
            'id="agent-console-provider-select"',
            'id="agent-console-model-select"',
        )
        self.assertTrue(all(item in runtime for item in ids))
        self.assertLess(runtime.index(ids[0]), runtime.index(ids[1]))
        self.assertLess(runtime.index(ids[1]), runtime.index(ids[2]))
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", CSS)

    def test_provider_and_model_changes_apply_automatically(self):
        handlers = self.app_block(
            "$('#agent-console-model-select')?.addEventListener",
            "$('[data-provider-switch-confirm]')?.addEventListener",
        )
        provider_handler = handlers[
            handlers.index("$('#agent-console-provider-select')")
            : handlers.index("$('#agent-console-tool-toggle')")
        ]
        self.assertIn("provider.models[0]", provider_handler)
        self.assertIn("await applyAgentConsoleRuntimeSelection({", provider_handler)
        self.assertIn("model: state.agentConsoleSelectedModel", provider_handler)
        model_handler = handlers[:handlers.index("$('#agent-console-provider-select')")]
        self.assertIn("await applyAgentConsoleRuntimeSelection({", model_handler)
        self.assertNotIn("agent-console-apply-model", INDEX)

    def test_automatic_apply_keeps_preview_confirmation_and_failure_refresh(self):
        apply_block = self.app_block(
            "async function applyAgentConsoleRuntimeSelection",
            "async function confirmAgentConsoleProviderSwitch",
        )
        self.assertLess(
            apply_block.index("await previewAgentConsoleProvider("),
            apply_block.index("await switchAgentConsoleProvider("),
        )
        self.assertIn("preview.confirmation_id", apply_block)
        self.assertEqual(apply_block.count("await switchAgentConsoleProvider("), 1)
        self.assertIn("state.agentConsoleRuntimeMutationInFlight = true", apply_block)
        self.assertIn("state.agentConsoleRuntimeMutationInFlight = false", apply_block)
        self.assertIn("state.agentConsoleRuntimePending = {", apply_block)
        self.assertIn("const transportBinding = state.agentConsoleTransportBinding", apply_block)
        self.assertGreaterEqual(
            apply_block.count("transportBinding !== state.agentConsoleTransportBinding"),
            3,
        )
        self.assertGreaterEqual(
            apply_block.count("mutationGeneration !== state.agentConsoleRuntimeMutationGeneration"),
            4,
        )
        self.assertIn("state.agentConsoleSelectedProvider = ''", apply_block)
        self.assertIn("await refreshAgentConsoleModelCatalog({ agentId, silent: true })", apply_block)
        self.assertIn("clearAgentConsoleRuntimeForInspection(agentId)", apply_block)
        self.assertIn("state.agentConsoleRuntimeUnresolved = true", apply_block)
        self.assertIn("applyAgentConsoleRuntimePayload(payload, { addNotice: true })", apply_block)

    def test_confirmed_runtime_is_separate_from_selectable_inventory_and_pending_target(self):
        render = self.app_block("function renderAgentConsole(payload = {})", "function scheduleAgentConsolePoll")
        self.assertIn("incomingCatalog.profile_id === selectedAgentId", render)
        self.assertIn("incomingProviderInventory.profile_id === selectedAgentId", render)
        self.assertNotIn("state.agentConsoleRuntimeLoading = false", render)
        self.assertIn("if (transportChanged)", render)
        self.assertIn("void refreshAgentConsoleModelCatalog({", render)
        self.assertIn("requireReadable: true", render)
        refresh = self.app_block(
            "async function refreshAgentConsoleModelCatalog",
            "function clearAgentConsoleRuntimeForInspection",
        )
        self.assertIn("requireReadable = false", refresh)
        self.assertIn("requireReadable && !agentConsoleReadableRuntime", refresh)
        self.assertGreaterEqual(
            refresh.count("state.agentConsoleRuntimeUnresolved = true"),
            2,
        )
        self.assertIn("const confirmedProvider =", render)
        self.assertIn("const confirmedModel =", render)
        self.assertIn("currentProviderOutsideInventory", render)
        self.assertIn("confirmed_only: true", render)
        self.assertIn("state.agentConsoleRuntimePending", render)
        self.assertIn("switching to ${pendingRuntime.provider}", render)

    def test_unverified_runtime_blocks_execution_until_explicit_retry(self):
        render = self.app_block("function renderAgentConsole(payload = {})", "function scheduleAgentConsolePoll")
        self.assertIn("const runtimeBlocked = agentConsoleRuntimeBlocked()", render)
        self.assertIn("if (prompt) prompt.disabled", render)
        self.assertIn("if (send) send.disabled", render)
        self.assertIn("if (attach) attach.disabled", render)
        self.assertIn("runtimeRefresh.hidden = !state.agentConsoleRuntimeUnresolved", render)
        self.assertIn('id="agent-console-runtime-refresh"', INDEX)
        retry = self.app_block(
            "$('#agent-console-runtime-refresh')?.addEventListener",
            "$('[data-provider-switch-confirm]')?.addEventListener",
        )
        self.assertIn("const refreshPromise = refreshAgentConsoleModelCatalog", retry)
        self.assertIn("const refreshed = await refreshPromise", retry)
        self.assertNotIn("switchAgentConsoleProvider", retry)
        workspace_attachment = self.app_block(
            "async function addAgentConsoleWorkspaceFile",
            "async function addAgentConsoleFiles",
        )
        upload_attachment = self.app_block(
            "async function addAgentConsoleFiles",
            "function agentConsoleOutstandingToolCount",
        )
        self.assertIn("agentConsoleRuntimeBlocked()", workspace_attachment)
        self.assertIn("agentConsoleRuntimeBlocked()", upload_attachment)
        self.assertIn("const confirmedRuntime = agentConsoleConfirmedRuntime(", retry)
        confirmed = self.app_block(
            "function agentConsoleConfirmedRuntime",
            "async function refreshAgentConsoleModelCatalog",
        )
        self.assertIn("!provider", confirmed)
        self.assertIn("!model", confirmed)
        self.assertIn("String(inventory?.error || '').trim()", confirmed)
        readable = self.app_block(
            "function agentConsoleReadableRuntime",
            "async function refreshAgentConsoleModelCatalog",
        )
        self.assertIn("String(inventory?.error || '').trim()", readable)

    def test_context_pack_staging_is_serialized_with_runtime_changes(self):
        context = self.app_block(
            "async function applyContextPackToConsole",
            "function renderContextPackEditor",
        )
        self.assertIn("if (agentConsoleRuntimeBlocked())", context)
        self.assertIn("const transportBinding = state.agentConsoleTransportBinding", context)
        self.assertIn("transportBinding !== state.agentConsoleTransportBinding", context)
        self.assertIn("agentId !== state.agentConsoleSelectedAgentId", context)
        apply_block = self.app_block(
            "async function applyAgentConsoleRuntimeSelection",
            "async function confirmAgentConsoleProviderSwitch",
        )
        self.assertIn("state.agentConsoleAttachmentsUploading", apply_block)

    def test_agent_change_refreshes_without_switching(self):
        handler = self.app_block(
            "$('#agent-console-agent')?.addEventListener",
            "$('#agent-console-model-select')?.addEventListener",
        )
        self.assertIn("const refreshPromise = refreshAgentConsoleModelCatalog", handler)
        self.assertIn("const refreshed = await refreshPromise", handler)
        self.assertIn("const transportBinding = state.agentConsoleTransportBinding", handler)
        self.assertIn("const requestGeneration = state.agentConsoleRuntimeRequestGeneration", handler)
        self.assertIn("requestGeneration !== state.agentConsoleRuntimeRequestGeneration", handler)
        self.assertIn("confirmed by Hermes", handler)
        self.assertNotIn("applyAgentConsoleRuntimeSelection", handler)
        self.assertNotIn("switchAgentConsoleProvider", handler)

    def test_profile_navigation_and_retry_fail_closed_around_fresh_reads(self):
        navigation = self.app_block(
            "async function useHermesProfileInConsole",
            "async function testHermesProfile",
        )
        self.assertLess(
            navigation.index("state.agentConsoleRuntimeLoading = true"),
            navigation.index("await setView('today', { refreshOnChange: false })"),
        )
        self.assertIn("state.agentConsoleRuntimeUnresolved = true", navigation)
        self.assertIn("clearAgentConsoleRuntimeForInspection(requestedProfileId)", navigation)
        self.assertIn("requestGeneration !== state.agentConsoleRuntimeRequestGeneration", navigation)
        retry = self.app_block(
            "$('#agent-console-runtime-refresh')?.addEventListener",
            "$('[data-provider-switch-confirm]')?.addEventListener",
        )
        self.assertIn("const requestedAgentId = state.agentConsoleSelectedAgentId", retry)
        self.assertIn("const transportBinding = state.agentConsoleTransportBinding", retry)
        self.assertIn("requestGeneration !== state.agentConsoleRuntimeRequestGeneration", retry)

    def test_tool_details_default_hidden_with_toggle_and_activity_summary(self):
        self.assertIn("agentConsoleShowTools: false", CORE)
        self.assertIn('id="agent-console-tool-toggle" aria-pressed="false">Show tools</button>', INDEX)
        render = self.app_block("function renderAgentConsole(payload = {})", "function scheduleAgentConsolePoll")
        self.assertIn("eventType.startsWith('tool.') && !state.agentConsoleShowTools", render)
        self.assertIn("agentConsoleOutstandingToolCount(run.events || []) > 0", render)
        self.assertIn("toolActivityBanner.hidden = !toolActivityActive || state.agentConsoleShowTools", render)
        self.assertIn("`${toolAgentName} is using tools`", render)
        self.assertIn("toolToggle.setAttribute('aria-pressed'", render)
        self.assertIn('id="agent-console-tool-activity-banner"', INDEX)
        self.assertIn('id="agent-console-tool-live-status"', INDEX)
        self.assertIn("toolActivityContext !== state.agentConsoleToolActivityContext", render)
        self.assertIn("toolActivityActive !== state.agentConsoleToolActivityActive", render)
        self.assertNotIn('class="agent-console-log-row agent-console-tool-activity" role="status"', render)
        self.assertIn("@keyframes agent-console-tool-dots", CSS)
        self.assertIn('content: "..";', CSS)
        self.assertIn('content: "...";', CSS)

    def test_verified_switch_notice_is_browser_only(self):
        notice = self.app_block(
            "function addAgentConsoleRuntimeNotice",
            "function renderAgentConsole(payload = {})",
        )
        self.assertIn("state.agentConsoleRuntimeNotices", notice)
        self.assertIn("transport_binding: state.agentConsoleTransportBinding", notice)
        render = self.app_block("function renderAgentConsole(payload = {})", "function scheduleAgentConsolePoll")
        self.assertIn("agent-console-runtime-notice", render)
        self.assertIn("agent-console-runtime-banner", INDEX)
        self.assertIn("(notice.transport_binding || '') === (state.agentConsoleTransportBinding || '')", render)
        self.assertIn(".sort((left, right) => left.timestamp - right.timestamp)", render)
        self.assertIn("Switched to", render)
        self.assertNotIn('agent-console-runtime-notice" role="status"', render)
        self.assertNotIn("startAgentConsoleRun", notice)

    def test_history_toolbar_is_not_a_second_runtime_editor(self):
        console = INDEX[
            INDEX.index('id="agent-console-panel"')
            : INDEX.index('id="view-agents"')
        ]
        details = console[console.index('id="agent-console-details"'):]
        self.assertIn("<summary>Console history</summary>", details)
        self.assertIn('id="agent-console-new-session"', details)
        self.assertIn('id="agent-console-tool-toggle"', details)
        self.assertNotIn('id="agent-console-provider-select"', details)
        self.assertNotIn("Review change", details)


if __name__ == "__main__":
    unittest.main()
