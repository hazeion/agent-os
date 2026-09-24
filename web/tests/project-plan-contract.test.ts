import assert from "node:assert/strict";
import test from "node:test";
import { ProjectPlanContractError, projectPlanRequest, projectPlanResult } from "../src/lib/project-plan-contract.ts";

const projectId = "project_garage", versionId = `plan_version_${"a".repeat(32)}`, inputId = `task_input_${"b".repeat(32)}`;
const node = { task_id: "task_research", expected_task_revision: 1, agent_id: "agent_research", input_version_id: inputId,
  after: [], segment: 0, max_attempts: 1, max_wall_seconds: 900, max_work_units: 100 };
const publish = { project_id: projectId, expected_project_revision: 1, expected_plan_revision: 0, title: "Garage organization", nodes: [node] };
const saved = { task_id: node.task_id, task_revision: 1, agent_id: node.agent_id, input_version_id: inputId,
  after: [], segment: 0, max_attempts: 1, max_wall_seconds: 900, max_work_units: 100 };
const comparison = { missing_from_plan: [], additional_in_plan: [], missing_count: 0, additional_count: 0, truncated: false };

test("exact plan publication and read projections keep private identities out", () => {
  assert.deepEqual(projectPlanRequest("publish", publish), publish);
  const project = { project: { id: projectId, name: "Garage", revision: 1, status: "active" }, plan_revision: 1,
    current: { title: publish.title, nodes: [saved] }, versions: [{ id: versionId, revision: 1, title: publish.title, node_count: 1, created_at: 1790035200 }],
    stale_reasons: [], dependency_comparison: comparison, execution_available: false };
  assert.equal(projectPlanResult("project", project, { project_id: projectId }).plan_revision, 1);
  assert.equal(projectPlanResult("publish", { id: versionId, revision: 1, project_id: projectId, status: "unapproved" }, publish).id, versionId);
  const version = { id: versionId, project_id: projectId, revision: 1, project_revision: 1, title: publish.title,
    nodes: [{ ...saved, task_state: "current", task_title: "Research storage", agent_state: "current", agent_name: "Research Agent" }], created_at: 1790035200, current: true, status: "unapproved" };
  assert.deepEqual(projectPlanResult("version", version, { project_id: projectId, version_id: versionId }), version);
});

test("widened, unsorted, cyclic and private plan requests fail closed", () => {
  for (const invalid of [
    { ...publish, runtime_ref: "private" },
    { ...publish, expected_plan_revision: true },
    { ...publish, nodes: [] },
    { ...publish, nodes: [{ ...node, after: [node.task_id] }] },
    { ...publish, nodes: [{ ...node, max_wall_seconds: 0 }] },
    { ...publish, title: "Garage\u202e" },
  ]) assert.throws(() => projectPlanRequest("publish", invalid), ProjectPlanContractError);
  assert.throws(() => projectPlanResult("project", { project: { id: projectId, name: "Garage", revision: 1, status: "active" },
    plan_revision: 1, current: { title: publish.title, nodes: [{ ...saved, task_incarnation: "private" }] },
    versions: [{ id: versionId, revision: 1, title: publish.title, node_count: 1, created_at: 1790035200 }],
    stale_reasons: [], dependency_comparison: comparison, execution_available: false }, { project_id: projectId }), ProjectPlanContractError);
});

test("dependency comparison is bounded in both directions", () => {
  const project = { project: { id: projectId, name: "Garage", revision: 2, status: "active" }, plan_revision: 1,
    current: { title: publish.title, nodes: [saved] }, versions: [{ id: versionId, revision: 1, title: publish.title, node_count: 1, created_at: 1790035200 }],
    stale_reasons: ["project_changed", "dependency_mismatch"], dependency_comparison: { ...comparison,
      missing_count: 1, missing_from_plan: [{ task_id: "task_research", prerequisite_id: "task_measure" }] }, execution_available: false };
  assert.equal(projectPlanResult("project", project, { project_id: projectId }).dependency_comparison.missing_count, 1);
  assert.throws(() => projectPlanResult("project", { ...project, dependency_comparison: { ...project.dependency_comparison, extra_private: true } }, { project_id: projectId }), ProjectPlanContractError);
});
