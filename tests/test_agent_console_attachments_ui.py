from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
CORE = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")


class AgentConsoleAttachmentUiTests(unittest.TestCase):
    def test_composer_has_accessible_attachment_controls(self):
        console = INDEX[INDEX.index('id="agent-console-panel"'):INDEX.index('id="today-completed-panel"')]
        self.assertIn('id="agent-console-attach"', console)
        self.assertIn('aria-label="Attach files"', console)
        self.assertIn('aria-expanded="false"', console)
        self.assertIn('id="agent-console-attachment-menu"', console)
        self.assertIn('data-agent-console-upload', console)
        self.assertIn('id="agent-console-file-input"', console)
        self.assertIn('multiple', console)
        self.assertIn('hidden', console)
        self.assertIn('id="agent-console-attachment-tray"', console)

    def test_uploads_are_raw_sequential_requests_with_safe_filename_encoding(self):
        upload = CORE[CORE.index("async function uploadAgentConsoleAttachment"):CORE.index("async function fetchAgentConsoleRun")]
        self.assertIn("agentConsoleAttachments: '/api/agent-console/attachments'", CORE)
        self.assertIn("'Content-Type': file.type || 'application/octet-stream'", upload)
        self.assertIn("'X-Mentat-Filename': encodeURIComponent(file.name", upload)
        self.assertIn("body: file", upload)
        self.assertIn("for (const file of Array.from(files))", upload)
        self.assertIn("await uploadAgentConsoleAttachment(file)", upload)

    def test_run_submission_binds_only_opaque_attachment_ids(self):
        submit = APP[APP.index("async function submitAgentConsolePrompt"):APP.index("function renderCrons")]
        self.assertIn("if (!value && !state.agentConsoleAttachments.length) return", submit)
        self.assertIn("attachment_ids: state.agentConsoleAttachments.map((attachment) => attachment.id)", submit)
        self.assertIn("state.agentConsoleAttachments = []", submit)
        self.assertNotIn("content_url:", submit)
        self.assertNotIn("relative_path:", submit)

    def test_attachment_previews_require_same_origin_server_urls(self):
        rendering = APP[APP.index("function safeAgentConsoleContentUrl"):APP.index("function renderAgentConsole(payload")]
        self.assertIn("url.origin !== window.location.origin", rendering)
        self.assertIn("attachment_[a-f0-9]{32}", rendering)
        self.assertIn("attachment?.content_url", rendering)
        self.assertIn('loading="lazy"', rendering)
        self.assertIn("data-remove-agent-console-attachment", rendering)
        self.assertNotIn("file://", rendering)
        self.assertNotIn("data:image", rendering)
        self.assertNotIn("URL.createObjectURL", rendering)

    def test_composer_keeps_ready_attachments_and_upload_errors_visible(self):
        rendering = APP[APP.index("function renderAgentConsoleAttachmentTray"):APP.index("function setAgentConsoleAttachmentMenu")]
        upload = APP[APP.index("async function addAgentConsoleFiles"):APP.index("function renderAgentConsole(payload")]
        self.assertIn("Prompt attachments", rendering)
        self.assertIn("ready for next prompt", rendering)
        self.assertIn("agentConsoleAttachmentError", rendering)
        self.assertIn('role="alert"', rendering)
        self.assertIn("older server build", APP)
        self.assertIn("state.agentConsoleAttachmentError = agentConsoleUploadErrorMessage(err)", upload)
        self.assertIn(".agent-console-attachment-tray-head", CSS)
        self.assertIn(".agent-console-attachment-error", CSS)

    def test_run_input_attachments_and_responsive_chips_are_rendered(self):
        render = APP[APP.index("function renderAgentConsole(payload"):APP.index("function scheduleAgentConsolePoll")]
        self.assertIn("run.attachments", render)
        self.assertIn("run.input_attachments", render)
        self.assertIn("agentConsoleAttachmentCards(inputAttachments)", render)
        self.assertIn("Used as prompt context", render)
        self.assertIn(".agent-console-attachment-card", CSS)
        self.assertIn("max-width: min(240px, 100%)", CSS)
        self.assertIn("flex-wrap: wrap", CSS)

    def test_fenced_code_is_escaped_and_has_language_and_copy_controls(self):
        renderer = CORE[CORE.index("function renderMarkdown(value"):CORE.index("async function api")]
        self.assertIn("^[A-Za-z0-9_+#.-]{1,32}$", renderer)
        self.assertIn("escapeHtml(language || 'plain text')", renderer)
        self.assertIn("escapeHtml(code.trimEnd())", renderer)
        self.assertIn('class="markdown-code-block"', renderer)
        self.assertIn("data-copy-code", renderer)
        self.assertNotIn("innerHTML", renderer)

    def test_code_copy_reads_rendered_text_instead_of_an_html_attribute(self):
        copying = APP[APP.index("async function copyRenderedCode"):APP.index("function renderAgentConsoleAttachmentTray")]
        self.assertIn("querySelector('code')?.textContent", copying)
        self.assertIn("navigator.clipboard?.writeText", copying)
        self.assertNotIn("dataset.code", copying)

    def test_only_validated_same_origin_raster_images_are_embedded(self):
        media = APP[APP.index("const AGENT_CONSOLE_INLINE_IMAGE_TYPES"):APP.index("function renderAgentConsoleAttachmentTray")]
        for mime_type in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            self.assertIn(mime_type, media)
        for unsafe_type in ("image/svg+xml", "text/html", "application/pdf"):
            self.assertNotIn(unsafe_type, media)
        self.assertIn("safeAgentConsoleContentUrl(artifact?.content_url)", media)
        self.assertIn("download=", media)
        self.assertNotIn("<iframe", media)
        self.assertNotIn("<object", media)
        self.assertNotIn("<embed", media)

    def test_run_output_artifacts_render_even_without_response_text(self):
        render = APP[APP.index("function renderAgentConsole(payload"):APP.index("function scheduleAgentConsolePoll")]
        self.assertIn("run.artifacts", render)
        self.assertIn("run.output_artifacts", render)
        self.assertIn("agentConsoleArtifactCards(outputArtifacts)", render)
        self.assertIn("run.response || artifactCards", render)
        self.assertIn(".agent-console-artifact-grid", CSS)
        self.assertIn(".markdown-code-copy", CSS)
        self.assertIn("white-space: pre-wrap", CSS)

    def test_attachment_menu_exposes_compact_workspace_search(self):
        menu = INDEX[INDEX.index('id="agent-console-attachment-menu"'):INDEX.index('id="agent-console-file-input"')]
        self.assertIn("Choose from workspace", menu)
        self.assertIn('id="agent-console-workspace-picker"', menu)
        self.assertIn('id="agent-console-workspace-query"', menu)
        self.assertIn('placeholder="Search relative paths…"', menu)
        self.assertIn('id="agent-console-workspace-results"', menu)
        self.assertIn(".agent-console-workspace-results", CSS)
        self.assertIn("max-height: 220px", CSS)

    def test_workspace_api_uses_only_root_id_and_relative_path(self):
        helpers = CORE[CORE.index("async function fetchAgentConsoleWorkspaceFiles"):CORE.index("async function fetchAgentConsoleRun")]
        self.assertIn("'/api/agent-console/workspace-files'", CORE)
        self.assertIn("'/api/agent-console/workspace-attachments'", CORE)
        self.assertIn("?q=${encodeURIComponent", helpers)
        self.assertIn("root_id: rootId", helpers)
        self.assertIn("relative_path: relativePath", helpers)
        self.assertNotIn("absolute", helpers.lower())
        self.assertNotIn("file://", helpers)

    def test_workspace_choices_reject_absolute_and_traversing_paths(self):
        workspace = APP[APP.index("function safeAgentConsoleWorkspaceChoice"):APP.index("async function addAgentConsoleFiles")]
        self.assertIn("normalizedPath.startsWith('/')", workspace)
        self.assertIn("normalizedPath.includes('\\0')", workspace)
        self.assertIn("normalizedPath.includes('\\\\')", workspace)
        self.assertIn("/^[A-Za-z]:/.test(normalizedPath)", workspace)
        self.assertIn("part === '..'", workspace)
        self.assertIn("part === '.'", workspace)
        self.assertIn("slice(0, 40)", workspace)
        self.assertIn("escapeHtml(file.relative_path)", workspace)
        self.assertNotIn("file://", workspace)

    def test_workspace_picker_has_loading_empty_error_and_success_states(self):
        workspace = APP[APP.index("function renderAgentConsoleWorkspaceResults"):APP.index("async function addAgentConsoleFiles")]
        self.assertIn("Loading workspace files…", workspace)
        self.assertIn("No matching workspace files.", workspace)
        self.assertIn("Workspace files are unavailable.", workspace)
        self.assertIn("payload.attachment || payload", workspace)
        self.assertIn("state.agentConsoleAttachments.push(attachment)", workspace)
        self.assertIn("attached as a private snapshot", workspace)
        self.assertIn("state.agentConsoleAttachmentsUploading = false", workspace)
        self.assertIn("renderAgentConsoleAttachmentTray()", workspace)


if __name__ == "__main__":
    unittest.main()
