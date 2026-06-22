from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")


class VisualContractTests(unittest.TestCase):
    def test_hero_title_uses_jetbrains_mono_and_cool_theme_glow(self):
        self.assertIn("JetBrains Mono", CSS)
        hero_block = CSS[CSS.index(".command-header .hero-title") : CSS.index(".command-header .hero-title::after")]
        self.assertIn("JetBrains Mono", hero_block)
        self.assertIn("--hero-blue", hero_block)
        self.assertNotIn("--led-amber", hero_block)

    def test_sidebar_brand_contains_digitized_brain_not_plain_ao(self):
        brand_block = INDEX[INDEX.index('<div class="brand-block">') : INDEX.index('<nav class="nav-groups">')]
        header_block = INDEX[INDEX.index('<header class="command-header">') : INDEX.index('</header>')]
        self.assertIn("brain-brand", brand_block)
        self.assertIn("brain-frame", brand_block)
        self.assertIn("Digitized Mentat brain logo", brand_block)
        self.assertNotIn('class="brain-orb"', header_block)
        self.assertNotIn("15-frame cortex", header_block)
        self.assertNotIn(">AO</div>", brand_block)

    def test_brain_animation_is_low_frame_rate_and_respects_reduced_motion(self):
        self.assertIn("steps(15, end)", CSS)
        self.assertNotIn("15-frame cortex", INDEX)
        self.assertNotIn("15fps cortex", INDEX)
        self.assertIn("brain-spin", CSS)
        self.assertIn("prefers-reduced-motion", CSS)
        reduced_motion_block = CSS[CSS.index("prefers-reduced-motion") :]
        self.assertIn("animation: none !important", reduced_motion_block)
        self.assertNotIn("animation-name: brain-spin", reduced_motion_block)

    def test_projects_tasks_view_uses_refined_a_task_inspector(self):
        self.assertIn('id="selected-task-panel"', INDEX)
        self.assertIn('id="selected-task-detail"', INDEX)
        self.assertIn("Selected Task", INDEX)
        self.assertIn("function renderSelectedTaskInspector", APP_JS)
        self.assertIn("selectedTaskId", APP_JS)
        self.assertIn("task-list-item-button", APP_JS)
        self.assertIn("data-task-id", APP_JS)
        self.assertIn("aria-pressed", APP_JS)
        self.assertIn(".task-detail-card", CSS)
        self.assertIn(".task-list-item-button.active", CSS)

    def test_task_status_filter_uses_only_the_custom_dropdown_controls(self):
        self.assertIn('id="task-status-button"', INDEX)
        self.assertIn('id="task-status-menu"', INDEX)
        self.assertNotIn('id="task-status-filter"', INDEX)
        self.assertNotIn('visually-hidden', INDEX)
        self.assertNotIn('.visually-hidden', CSS)
        self.assertNotIn('const taskStatusFilter =', APP_JS)

    def test_refined_a_mobile_fallback_avoids_duplicate_status_pill_in_detail_header(self):
        self.assertIn('id="selected-task-back"', INDEX)
        self.assertIn('"queue"\n      "status"', CSS)
        self.assertIn("task-detail-meta-row", APP_JS)
        self.assertNotIn("Status</small><strong", APP_JS)
        self.assertNotIn("selected-task-status-pill", INDEX + APP_JS)


if __name__ == "__main__":
    unittest.main()
