from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")


class TaskDelegationUiTests(unittest.TestCase):
    def test_selected_task_offers_confirmed_delegation(self):
        self.assertIn('id="selected-task-delegate"', INDEX)
        self.assertIn('id="task-delegation-dialog"', INDEX)
        self.assertIn('id="task-delegation-review"', INDEX)
        self.assertIn('data-task-delegation-preview', INDEX)
        self.assertIn('data-task-delegation-confirm', INDEX)
        self.assertIn("async function reviewTaskDelegation()", APP)
        self.assertIn("async function submitTaskDelegation()", APP)
        self.assertIn("previewTaskDelegation", CORE)
        self.assertIn("confirmation_id", CORE)

    def test_task_inspector_exposes_linked_run_and_review_actions(self):
        self.assertIn("task-delegation-card", APP)
        self.assertIn('data-delegation-action="accept"', APP)
        self.assertIn('data-delegation-action="request_revision"', APP)
        self.assertIn('data-delegation-action="reply"', APP)
        self.assertIn('data-delegation-action="retry"', APP)
        self.assertIn('data-delegation-action="stop"', APP)
        self.assertIn("refreshTaskDelegation", CORE)
        self.assertIn("runTaskDelegationAction", CORE)

    def test_generated_files_are_available_in_task_and_home_views(self):
        self.assertIn("delegationArtifacts", APP)
        self.assertIn(
            "agentConsoleArtifactCards(delegationArtifacts, { embedImages: false })",
            APP,
        )
        focus = APP[APP.index("function renderFocusTasks") : APP.index("function dueTaskReminders")]
        self.assertIn("task.delegation?.artifacts", focus)
        self.assertIn(
            "agentConsoleArtifactCards(artifacts, { compact: true, embedImages: false })",
            focus,
        )
        task_area = APP[APP.index("function taskArea") : APP.index("function taskTone")]
        self.assertIn("task.delegation?.state === 'ready_for_review'", task_area)
        self.assertIn("task.delegation.artifacts.length", task_area)
        self.assertLess(
            task_area.index("task.needs_attention"),
            task_area.index("status === 'in progress'"),
        )
        self.assertIn('aria-label="Download ${escapeHtml(name)}"', APP)
        self.assertIn("home-focus-item", focus)
        self.assertIn("task.delegation?.state === 'ready_for_review'", APP)
        self.assertIn("task.delegation.artifacts.length", APP)
        self.assertIn(".agent-console-artifacts.compact", CSS)
        self.assertIn(".task-artifact-notice", CSS)

    def test_home_renders_local_data_before_remote_delegation_refresh(self):
        refresh = APP[
            APP.index("async function refresh()")
            : APP.index("async function runMessageSearchRequest")
        ]
        local_fetch = refresh.index("const requests = {")
        core_render = refresh.index("renderRefreshCore(coreData, { activeView });")
        deferred_render = refresh.index("renderRefreshDeferred({ [key]: await promise }")
        remote_refresh = refresh.index("void refreshHomeDelegations()")
        self.assertLess(local_fetch, core_render)
        self.assertLess(core_render, deferred_render)
        self.assertLess(deferred_render, remote_refresh)
        self.assertIn("projects: requests.projects", refresh)
        self.assertNotIn("overview: requests.overview", refresh[refresh.index("const coreRequests"):deferred_render])
        self.assertIn("Promise.allSettled", refresh)
        self.assertIn("renderRefreshFailure(key, error", refresh)
        self.assertIn("function renderRefreshCore", APP)
        self.assertIn("function renderRefreshDeferred", APP)
        self.assertIn("window.__MENTAT_HOME_CORE_READY__ = true", APP)
        self.assertIn("performance.mark('mentat-home-core-rendered')", APP)
        self.assertIn("homeDelegationRefreshInFlight", CORE)
        self.assertIn("latestAgentsPayload", CORE)
        self.assertIn("if (viewChanged && refreshOnChange) return refresh();", APP)
        failure_render = APP[
            APP.index("function renderRefreshFailure")
            : APP.index("async function refresh()")
        ]
        for key in ("'tasks'", "'projects'", "'agentActivity'", "'sessions'", "'agentConsole'", "'contextPacks'"):
            self.assertIn(key, failure_render)
        self.assertIn("state.latestSessionsPayload = null;", failure_render)
        self.assertIn("state.latestAgentsPayload = null;", failure_render)
        self.assertIn("const refreshedTasks = (await api(endpoints.tasks)).tasks", refresh)
        self.assertIn("renderFocusTasks(refreshedTasks)", refresh)

    def test_today_has_agent_activity_and_review_inbox(self):
        self.assertIn('id="agent-activity-panel"', INDEX)
        self.assertIn('id="agent-activity-list"', INDEX)
        self.assertIn("function renderAgentActivity", APP)
        self.assertIn("needs_input", APP)
        self.assertIn("ready_for_review", APP)
        self.assertIn("endpoints.agentActivity", APP)
        self.assertIn(".agent-activity-list", CSS)

    def test_delegation_actions_form_a_compact_left_aligned_group(self):
        actions = CSS[
            CSS.index(".task-delegation-actions {") : CSS.index(".delegation-context-preview")
        ]
        self.assertIn("justify-content: flex-start", actions)
        self.assertIn("flex-wrap: wrap", actions)
        self.assertNotIn("justify-content: space-between", actions)


if __name__ == "__main__":
    unittest.main()
