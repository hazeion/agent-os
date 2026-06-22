from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
import server


class ObsidianNotesViewTests(unittest.TestCase):
    def test_obsidian_notes_endpoint_returns_all_markdown_notes(self):
        payload = server.obsidian_notes()
        self.assertTrue(payload["exists"])
        vault = Path(payload["vault"])
        expected = sorted(
            [p.relative_to(vault).as_posix() for p in vault.rglob("*.md")],
            reverse=True,
        )
        actual = [note["relative_path"] for note in payload["notes"]]
        self.assertEqual(sorted(actual, reverse=True), expected)
        self.assertEqual(payload["note_count"], len(expected))

    def test_notes_view_has_scrollable_region_and_count_ui(self):
        self.assertIn('id="notes-count-pill"', INDEX_HTML)
        self.assertIn('id="notes-vault-meta"', INDEX_HTML)
        self.assertIn('class="notes-grid notes-scroll-region"', INDEX_HTML)
        self.assertIn('countPill.textContent', APP_JS)
        self.assertIn('payload.vault', APP_JS)
        self.assertIn('.notes-scroll-region {', STYLES)
        self.assertIn('overflow-y: auto;', STYLES)


if __name__ == "__main__":
    unittest.main()
