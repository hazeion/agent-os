import assert from "node:assert/strict";
import test from "node:test";
import { ProjectLeadContractError, projectLeadRequest, projectLeadResult } from "../src/lib/project-lead-contract.ts";

const project_id = "project_garage", agent_id = "agent_research", token = "a".repeat(64);
const request = { project_id, agent_id, expected_project_revision: 1, expected_lead_revision: 0, selection_token: token };
const choice = { id: agent_id, name: "Research", context_bound: true, selection_token: token };
const before = { project_id, project_revision: 1, revision: 0, id: null, agent_id: null, agent_name: null,
  status: "unassigned", reasons: [], proposal_available: false, choices: [choice], clear_token: token };
const after = { ...before, revision: 1, id: `lead_role_${"b".repeat(32)}`, agent_id, agent_name: "Research", status: "context_bound" };

test("lead selection and readback accept only bounded safe fields", () => {
  assert.deepEqual(projectLeadRequest("project", { project_id }), { project_id });
  assert.deepEqual(projectLeadRequest("select", request), request);
  assert.deepEqual(projectLeadResult(before, { project_id }), before);
  assert.deepEqual(projectLeadResult(after, request), after);
});

test("private references and widened lead authority fail closed", () => {
  for (const invalid of [
    { ...request, runtime_ref: "private" }, { ...request, expected_lead_revision: true },
    { ...request, selection_token: "x".repeat(64) }, { ...request, agent_id: "../other" },
  ]) assert.throws(() => projectLeadRequest("select", invalid), ProjectLeadContractError);
  for (const invalid of [
    { ...after, binding_digest: token }, { ...after, proposal_available: true },
    { ...after, choices: [{ ...choice, runtime_ref: "private" }] },
    { ...after, revision: 2 }, { ...after, status: "context_bound", reasons: ["grant_changed"] },
  ]) assert.throws(() => projectLeadResult(invalid, request), ProjectLeadContractError);
});
