import assert from "node:assert/strict";
import test from "node:test";
import { createProjectLeadHandler } from "../src/lib/project-lead-route.ts";
import { GATEWAY_ROUTE_MANIFEST } from "../src/lib/gateway-route-manifest.ts";
import type { projectLeadCapability } from "../src/lib/bridge-project-leads.ts";

const origin = "http://127.0.0.1:8890", path = "/api/projects/project_garage/lead";
const headers = { Host: "127.0.0.1:8890", Origin: origin, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json" };
const params = { params: Promise.resolve({ projectId: "project_garage" }) };
const body = { agent_id: "agent_research", expected_project_revision: 1, expected_lead_revision: 0, selection_token: "a".repeat(64) };
function request(method: string, value?: unknown, url = path, custom = headers) { return new Request(`${origin}${url}`, { method, headers: custom,
  ...(value === undefined ? {} : { body: JSON.stringify(value) }) }); }

test("lead routes require owner session and mutation CSRF", () => {
  for (const method of ["GET", "POST"]) {
    const rule = GATEWAY_ROUTE_MANIFEST.find((item) => item.method === method && item.path === "/api/projects/[projectId]/lead");
    assert.equal(rule?.exposure, "owner_session");
    assert.equal(rule?.csrf, method === "GET" ? "not_required" : "session_bound");
  }
});

test("lead save binds Project path and exact fields before bridge call", async () => {
  const calls: unknown[] = [];
  const capability = (async (operation: string, value: unknown) => { calls.push([operation, value]); return { project_id: "project_garage", project_revision: 1,
    revision: 1, id: `lead_role_${"b".repeat(32)}`, agent_id: "agent_research", agent_name: "Research", status: "context_bound",
    reasons: [], proposal_available: false, choices: [], clear_token: "a".repeat(64) }; }) as typeof projectLeadCapability;
  const handler = createProjectLeadHandler("select", { capability, gatewayPort: "8890" });
  assert.equal((await handler(request("POST", body), params)).status, 200);
  assert.deepEqual(calls, [["select", { ...body, project_id: "project_garage" }]]);
  for (const invalid of [{ ...body, project_id: "other" }, { ...body, runtime_ref: "private" }, { ...body, expected_lead_revision: true }])
    assert.equal((await handler(request("POST", invalid), params)).status, 400);
  assert.equal((await handler(request("POST", body, `${path}?extra=1`), params)).status, 400);
  assert.equal((await handler(request("POST", body, path, { ...headers, Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" }), params)).status, 403);
  assert.equal(calls.length, 1);
});
