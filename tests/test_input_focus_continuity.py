from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[1]
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")


class InputFocusContinuityTests(unittest.TestCase):
    def test_all_search_inputs_use_the_shared_editable_focus_contract(self):
        search_ids = set(
            re.findall(
                r'<input[^>]*\bid="([^"]+)"[^>]*\btype="search"[^>]*>',
                INDEX,
            )
        )
        self.assertEqual(
            search_ids,
            {
                "agent-console-workspace-query",
                "agent-creator-skill-search",
                "context-pack-workspace-query",
                "global-search",
                "notes-search",
                "session-search",
            },
        )
        self.assertIn("input[type='search']", CSS)
        self.assertNotRegex(
            CSS,
            r"(?:search-shell|workspace-search|input-wrap)[^{]*:focus-within",
        )

    def test_search_focus_belongs_to_the_editable_input_only(self):
        self.assertNotIn(".search-shell:focus-within", CSS)
        self.assertIn(".search-shell input:focus-visible", CSS)
        focus_block = CSS[
            CSS.index(".search-shell input:focus-visible")
            : CSS.index("}", CSS.index(".search-shell input:focus-visible")) + 1
        ]
        self.assertIn("outline:", focus_block)
        self.assertIn("outline-offset:", focus_block)

    def test_session_selector_and_search_share_one_control_height(self):
        card_block = CSS[
            CSS.index(".session-controls-card {")
            : CSS.index("}", CSS.index(".session-controls-card {")) + 1
        ]
        self.assertIn("--session-control-height:", card_block)
        self.assertIn(
            ".session-controls-card :is(.session-select, .search-shell)",
            CSS,
        )
        shared_block = CSS[
            CSS.index(".session-controls-card :is(.session-select, .search-shell)")
            : CSS.index(
                "}",
                CSS.index(".session-controls-card :is(.session-select, .search-shell)"),
            )
            + 1
        ]
        self.assertIn("height: var(--session-control-height)", shared_block)
        self.assertIn("min-height: var(--session-control-height)", shared_block)

    def test_agent_console_status_is_plain_dot_and_text(self):
        console = INDEX[
            INDEX.index('id="agent-console-transcript"')
            : INDEX.index('id="agent-console-form-status"')
        ]
        self.assertIn('id="agent-console-presence"', console)
        self.assertIn('id="agent-console-state"', console)
        status_block = CSS[
            CSS.index(":root[data-ui-shell='emerald'] .home-console-state {")
            : CSS.index(
                "}",
                CSS.index(":root[data-ui-shell='emerald'] .home-console-state {"),
            )
            + 1
        ]
        for declaration in (
            "padding: 0;",
            "border: 0;",
            "border-radius: 0;",
            "background: transparent;",
        ):
            self.assertIn(declaration, status_block)
        self.assertNotIn("flex: 1 1", status_block)

    def test_long_agent_console_status_is_safely_truncated(self):
        state_selector = (
            ":root[data-ui-shell='emerald'] "
            ".home-console-state #agent-console-state {"
        )
        state_start = CSS.index(state_selector)
        state_block = CSS[state_start : CSS.index("}", state_start) + 1]
        for declaration in (
            "display: block;",
            "min-width: 0;",
            "max-width: 100%;",
            "overflow: hidden;",
            "text-overflow: ellipsis;",
            "white-space: nowrap;",
        ):
            self.assertIn(declaration, state_block)

    def test_text_entry_focus_remains_visible_without_a_second_shadow(self):
        focus_selector = ":where(\n  input:not([type]),\n  input[type='text'],"
        self.assertIn(focus_selector, CSS)
        focus_start = CSS.index(focus_selector)
        focus_block = CSS[focus_start : CSS.index("}", focus_start) + 1]
        self.assertIn("textarea\n):focus-visible", focus_block)
        self.assertIn("outline:", focus_block)
        self.assertIn("box-shadow: none;", focus_block)


if __name__ == "__main__":
    unittest.main()
