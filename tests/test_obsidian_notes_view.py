from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
import server


class ObsidianNotesViewTests(unittest.TestCase):
    def test_obsidian_notes_endpoint_returns_all_markdown_notes(self):
        with TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir) / "vault"
            (vault / "nested").mkdir(parents=True)
            (vault / "daily.md").write_text("# Daily", encoding="utf-8")
            (vault / "nested" / "project.md").write_text("# Project", encoding="utf-8")
            with patch.object(server, "OBSIDIAN_VAULT", vault), patch.dict(
                server.OBSIDIAN_NOTES_CACHE, {"key": None, "payload": None}, clear=True
            ):
                payload = server.obsidian_notes()

        self.assertTrue(payload["exists"])
        expected = ["nested/project.md", "daily.md"]
        actual = [note["relative_path"] for note in payload["notes"]]
        self.assertEqual(sorted(actual, reverse=True), expected)
        self.assertEqual(payload["note_count"], len(expected))
        self.assertNotIn("vault", payload)
        self.assertTrue(all("path" not in note for note in payload["notes"]))

    def test_notes_view_has_scrollable_region_and_count_ui(self):
        self.assertIn('id="notes-count"', INDEX_HTML)
        self.assertIn('id="notes-search"', INDEX_HTML)
        self.assertIn('id="notes-vault-meta"', INDEX_HTML)
        self.assertIn('class="notes-grid notes-scroll-region"', INDEX_HTML)
        self.assertIn('const countPill = $(\'#notes-count\')', APP_JS)
        self.assertIn('payload.vault_name', APP_JS)
        self.assertIn('data-attach-note', APP_JS)
        self.assertIn('.notes-scroll-region {', STYLES)
        self.assertIn('overflow-y: auto;', STYLES)

    def test_notes_endpoint_does_not_follow_markdown_symlinks_outside_the_vault(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            vault = root / "vault"
            vault.mkdir()
            (vault / "inside.md").write_text("inside", encoding="utf-8")
            outside = root / "outside.md"
            outside.write_text("outside secret", encoding="utf-8")
            link = vault / "linked.md"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            with patch.object(server, "OBSIDIAN_VAULT", vault), patch.dict(
                server.OBSIDIAN_NOTES_CACHE, {"key": None, "payload": None}, clear=True
            ):
                payload = server.obsidian_notes()

        self.assertEqual([note["relative_path"] for note in payload["notes"]], ["inside.md"])
        self.assertNotIn("outside secret", str(payload))


if __name__ == "__main__":
    unittest.main()
