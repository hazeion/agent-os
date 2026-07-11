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
        self.assertIn("managed-agent-card", STYLES)

    def test_skill_picker_supports_default_custom_and_none_modes(self):
        self.assertIn('name="skill_mode" value="default"', INDEX)
        self.assertIn('name="skill_mode" value="custom"', INDEX)
        self.assertIn('name="skill_mode" value="none"', INDEX)
        self.assertIn('id="agent-creator-skill-search"', INDEX)
        self.assertIn("renderAgentCreatorSkills", APP_JS)
        self.assertIn("enabled_builtin_skills", APP_JS)
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


if __name__ == "__main__":
    unittest.main()
