"""Untrusted lead proposals are inert suggestions, never Task authority."""

from copy import deepcopy
import json
import unittest

from project_proposal_artifact import (
    MAX_ARTIFACT_BYTES, ProjectProposalArtifactError,
    parse_proposal_artifact, proposal_snapshot_digest,
)


def _artifact() -> dict:
    return {
        "version": 1,
        "summary": "Organize the garage after confirming its dimensions.",
        "questions": [],
        "tasks": [
            {"title": "Research garage storage", "description": "Compare public options.",
             "agent_id": "agent_research", "due_date": None, "after": []},
            {"title": "Fit the layout to the floorplan", "description": "Use the owner's dimensions.",
             "agent_id": None, "due_date": "2026-10-15", "after": [0]},
        ],
    }


def _raw(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class ProjectProposalArtifactTests(unittest.TestCase):
    def assert_invalid(self, raw: bytes) -> None:
        with self.assertRaisesRegex(ProjectProposalArtifactError,
                                    "project_proposal.artifact_invalid"):
            parse_proposal_artifact(raw)

    def test_valid_task_graph_and_stable_snapshot_digest(self):
        source = _artifact()
        expected = parse_proposal_artifact(_raw(source))
        self.assertEqual(expected["tasks"][1]["after"], [0])
        self.assertEqual(expected["tasks"][1]["due_date"], "2026-10-15")
        changed_order = {key: source[key] for key in reversed(tuple(source))}
        self.assertEqual(expected, parse_proposal_artifact(
            json.dumps(changed_order, ensure_ascii=False, indent=2).encode("utf-8")))
        self.assertEqual(proposal_snapshot_digest(expected), proposal_snapshot_digest(
            parse_proposal_artifact(_raw(changed_order))))

    def test_question_only_is_reviewable_without_inventing_a_task(self):
        source = _artifact()
        source["tasks"] = []
        source["questions"] = [
            {"kind": "measurement", "text": "What is the garage width in millimeters?"},
        ]
        result = parse_proposal_artifact(_raw(source))
        self.assertEqual(result["tasks"], [])
        self.assertEqual(result["questions"][0]["kind"], "measurement")

    def test_capacity_is_counted_before_normalization(self):
        source = _artifact()
        source["tasks"] = [
            {"title": f"Task {index}", "description": "", "agent_id": None,
             "due_date": None, "after": []}
            for index in range(16)
        ]
        source["questions"] = [
            {"kind": "clarification", "text": f"Question {index}"}
            for index in range(8)
        ]
        self.assertEqual(len(parse_proposal_artifact(_raw(source))["tasks"]), 16)
        source["tasks"].append(deepcopy(source["tasks"][0]))
        self.assert_invalid(_raw(source))
        source["tasks"].pop()
        source["questions"].append(deepcopy(source["questions"][0]))
        self.assert_invalid(_raw(source))

    def test_raw_utf8_limit_malformed_json_and_duplicate_keys(self):
        self.assert_invalid(b"")
        valid = _raw(_artifact())
        self.assertEqual(len(parse_proposal_artifact(valid + b" " *
                                                     (MAX_ARTIFACT_BYTES - len(valid)))["tasks"]), 2)
        self.assert_invalid(valid + b" " * (MAX_ARTIFACT_BYTES - len(valid) + 1))
        self.assert_invalid(b"\xff")
        self.assert_invalid(b"\xef\xbb\xbf{}")
        self.assert_invalid(b'{"version":1,"version":1,"summary":"x","questions":[],"tasks":[]}')
        self.assert_invalid(valid.replace(b'"title":"Research garage storage"',
                                          b'"title":"A","title":"Research garage storage"', 1))
        self.assert_invalid(valid.replace(b'"summary":"Organize the garage after confirming its dimensions."',
                                          b'"summary":NaN', 1))
        self.assert_invalid(b'{} trailing')

    def test_authority_fields_and_invalid_text_are_rejected(self):
        for key, value in (("project_id", "project_other"), ("run_id", "run_other"),
                           ("tools", ["shell"]), ("file_path", "/etc/passwd")):
            source = _artifact()
            source[key] = value
            with self.subTest(key=key):
                self.assert_invalid(_raw(source))
        for text in ("bad\x00title", "bad\u200btitle", "bad\ntitle", "title\r",
                     "A\u2028B", "A\u2029B", "A" * 161):
            source = _artifact()
            source["tasks"][0]["title"] = text
            with self.subTest(text=text[:12]):
                self.assert_invalid(_raw(source))
        source = _artifact()
        source["tasks"][0]["description"] = "é" * 2049
        self.assert_invalid(_raw(source))
        source = _artifact()
        source["summary"] = "é" * 1025
        self.assert_invalid(_raw(source))

    def test_assignment_due_date_and_dependency_are_not_trusted(self):
        for agent in ("../agent", "agent/other", "", 1, "a" * 129):
            source = _artifact()
            source["tasks"][0]["agent_id"] = agent
            with self.subTest(agent=agent):
                self.assert_invalid(_raw(source))
        for due in ("2026-02-30", "2026-2-3", "tomorrow", 1):
            source = _artifact()
            source["tasks"][0]["due_date"] = due
            with self.subTest(due=due):
                self.assert_invalid(_raw(source))
        for after in ([1], [0, 0], [True], ["0"], [-1]):
            source = _artifact()
            source["tasks"][1]["after"] = after
            with self.subTest(after=after):
                self.assert_invalid(_raw(source))
        source = _artifact()
        source["tasks"][0]["after"] = [0]
        self.assert_invalid(_raw(source))

    def test_questions_are_bounded_and_unknown_shapes_fail(self):
        source = _artifact()
        source["questions"] = [{"kind": "measurement", "text": "Width?", "url": "https://x.test"}]
        self.assert_invalid(_raw(source))
        source["questions"] = [{"kind": "web_request", "text": "Fetch private URL"}]
        self.assert_invalid(_raw(source))
        source["questions"] = [{"kind": "measurement", "text": "x" * 513}]
        self.assert_invalid(_raw(source))
        source["questions"] = [{"kind": "measurement", "text": "Width?"},
                               {"kind": "measurement", "text": "width?"}]
        self.assert_invalid(_raw(source))
        source["questions"] = []
        source["tasks"] = []
        self.assert_invalid(_raw(source))

    def test_duplicate_task_titles_are_rejected(self):
        source = _artifact()
        source["tasks"][1]["title"] = "research garage storage"
        self.assert_invalid(_raw(source))

    def test_normalized_snapshot_cannot_exceed_artifact_ceiling(self):
        source = _artifact()
        source["tasks"] = [
            {"title": f"Task {index}", "description": "\u0344" * 1000,
             "agent_id": None, "due_date": None, "after": []}
            for index in range(12)
        ]
        self.assertLess(len(_raw(source)), MAX_ARTIFACT_BYTES)
        self.assert_invalid(_raw(source))

    def test_question_text_is_single_line(self):
        for separator in ("\n", "\r", "\u2028", "\u2029"):
            source = _artifact()
            source["questions"] = [{"kind": "measurement", "text": f"Width?{separator}Depth?"}]
            self.assert_invalid(_raw(source))

    def test_digest_rejects_a_forged_unparsed_snapshot(self):
        source = parse_proposal_artifact(_raw(_artifact()))
        source["tasks"][0]["after"] = [0]
        with self.assertRaises(ProjectProposalArtifactError):
            proposal_snapshot_digest(source)


if __name__ == "__main__":
    unittest.main()
