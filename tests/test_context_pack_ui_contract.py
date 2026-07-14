from pathlib import Path
import json
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE = (ROOT / "public" / "core.js").read_text(encoding="utf-8")


class ContextPackUiContractTests(unittest.TestCase):
    def test_delete_prefers_content_revision_with_legacy_timestamp_fallback(self):
        helper = CORE[CORE.index("async function removeContextPack") : CORE.index("async function stageContextPack")]
        self.assertIn("payload.expected_revision = expectedRevision", helper)
        self.assertIn("else if (updatedAt) payload.expected_updated_at = updatedAt", helper)
        self.assertNotIn("expected_updated_at: updatedAt", helper)
        self.assertIn("removeContextPack(binding.id, binding.revision, binding.updated_at)", APP)

    def test_editor_delete_remains_bound_to_opened_draft_during_live_refresh(self):
        script = r'''
const source = require('fs').readFileSync(process.argv[1], 'utf8');
function functionSource(name) {
  const marker = `function ${name}`;
  const start = source.indexOf(marker);
  const parameters = source.indexOf('(', start);
  let parameterDepth = 0;
  let brace = -1;
  for (let index = parameters; index < source.length; index += 1) {
    if (source[index] === '(') parameterDepth += 1;
    if (source[index] === ')') parameterDepth -= 1;
    if (parameterDepth === 0) {
      brace = source.indexOf('{', index);
      break;
    }
  }
  let depth = 0;
  for (let index = brace; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`unterminated ${name}`);
}
eval(functionSource('contextPackEditorDraft'));
eval(functionSource('contextPackDeleteBinding'));
const opened = { id: 'pack-1', name: 'Opened', revision: 'rev-opened', updated_at: 'time-opened' };
const draft = contextPackEditorDraft(opened);
opened.revision = 'rev-live-refresh';
opened.updated_at = 'time-live-refresh';
const binding = contextPackDeleteBinding(draft, 'pack-1');
process.stdout.write(JSON.stringify({ draft, binding, live: opened }));
'''
        result = subprocess.run(
            ["node", "-e", script, str(ROOT / "public" / "app.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["binding"]["revision"], "rev-opened")
        self.assertEqual(payload["binding"]["updated_at"], "time-opened")
        self.assertEqual(payload["live"]["revision"], "rev-live-refresh")

        delete_handler = APP[
            APP.index("$('[data-context-pack-delete]')?.addEventListener") :
            APP.index("$('#context-pack-list')?.addEventListener")
        ]
        self.assertIn("contextPackDeleteBinding(state.contextPackDraft", delete_handler)
        self.assertNotIn("state.contextPacks.find", delete_handler)


if __name__ == "__main__":
    unittest.main()
