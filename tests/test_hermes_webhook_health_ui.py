from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CORE = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
STYLES = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")


class HermesWebhookHealthUiTests(unittest.TestCase):
    def test_settings_alone_loads_the_dedicated_health_endpoint(self):
        self.assertIn("hermesWebhookHealth: '/api/hermes/webhooks/health'", CORE)
        self.assertIn("hermesWebhookProbe: '/api/hermes/webhooks/probe'", CORE)
        settings_start = APP.index("if (activeView === 'settings') {")
        settings_end = APP.index("\n  }", settings_start)
        settings_requests = APP[settings_start:settings_end]
        self.assertIn("requests.hermesWebhookHealth = fetchHermesWebhookHealth()", settings_requests)
        self.assertNotIn("requests.hermesWebhookHealth", APP[:settings_start])
        self.assertIn('"/api/hermes/webhooks/health": hermes_webhook_health_payload', SERVER)

    def test_health_panel_has_compact_actions_and_accessible_feedback(self):
        capabilities = INDEX.index("<h2>Hermes Capabilities</h2>")
        webhooks = INDEX.index("<h2>Webhook Health</h2>")
        themes = INDEX.index("<h2>Theme Studio</h2>")
        self.assertLess(capabilities, webhooks)
        self.assertLess(webhooks, themes)
        self.assertIn('class="panel-controls webhook-health-controls"', INDEX)
        self.assertIn('id="copy-webhook-setup" disabled', INDEX)
        self.assertIn('id="verify-webhook-probe" disabled', INDEX)
        self.assertIn('id="webhook-health-status"', INDEX)
        self.assertIn('role="status" aria-live="polite" aria-atomic="true"', INDEX)

    def test_renderer_allows_only_public_states_and_fixed_error_copy(self):
        start = APP.index("const WEBHOOK_HEALTH_STATES")
        end = APP.index("function replayStatusTone", start)
        renderer = APP[start:end]
        self.assertIn("new Set(['off', 'ready', 'receiving', 'degraded'])", renderer)
        self.assertIn("messages[err.message] || 'The signed probe could not be verified.'", renderer)
        self.assertNotIn("status.textContent = err.message", renderer)
        self.assertIn("escapeHtml(stateLabel)", renderer)
        self.assertIn("escapeHtml(summary)", renderer)

    def test_setup_copy_uses_visible_placeholder_only_text(self):
        start = APP.index("function webhookSetupText")
        end = APP.index("function replayStatusTone", start)
        implementation = APP[start:end]
        self.assertIn("secret_env: <YOUR_PRIVATE_SECRET_ENV>", implementation)
        self.assertIn("const localOrigin = window.location.origin", implementation)
        self.assertIn("navigator.clipboard.writeText(setup.textContent || '')", implementation)
        self.assertNotIn("window.location.port || '8888'", implementation)
        self.assertNotIn("127.0.0.1", implementation)
        for private_term in (
            "MENTAT_HERMES_WEBHOOK_SECRET_DEFAULT",
            "X-Hermes-Signature-256",
            "delivery_id",
            "session_id",
        ):
            self.assertNotIn(private_term, implementation)

    def test_renderer_displays_the_allowlisted_reconciliation_counter(self):
        start = APP.index("const WEBHOOK_HEALTH_STATES")
        end = APP.index("function replayStatusTone", start)
        renderer = APP[start:end]
        self.assertIn("safeCounter('reconciliations')", renderer)

    def test_phone_layout_wraps_timing_and_long_setup_lines(self):
        self.assertIn(".webhook-setup-text", STYLES)
        self.assertIn("overflow-wrap: anywhere", STYLES)
        mobile = STYLES[STYLES.index("@media (max-width: 480px)") :]
        self.assertIn(".webhook-health-grid", mobile)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", mobile)


if __name__ == "__main__":
    unittest.main()
