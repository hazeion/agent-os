import assert from "node:assert/strict";
import test from "node:test";
import { editOutput, reconcilePolicy } from "../src/app/tasks/project-plan-policy-draft.ts";
import type { PlanDraftNode, PlanPolicy } from "../src/lib/project-plan-contract.ts";

const nodes: PlanDraftNode[] = [
  { task_id: "task_research", expected_task_revision: 1, agent_id: "agent_research",
    input_version_id: `task_input_${"a".repeat(32)}`, after: [], segment: 0,
    max_attempts: 1, max_wall_seconds: 900, max_work_units: 100 },
  { task_id: "task_synthesis", expected_task_revision: 1, agent_id: "agent_synthesis",
    input_version_id: `task_input_${"b".repeat(32)}`, after: ["task_research"], segment: 1,
    max_attempts: 1, max_wall_seconds: 900, max_work_units: 100 },
];
const policy: PlanPolicy = {
  operations: [["read_public_web", "write_registered_artifacts"],
    ["read_selected_inputs", "write_registered_artifacts"]],
  outputs: [{ slot: "research_1", kind: "intermediate", type: "research", producer: 0,
    max_bytes: 100_000, owner_review: true }],
  transfers: [{ producer: 0, consumer: 1, slots: ["research_1"], use: "read_registered_input",
    max_files: 1, max_bytes: 100_000, segment: 1 }],
  ceilings: { max_attempts: 2, max_wall_seconds: 1800, max_work_units: 200 },
};

test("renaming an output preserves its exact planned handoff", () => {
  const edited = editOutput(policy, 0, { slot: "public_research_findings" });
  const reconciled = reconcilePolicy(edited, nodes, nodes);
  assert.deepEqual(reconciled.transfers[0].slots, ["public_research_findings"]);
  assert.equal(reconciled.outputs[0].slot, "public_research_findings");
});
