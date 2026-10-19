"""Policy intent is bounded and cannot silently join public web with private work."""

from copy import deepcopy
from contextlib import closing
import hashlib
import unittest

import mentat_db
import private_console_unit
from project_context import DELIVERABLE_REVIEW_MAX_METADATA_BYTES, PLAN_MAX_METADATA_BYTES, _encoded
from project_plan_policy import MAX_POLICY_CONTENT_BYTES, PlanPolicyError, normalize_policy
from project_plans import ProjectPlanError, _canonical, publish_owner_plan, validate_plan_connection
from task_inputs import publish_task_inputs
from tests import test_task_inputs


class ProjectPlanPolicyTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            {"task_id": "task_research", "after": [], "segment": 0,
             "max_attempts": 1, "max_wall_seconds": 900, "max_work_units": 100},
            {"task_id": "task_synthesis", "after": ["task_research"], "segment": 1,
             "max_attempts": 2, "max_wall_seconds": 900, "max_work_units": 100},
        ]
        self.policy = {
            "operations": [
                ["read_public_web", "write_registered_artifacts"],
                ["read_selected_inputs", "write_registered_artifacts"],
            ],
            "outputs": [
                {"slot": "public_research_findings", "kind": "intermediate", "type": "research",
                 "producer": 0, "max_bytes": 100_000, "owner_review": True},
                {"slot": "products", "kind": "final", "type": "document",
                 "producer": 1, "max_bytes": 200_000, "owner_review": True},
            ],
            "transfers": [
                {"producer": 0, "consumer": 1, "slots": ["public_research_findings"],
                 "use": "read_registered_input", "max_files": 1, "max_bytes": 100_000,
                 "segment": 1},
            ],
            "ceilings": {"max_attempts": 3, "max_wall_seconds": 2700, "max_work_units": 300},
        }

    def test_public_research_to_private_synthesis_has_exact_intermediate_handoff(self):
        expected = deepcopy(self.policy)
        self.assertEqual(normalize_policy(self.policy, self.nodes, stored=False), expected)
        expected["public_briefs"] = [{"node": 0, "digest": "a" * 64}]
        self.assertEqual(normalize_policy(expected, self.nodes, stored=True), expected)
        with self.assertRaises(PlanPolicyError):
            normalize_policy(expected, self.nodes, stored=False)

    def test_public_web_never_receives_private_inputs_or_downstream_outputs(self):
        direct = deepcopy(self.policy)
        direct["operations"][0].insert(0, "read_selected_inputs")
        with self.assertRaises(PlanPolicyError):
            normalize_policy(direct, self.nodes, stored=False)
        private_answer = deepcopy(self.policy)
        private_answer["operations"][0].insert(0, "ask_owner")
        with self.assertRaises(PlanPolicyError):
            normalize_policy(private_answer, self.nodes, stored=False)
        incoming = deepcopy(self.policy)
        incoming["operations"][1] = ["read_public_web", "write_registered_artifacts"]
        with self.assertRaises(PlanPolicyError):
            normalize_policy(incoming, self.nodes, stored=False)

    def test_transfer_cannot_substitute_a_different_producer_or_skip_dependency(self):
        for change in ("producer", "dependency", "segment"):
            with self.subTest(change=change):
                policy, nodes = deepcopy(self.policy), deepcopy(self.nodes)
                if change == "producer":
                    policy["outputs"][0]["producer"] = 1
                elif change == "dependency":
                    nodes[1]["after"] = []
                else:
                    policy["transfers"][0]["segment"] = 0
                with self.assertRaises(PlanPolicyError):
                    normalize_policy(policy, nodes, stored=False)

    def test_public_findings_require_owner_review_and_later_checkpoint(self):
        unchecked = deepcopy(self.policy)
        unchecked["outputs"][0]["owner_review"] = False
        with self.assertRaises(PlanPolicyError):
            normalize_policy(unchecked, self.nodes, stored=False)
        same_segment = deepcopy(self.nodes)
        same_segment[1]["segment"] = 0
        transfer = deepcopy(self.policy)
        transfer["transfers"][0]["segment"] = 0
        with self.assertRaises(PlanPolicyError):
            normalize_policy(transfer, same_segment, stored=False)

    def test_retry_ceiling_counts_every_allowed_attempt(self):
        for field, value in (("max_attempts", 2), ("max_wall_seconds", 1800),
                             ("max_work_units", 200)):
            with self.subTest(field=field):
                policy = deepcopy(self.policy)
                policy["ceilings"][field] = value
                with self.assertRaises(PlanPolicyError):
                    normalize_policy(policy, self.nodes, stored=False)

    def test_untrusted_nested_shapes_fail_as_policy_errors(self):
        for field in ("kind", "type"):
            policy = deepcopy(self.policy)
            policy["outputs"][0][field] = []
            with self.subTest(field=field), self.assertRaises(PlanPolicyError):
                normalize_policy(policy, self.nodes, stored=False)
        policy = deepcopy(self.policy)
        policy["transfers"][0]["use"] = []
        with self.assertRaises(PlanPolicyError):
            normalize_policy(policy, self.nodes, stored=False)

    def test_public_brief_is_frozen_from_exact_fileless_task_input(self):
        fixture = test_task_inputs.TaskInputStorageTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        public_input = publish_task_inputs(fixture.root, {
            **fixture.payload, "instructions": "Research public garage shelving methods.",
            "attachment_ids": [],
        })
        policy = {
            "operations": [["read_public_web", "write_registered_artifacts"]],
            "outputs": [{"slot": "public_research_findings", "kind": "intermediate",
                         "type": "research", "producer": 0, "max_bytes": 100_000,
                         "owner_review": True}],
            "transfers": [],
            "ceilings": {"max_attempts": 1, "max_wall_seconds": 900, "max_work_units": 100},
        }
        node = {"task_id": "task_research", "expected_task_revision": 1,
                "agent_id": "agent_research", "input_version_id": public_input["input_id"],
                "after": [], "segment": 0, "max_attempts": 1,
                "max_wall_seconds": 900, "max_work_units": 100}
        result = publish_owner_plan(
            fixture.root, "project_mentat", "Public garage research", [node],
            expected_project_revision=1, expected_plan_revision=0, policy=policy,
        )
        self.assertEqual(result["status"], "unapproved")
        with closing(mentat_db.connect(fixture.root)) as connection:
            self.assertEqual(connection.execute(
                "SELECT format FROM mentat_plan_versions WHERE id=?", (result["id"],)
            ).fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0], 0)
            validate_plan_connection(connection)
        private_console_unit.validate_private_console_unit(
            private_console_unit.capture_private_console_unit(fixture.root)
        )

    def test_web_plan_rejects_private_selected_file_before_publication(self):
        fixture = test_task_inputs.TaskInputStorageTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        private_input = publish_task_inputs(fixture.root, fixture.payload)
        policy = {"operations": [["read_public_web", "write_registered_artifacts"]],
                  "outputs": [], "transfers": [],
                  "ceilings": {"max_attempts": 1, "max_wall_seconds": 900, "max_work_units": 100}}
        node = {"task_id": "task_research", "expected_task_revision": 1,
                "agent_id": "agent_research", "input_version_id": private_input["input_id"],
                "after": [], "segment": 0, "max_attempts": 1,
                "max_wall_seconds": 900, "max_work_units": 100}
        with self.assertRaisesRegex(ProjectPlanError, "input_changed"):
            publish_owner_plan(fixture.root, "project_mentat", "Unsafe web research", [node],
                               expected_project_revision=1, expected_plan_revision=0, policy=policy)

    def test_dense_policy_rows_and_input_refs_fit_reserved_backup_metadata(self):
        task_ids = [f"task_{index:02d}_" + "x" * 45 for index in range(32)]
        nodes = [{"task_id": task_ids[index], "task_incarnation": "a" * 32,
                  "task_revision": 1, "agent_id": f"agent_{index:02d}_" + "y" * 40,
                  "agent_incarnation": "b" * 32,
                  "input_version_id": f"task_input_{index:032x}",
                  "after": [] if index == 0 else [task_ids[0]], "segment": 0,
                  "max_attempts": 1, "max_wall_seconds": 900, "max_work_units": 100}
                 for index in range(32)]
        outputs = [{"slot": f"research_{index}_" + "z" * 35,
                    "kind": "intermediate", "type": "research", "producer": 0,
                    "max_bytes": 1, "owner_review": True} for index in range(8)]
        outputs += [{"slot": slot, "kind": "final", "type": kind,
                     "producer": 0, "max_bytes": 1, "owner_review": True}
                    for slot, kind in (("layout", "diagram"), ("products", "document"), ("steps", "checklist"))]
        transfers = [{"producer": 0, "consumer": consumer, "slots": [outputs[slot]["slot"]],
                      "use": "read_registered_input", "max_files": 1,
                      "max_bytes": 1, "segment": 0}
                     for consumer in range(1, 21) for slot in (0, 1)]
        policy = {"operations": [["read_selected_inputs", "write_registered_artifacts"] for _ in nodes],
                  "outputs": outputs, "transfers": transfers,
                  "ceilings": {"max_attempts": 32, "max_wall_seconds": 28800,
                               "max_work_units": 3200}, "public_briefs": []}
        normalize_policy(policy, nodes, stored=True)
        raw = _canonical({"title": "Garage", "nodes": nodes, "policy": policy}).decode("utf-8")
        self.assertGreater(len(raw.encode("utf-8")), MAX_POLICY_CONTENT_BYTES - 256)
        self.assertLessEqual(len(raw.encode("utf-8")), MAX_POLICY_CONTENT_BYTES)
        scopes = [[f"plan_scope_{index:032x}", "project", "a" * 32,
                   f"project_scope_{index:032x}", 32, 1.0, "0" * 32] for index in range(256)]
        versions = [[f"plan_version_{index:032x}", f"plan_scope_{index:032x}",
                     1, 1, 2, raw, hashlib.sha256(raw.encode()).hexdigest(), "owner_edit", 1.0]
                    for index in range(256)]
        refs = [[f"plan_version_{index:032x}", f"task_input_{input_index:032x}"]
                for index in range(256) for input_index in range(32)]
        self.assertLess(len(_encoded([scopes, versions, refs])),
                        PLAN_MAX_METADATA_BYTES - DELIVERABLE_REVIEW_MAX_METADATA_BYTES)


if __name__ == "__main__":
    unittest.main()
