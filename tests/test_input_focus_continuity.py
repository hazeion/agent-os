from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[1]
CSS = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")


class InputFocusContinuityTests(unittest.TestCase):
    def test_search_inputs_use_their_visible_control_box_for_focus(self):
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
        shell_search_ids = set(
            re.findall(
                r'<label class="[^"]*search-shell[^"]*"[^>]*>.*?'
                r'<input[^>]*\bid="([^"]+)"[^>]*\btype="search"[^>]*>',
                INDEX,
                re.DOTALL,
            )
        )
        self.assertEqual(
            shell_search_ids,
            {
                "agent-creator-skill-search",
                "global-search",
                "notes-search",
                "session-search",
            },
        )
        self.assertIn("input[type='search']", CSS)

    def test_search_focus_highlights_the_visible_shell_border_only(self):
        self.assertIn(":root[data-ui-shell] .search-shell:focus-within", CSS)
        self.assertIn(
            ".search-shell:focus-within input:focus-visible",
            CSS,
        )
        shell_focus_start = CSS.index(".search-shell:focus-within")
        shell_focus_block = CSS[
            shell_focus_start : CSS.index("}", shell_focus_start) + 1
        ]
        self.assertIn("border-color:", shell_focus_block)
        self.assertIn("outline: none;", shell_focus_block)
        self.assertIn("box-shadow: none;", shell_focus_block)
        self.assertNotIn("outline-offset:", shell_focus_block)
        input_focus_start = CSS.index(
            ".search-shell:focus-within input:focus-visible"
        )
        input_focus_block = CSS[
            input_focus_start : CSS.index("}", input_focus_start) + 1
        ]
        self.assertIn("outline: none;", input_focus_block)
        self.assertIn("box-shadow: none;", input_focus_block)
        self.assertIn("border-color: transparent;", input_focus_block)

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
        alignment_selector = ".session-controls-card > .search-shell"
        self.assertIn(alignment_selector, CSS)
        alignment_start = CSS.index(alignment_selector)
        alignment_block = CSS[
            alignment_start : CSS.index("}", alignment_start) + 1
        ]
        self.assertIn("align-self: end;", alignment_block)

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

    def test_text_entry_focus_uses_its_border_without_an_outer_effect(self):
        focus_selector = (
            ":root[data-ui-shell] :where(\n"
            "  input:not([type]),\n  input[type='text'],"
        )
        self.assertIn(focus_selector, CSS)
        focus_start = CSS.index(focus_selector)
        focus_block = CSS[focus_start : CSS.index("}", focus_start) + 1]
        self.assertIn("textarea\n):focus-visible", focus_block)
        self.assertIn("border-color:", focus_block)
        self.assertIn("outline: none;", focus_block)
        self.assertIn("box-shadow: none;", focus_block)
        self.assertNotIn("outline-offset:", focus_block)

        specific_selector = (
            ":root[data-ui-shell] "
            ".task-editor-field :is(input, textarea):focus,"
        )
        self.assertIn(specific_selector, CSS)
        specific_start = CSS.index(specific_selector)
        specific_block = CSS[specific_start : CSS.index("}", specific_start) + 1]
        self.assertIn("border-color:", specific_block)
        self.assertIn("outline: none;", specific_block)
        self.assertIn("box-shadow: none;", specific_block)
        self.assertNotIn("outline-offset:", specific_block)

    def test_final_text_entry_focus_rules_win_the_emerald_cascade(self):
        def specificity(selector):
            selector = re.sub(
                r":where\(.*\)(?=:focus-visible)",
                "",
                selector,
                flags=re.DOTALL,
            )
            ids = len(re.findall(r"#[\w-]+", selector))
            class_like = len(
                re.findall(r"\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+", selector)
            )
            elements = len(
                re.findall(r"(?:^|[ >+~])([a-z][\w-]*)", selector)
            )
            return ids, class_like, elements

        competitor = (
            ":root[data-ui-shell='emerald'] :where(\n"
            "  button,\n  a,\n  input,"
        )
        competitor_start = CSS.index(competitor)
        competitor_selector = CSS[competitor_start : CSS.index("{", competitor_start)]
        competitor_block = CSS[
            competitor_start : CSS.index("}", competitor_start) + 1
        ]
        self.assertIn("outline: 2px solid", competitor_block)
        self.assertNotIn("!important", competitor_block)

        final_selectors = (
            ":root[data-ui-shell] :where(\n  input:not([type]),",
            ":root[data-ui-shell] .task-editor-field :is(input, textarea):focus",
            ":root[data-ui-shell] .agent-console-form textarea:focus-visible",
            ":root[data-ui-shell] .agent-console-workspace-search input:focus-visible",
            ".search-shell:focus-within input:focus-visible",
        )
        for selector in final_selectors:
            with self.subTest(selector=selector):
                start = CSS.index(selector)
                self.assertGreater(start, competitor_start)
                cascade_selector = (
                    CSS[start : CSS.index("{", start)]
                    if ":where(" in selector
                    else selector
                )
                self.assertGreaterEqual(
                    specificity(cascade_selector), specificity(competitor_selector)
                )
                block = CSS[start : CSS.index("}", start) + 1]
                self.assertIn("outline: none;", block)
                self.assertNotIn("!important", block)

        search_base_selector = ":root[data-ui-shell='emerald'] .search-shell"
        search_base_start = CSS.index(f"{search_base_selector} {{")
        search_base_block = CSS[
            search_base_start : CSS.index("}", search_base_start) + 1
        ]
        search_focus_selector = ":root[data-ui-shell] .search-shell:focus-within"
        search_focus_start = CSS.index(f"{search_focus_selector} {{")
        search_focus_block = CSS[
            search_focus_start : CSS.index("}", search_focus_start) + 1
        ]
        self.assertGreater(search_focus_start, search_base_start)
        self.assertGreater(
            specificity(search_focus_selector), specificity(search_base_selector)
        )
        for declaration in (
            "border-color: var(--accent);",
            "outline: none;",
            "box-shadow: none;",
        ):
            self.assertIn(declaration, search_focus_block)
        self.assertNotIn("!important", search_base_block)
        self.assertNotIn("!important", search_focus_block)
        self.assertNotIn("\n.search-shell:focus-within {", CSS)


if __name__ == "__main__":
    unittest.main()
