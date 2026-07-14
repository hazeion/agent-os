from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE_JS = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
STYLES = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")


class AgentCreatorUiTests(unittest.TestCase):
    def test_agents_view_opens_three_step_creator(self):
        self.assertIn('id="create-agent-button"', INDEX)
        self.assertIn('id="managed-agent-list"', INDEX)
        self.assertIn('id="agent-creator-dialog"', INDEX)
        self.assertIn('data-agent-creator-progress="details"', INDEX)
        self.assertIn('data-agent-creator-progress="configuration"', INDEX)
        self.assertIn('data-agent-creator-progress="review"', INDEX)
        self.assertIn("async function openAgentCreator()", APP_JS)
        self.assertIn("async function previewAgentCreator()", APP_JS)
        self.assertIn("async function submitAgentCreator()", APP_JS)

    def test_managed_agents_render_and_refresh_after_creation(self):
        self.assertIn("function renderHermesProfiles", APP_JS)
        self.assertIn("requests.hermesProfiles = fetchHermesProfiles()", APP_JS)
        self.assertIn("renderHermesProfiles(result.profiles)", APP_JS)
        self.assertIn("data-agent-creator-view-agents", APP_JS)
        self.assertIn("managed-agent-layout", STYLES)
        self.assertIn("managed-agent-row", STYLES)

    def test_panel_action_buttons_stay_in_compact_edge_aligned_groups(self):
        managed_actions = STYLES[
            STYLES.index(".managed-agent-detail-actions {") : STYLES.index(".managed-agent-delete")
        ]
        creator_actions = STYLES[
            STYLES.index(".agent-creator-actions > div {") : STYLES.index("@media (max-width: 760px)", STYLES.index(".agent-creator-actions > div {"))
        ]

        self.assertIn("justify-content: flex-start", managed_actions)
        self.assertIn("flex-wrap: wrap", managed_actions)
        self.assertNotIn("justify-content: space-between", managed_actions)
        self.assertIn("justify-content: flex-end", creator_actions)
        self.assertIn("margin-left: auto", creator_actions)

    def test_managed_agents_can_preview_and_confirm_runtime_identity(self):
        self.assertIn('id="agent-identity-dialog"', INDEX)
        self.assertIn("managedAgentIdentities", CORE_JS)
        self.assertIn("fetchHermesProfileIdentity", CORE_JS)
        self.assertIn("previewHermesProfileIdentity", CORE_JS)
        self.assertIn("updateHermesProfileIdentity", CORE_JS)
        self.assertIn("async function loadManagedAgentIdentity", APP_JS)
        self.assertIn("async function openAgentIdentityReview", APP_JS)
        self.assertIn("async function submitAgentIdentityUpdate", APP_JS)
        self.assertIn("Identity synchronized", APP_JS)
        self.assertIn("managed-agent-identity-editor", STYLES)

    def test_identity_check_does_not_supply_the_expected_profile_id(self):
        start = APP_JS.index("async function testHermesProfile")
        block = APP_JS[start:APP_JS.index("async function assignFirstTaskToProfile", start)]
        self.assertIn("without relying on this message", block)
        self.assertNotIn("selected Hermes profile id", block)

    def test_blank_agents_can_choose_an_authenticated_provider(self):
        self.assertIn('id="managed-agent-provider-select"', APP_JS)
        self.assertIn('id="managed-agent-model-select"', APP_JS)
        self.assertIn("async function loadManagedAgentProviderInventory", APP_JS)
        self.assertIn("async function reviewManagedAgentProvider", APP_JS)
        self.assertIn("await loadManagedAgentProviderInventory(state.selectedHermesProfileId)", APP_JS)
        self.assertIn("No provider is assigned", APP_JS)
        self.assertIn("managed-agent-provider-editor", STYLES)

    def test_provider_and_model_controls_wrap_without_overlap(self):
        toolbar_rule = STYLES[STYLES.index(".agent-console-toolbar"):STYLES.index(".agent-console-select-shell")]
        self.assertIn("flex-wrap: wrap", toolbar_rule)
        self.assertIn("flex: 1 1 210px", STYLES)

    def test_skill_picker_supports_default_custom_and_none_modes(self):
        self.assertIn('name="skill_mode" value="default"', INDEX)
        self.assertIn('name="skill_mode" value="custom"', INDEX)
        self.assertIn('name="skill_mode" value="none"', INDEX)
        self.assertIn('id="agent-creator-skill-search"', INDEX)
        self.assertIn("renderAgentCreatorSkills", APP_JS)
        self.assertIn("enabled_builtin_skills", APP_JS)
        self.assertIn("enabled_builtin_skill_count", APP_JS)
        self.assertIn("agent-creator-skill-list", STYLES)

    def test_creator_uses_profile_preview_and_skill_catalog_endpoints(self):
        self.assertIn("hermesProfiles: '/api/hermes/profiles'", CORE_JS)
        self.assertIn("hermesSkillCatalog: '/api/hermes/skills/catalog'", CORE_JS)
        self.assertIn("previewHermesProfile", CORE_JS)
        self.assertIn("createHermesProfile", CORE_JS)
        self.assertIn('"/api/hermes/skills/catalog": hermes_skill_catalog_payload', SERVER)
        self.assertIn(r'^/api/hermes/profiles/preview$', SERVER)

    def test_review_and_confirmation_are_required_before_creation(self):
        self.assertIn("requires_confirmation", (ROOT / "hermes_profile_creation.py").read_text(encoding="utf-8"))
        self.assertIn("confirmation_id: preview.confirmation_id", APP_JS)
        self.assertIn("Review the exact effects", APP_JS)
        self.assertIn("shell-free Hermes profile operation", APP_JS)

    def test_review_step_hides_redundant_continue_control(self):
        self.assertIn("if (next) next.hidden = step === 'review';", APP_JS)
        self.assertIn(".agent-creator-actions [hidden]", STYLES)

    def test_agent_creation_and_managed_profile_surfaces_do_not_use_pills(self):
        creator = INDEX[
            INDEX.index('id="agent-creator-dialog"') : INDEX.index("</dialog>", INDEX.index('id="agent-creator-dialog"'))
        ]
        managed_profiles = APP_JS[
            APP_JS.index("function renderHermesProfiles") : APP_JS.index("function renderAgentCreatorSkills")
        ]
        progress = STYLES[
            STYLES.index(".agent-creator-progress li {") : STYLES.index(".agent-creator-body")
        ]

        self.assertNotIn('class="pill', creator)
        self.assertNotIn('class="pill', managed_profiles)
        self.assertIn("background: transparent", progress)
        self.assertNotIn("border-radius", progress)

    def test_managed_agents_offer_capability_gated_confirmed_deletion(self):
        self.assertIn('id="agent-delete-dialog"', INDEX)
        self.assertIn("state.hermesProfileCapabilities['profiles.delete'] === true", APP_JS)
        self.assertIn("!selectedProfile.is_default", APP_JS)
        self.assertIn("selectedProfile.id !== activeProfile", APP_JS)
        self.assertIn("state.agentConsoleRuns.some(agentConsoleRunIsActive)", APP_JS)
        self.assertIn("data-delete-hermes-profile", APP_JS)
        self.assertIn("async function openAgentDeletion", APP_JS)
        self.assertIn("async function submitAgentDeletion", APP_JS)
        self.assertIn("previewHermesProfileDeletion", CORE_JS)
        self.assertIn("deleteHermesProfile", CORE_JS)
        self.assertIn("renderHermesProfiles(refreshed)", APP_JS)
        self.assertIn("Keep the profile row and confirmation open", APP_JS)


if __name__ == "__main__":
    unittest.main()
