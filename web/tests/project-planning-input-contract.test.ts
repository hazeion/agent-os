import assert from "node:assert/strict";
import test from "node:test";
import { ProjectInputContractError, projectInputRequest, projectInputResult } from "../src/lib/project-planning-input-contract.ts";

const projectId = "project_garage", roleId = `lead_role_${"a".repeat(32)}`, contextId = `project_context_${"b".repeat(32)}`;
const inputId = `project_input_${"c".repeat(32)}`, actionId = `project_input_action_${"d".repeat(32)}`;
const file = { id: `attachment_${"e".repeat(32)}`, name: "floorplan.md", mime_type: "text/markdown", kind: "text", byte_size: 12,
  state: "attached", created_at: "2026-09-29T00:00:00Z", expires_at: null, available: true };
const context = { id: contextId, revision: 1, created_at: 1790640000, project_id: projectId, brief: "Keep bicycle access clear",
  retired: false, current: true, files: [file], prune_blocked: "current_version" };
export const editor = { project: { id: projectId, name: "Garage", revision: 1, status: "active" },
  lead: { id: roleId, revision: 1, agent_id: "agent_research", agent_name: "Research", status: "context_bound", reasons: [] },
  context, grant_revision: 1, input_revision: 0, scope_token: "1".repeat(64), selection_token: "2".repeat(64),
  save_available: true, version: null, versions: [] };
export const save = { project_id: projectId, expected_project_revision: 1, lead_role_id: roleId, expected_lead_revision: 1,
  context_id: contextId, expected_grant_revision: 1, expected_input_revision: 0, scope_token: "1".repeat(64),
  selection_token: "2".repeat(64), action_id: actionId, instructions: "Use the measured floorplan.", attachment_ids: [file.id] };

test("Project input contracts accept exact safe preparation and action readback", () => {
  assert.deepEqual(projectInputRequest("publish", save), save);
  assert.deepEqual(projectInputResult("project", editor, { project_id: projectId }), editor);
  assert.deepEqual(projectInputResult("publish", { input_id: inputId, revision: 1, status: "saved" }, save), { input_id: inputId, revision: 1, status: "saved" });
  assert.deepEqual(projectInputResult("reconcile", { status: "committed_needs_review", input_id: inputId, revision: 1 }, { project_id: projectId, action_id: actionId, scope_token: save.scope_token }), { status: "committed_needs_review", input_id: inputId, revision: 1 });
});

test("widened authority, private refs and malformed action attribution fail closed", () => {
  for (const value of [{ ...save, runtime_ref: "private" }, { ...save, expected_input_revision: true },
    { ...save, attachment_ids: [file.id, file.id] }, { ...save, action_id: "0".repeat(32) }])
    assert.throws(() => projectInputRequest("publish", value), ProjectInputContractError);
  for (const value of [{ ...editor, blob_sha256: "private" }, { ...editor, context: { ...context, files: [{ ...file, storage_key: "private" }] } },
    { ...editor, save_available: true, lead: { ...editor.lead, status: "stale" } }])
    assert.throws(() => projectInputResult("project", value, { project_id: projectId }), ProjectInputContractError);
  assert.throws(() => projectInputResult("publish", { input_id: inputId, revision: 1, status: "running" }, save), ProjectInputContractError);
  assert.throws(() => projectInputResult("reconcile", { status: "not_found", input_id: inputId, revision: null }, { project_id: projectId, action_id: actionId, scope_token: save.scope_token }), ProjectInputContractError);
});
