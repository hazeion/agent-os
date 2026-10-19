import assert from "node:assert/strict";
import test from "node:test";
import { createProjectInputHandler } from "../src/lib/project-planning-input-route.ts";
import { GATEWAY_ROUTE_MANIFEST } from "../src/lib/gateway-route-manifest.ts";
import type { projectInputCapability } from "../src/lib/bridge-project-planning-inputs.ts";

const origin = "http://127.0.0.1:8890", projectId = "project_garage", base = `/api/projects/${projectId}/planning-inputs`;
const headers = { Host: "127.0.0.1:8890", Origin: origin, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json" };
const params = { params: Promise.resolve({ projectId }) };
const actionId = `project_input_action_${"a".repeat(32)}`;
const body = { expected_project_revision: 1, lead_role_id: `lead_role_${"b".repeat(32)}`, expected_lead_revision: 1,
  context_id: `project_context_${"c".repeat(32)}`, expected_grant_revision: 1, expected_input_revision: 0,
  scope_token: "d".repeat(64), selection_token: "e".repeat(64), action_id: actionId,
  instructions: "Plan the garage", attachment_ids: [] };
function request(path: string, method = "GET", value?: unknown, custom = headers) { return new Request(`${origin}${path}`, { method, headers: custom,
  ...(value === undefined ? {} : { body: JSON.stringify(value) }) }); }

test("every planning-input route is owner-only and saves require CSRF", () => {
  for (const [method, path] of [["GET", base], ["POST", base], ["GET", `${base}/[inputId]`], ["GET", `${base}/actions/[actionId]`]]) {
    const pattern = path.replace(projectId, "[projectId]");
    const rule = GATEWAY_ROUTE_MANIFEST.find((item) => item.method === method && item.path === pattern);
    assert.equal(rule?.exposure, "owner_session");
    assert.equal(rule?.csrf, method === "POST" ? "session_bound" : "not_required");
  }
});

test("owner Save binds exact Project path and rejects widened bodies", async () => {
  const calls: unknown[] = [];
  const capability = (async (operation: string, value: unknown) => { calls.push([operation, value]); return { input_id: `project_input_${"f".repeat(32)}`, revision: 1, status: "saved" }; }) as typeof projectInputCapability;
  const handler = createProjectInputHandler("publish", { capability, gatewayPort: "8890" });
  assert.equal((await handler(request(base, "POST", body), params)).status, 200);
  assert.deepEqual(calls, [["publish", { ...body, project_id: projectId }]]);
  for (const invalid of [{ ...body, project_id: "other" }, { ...body, runtime_ref: "private" }, { ...body, expected_input_revision: true }])
    assert.equal((await handler(request(base, "POST", invalid), params)).status, 400);
  assert.equal((await handler(request(`${base}?extra=1`, "POST", body), params)).status, 400);
  assert.equal((await handler(request(base, "POST", body, { ...headers, Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" }), params)).status, 403);
  assert.equal(calls.length, 1);
});

test("action readback accepts only its exact query token and path action", async () => {
  const calls: unknown[] = [];
  const capability = (async (operation: string, value: unknown) => { calls.push([operation, value]); return { status: "not_found", input_id: null, revision: null }; }) as typeof projectInputCapability;
  const handler = createProjectInputHandler("reconcile", { capability, gatewayPort: "8890" });
  const route = `${base}/actions/${actionId}`;
  const context = { params: Promise.resolve({ projectId, actionId }) };
  assert.equal((await handler(request(`${route}?scope_token=${"d".repeat(64)}`), context)).status, 200);
  assert.deepEqual(calls, [["reconcile", { project_id: projectId, action_id: actionId, scope_token: "d".repeat(64) }]]);
  for (const url of [route, `${route}?scope_token=${"d".repeat(64)}&extra=1`, `${route}?scope_token=x`])
    assert.equal((await handler(request(url), context)).status, 400);
  assert.equal(calls.length, 1);
});
