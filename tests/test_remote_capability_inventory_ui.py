from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CORE_JS = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")


class RemoteCapabilityInventoryUiTests(unittest.TestCase):
    def test_settings_loads_and_renders_read_only_capability_inventory(self):
        self.assertIn("hermesCapabilities: '/api/hermes/capabilities'", CORE_JS)
        self.assertIn('requests.hermesCapabilities = api(endpoints.hermesCapabilities)', APP_JS)
        self.assertIn("renderHermesCapabilityInventory", APP_JS)
        self.assertIn('id="hermes-capability-summary"', INDEX_HTML)
        self.assertIn("This view is read-only.", INDEX_HTML)
        self.assertIn('"/api/hermes/capabilities": hermes_capability_inventory_payload', SERVER)

    def test_inventory_escapes_metadata_and_omits_tool_names_and_actions(self):
        start = APP_JS.index("function renderHermesCapabilityInventory")
        end = APP_JS.index("function renderConfig", start)
        renderer = APP_JS[start:end]
        for field in ("skill.name", "toolset.name"):
            self.assertIn(f"escapeHtml({field}", renderer)
        self.assertIn("toolset.tool_count", renderer)
        self.assertNotIn("toolset.tools", renderer)
        self.assertNotIn("skill.category", renderer)
        self.assertNotIn("toolset.label", renderer)
        self.assertNotIn("skill.description", renderer)
        self.assertNotIn("toolset.description", renderer)
        self.assertNotIn("configured", renderer)
        self.assertNotIn("<button", renderer)
        self.assertIn("#hermes-capability-summary .item-title span:first-child", STYLES)
        self.assertIn("overflow-wrap: anywhere", STYLES)
        self.assertIn("#hermes-capability-summary details .item-title", STYLES)
        self.assertIn("white-space: normal", STYLES)

    def test_runtime_copy_covers_local_and_remote_without_changing_readme(self):
        self.assertIn("<h2>Hermes Runtime</h2>", INDEX_HTML)
        self.assertIn("selected local or remote Hermes connection", INDEX_HTML)
        self.assertIn("Loading Hermes capabilities", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
