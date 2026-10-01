import assert from "node:assert/strict";
import test from "node:test";
import { createProjectPlanHandler, PROJECT_PLAN_ROUTES } from "../src/lib/project-plan-route.ts";
import { GATEWAY_ROUTE_MANIFEST } from "../src/lib/gateway-route-manifest.ts";
import type { projectPlanCapability } from "../src/lib/bridge-project-plans.ts";

const origin = "http://127.0.0.1:8890";
const headers = { Host: "127.0.0.1:8890", Origin: origin, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json" };
const params = { params: Promise.resolve({ projectId: "project_garage", versionId: `plan_version_${"a".repeat(32)}` }) };
const body = { expected_project_revision: 1, expected_plan_revision: 0, title: "Garage", nodes: [{ task_id: "task_research", expected_task_revision: 1,
  agent_id: "agent_research", input_version_id: `task_input_${"b".repeat(32)}`, after: [], segment: 0,
  max_attempts: 1, max_wall_seconds: 900, max_work_units: 100 }] };
function request(path: string, method = "GET", value?: unknown) { return new Request(`${origin}${path}`, { method, headers, ...(value === undefined ? {} : { body: JSON.stringify(value) }) }); }

test("every plan route is owner-only and mutations require session CSRF", () => {
  for (const [method, path] of Object.values(PROJECT_PLAN_ROUTES)) {
    const rule = GATEWAY_ROUTE_MANIFEST.find((item) => item.method === method && item.path === path);
    assert.equal(rule?.exposure, "owner_session");
    assert.equal(rule?.csrf, method === "GET" ? "not_required" : "session_bound");
  }
});

test("plan Save binds the Project path and rejects widened or foreign requests", async () => {
  const calls: unknown[] = [];
  const capability = (async (operation: string, value: unknown) => { calls.push([operation, value]); return { id: `plan_version_${"a".repeat(32)}`, revision: 1, project_id: "project_garage", status: "unapproved" }; }) as typeof projectPlanCapability;
  const handler = createProjectPlanHandler("publish", { capability, gatewayPort: "8890" });
  const path = "/api/projects/project_garage/plan";
  assert.equal((await handler(request(path, "POST", body), params)).status, 200);
  assert.deepEqual(calls, [["publish", { ...body, project_id: "project_garage" }]]);
  for (const invalid of [{ ...body, project_id: "other" }, { ...body, runtime_ref: "private" }, { ...body, expected_plan_revision: true }])
    assert.equal((await handler(request(path, "POST", invalid), params)).status, 400);
  assert.equal((await handler(request(`${path}?extra=1`, "POST", body), params)).status, 400);
  assert.equal((await handler(new Request(`${origin}${path}`, { method: "POST", headers: { ...headers, Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" }, body: JSON.stringify(body) }), params)).status, 403);
  assert.equal(calls.length, 1);
});
