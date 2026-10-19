import assert from "node:assert/strict";
import test from "node:test";
import { createProjectDeliverableHandler, PROJECT_DELIVERABLE_ROUTES } from "../src/lib/project-deliverable-route.ts";
import { GATEWAY_ROUTE_MANIFEST } from "../src/lib/gateway-route-manifest.ts";
import type { projectDeliverableCapability } from "../src/lib/bridge-project-deliverables.ts";

const origin = "http://127.0.0.1:8890";
const headers = { Host: "127.0.0.1:8890", Origin: origin, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json" };
const versionId = `deliverable_version_${"a".repeat(32)}`;
const params = { params: Promise.resolve({ projectId: "project_garage", versionId }) };
const body = { slot: "products", content: { notes: "", items: [{ id: "shelf", name: "Wall shelf", quantity: 2, url: "https://example.com/shelf", notes: "" }] }, expected_project_revision: 1, expected_slot_revision: 0, source_version_id: null, associated_task_id: null, expected_task_revision: null };
function request(path: string, method = "GET", value?: unknown) { return new Request(`${origin}${path}`, { method, headers, ...(value === undefined ? {} : { body: JSON.stringify(value) }) }); }

test("every deliverable route has owner admission and exact mutation CSRF", () => {
  for (const [method, path] of Object.values(PROJECT_DELIVERABLE_ROUTES)) {
    const rule = GATEWAY_ROUTE_MANIFEST.find((entry) => entry.method === method && entry.path === path);
    assert.equal(rule?.exposure, "owner_session");
    assert.equal(rule?.csrf, method === "GET" ? "not_required" : "session_bound");
  }
});

test("owner publication binds the Project path and rejects widened or cross-site requests before transport", async () => {
  const calls: unknown[] = [];
  const capability = (async (operation: string, value: unknown) => { calls.push([operation, value]); return { slot: "products", slot_id: `deliverable_${"b".repeat(32)}`, version_id: versionId, revision: 1, origin: "owner_edit", preview_attachment_id: null }; }) as typeof projectDeliverableCapability;
  const handler = createProjectDeliverableHandler("publish", { capability, gatewayPort: "8890" });
  const path = "/api/projects/project_garage/deliverables";
  assert.equal((await handler(request(path, "POST", body), params)).status, 200);
  assert.deepEqual(calls, [["publish", { ...body, project_id: "project_garage" }]]);
  for (const invalid of [{ ...body, project_id: "project_other" }, { ...body, runtime_agent_ref: "default" }, { ...body, expected_slot_revision: true }]) assert.equal((await handler(request(path, "POST", invalid), params)).status, 400);
  assert.equal((await handler(request(`${path}?extra=1`, "POST", body), params)).status, 400);
  assert.equal((await handler(request(path, "GET"), params)).status, 403);
  assert.equal((await handler(new Request(`${origin}${path}`, { method: "POST", headers: { ...headers, Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" }, body: JSON.stringify(body) }), params)).status, 403);
  assert.equal(calls.length, 1);
});

test("preview route returns only sandboxed PNG bytes under exact version selector", async () => {
  const png = Buffer.from("89504e470d0a1a0a", "hex");
  const capability = (async (operation: string, value: unknown) => { assert.equal(operation, "preview"); assert.deepEqual(value, { version_id: versionId }); return { version_id: versionId, content_base64: png.toString("base64"), sha256: "a".repeat(64), byte_size: png.length }; }) as typeof projectDeliverableCapability;
  const handler = createProjectDeliverableHandler("preview", { capability, gatewayPort: "8890" });
  const response = await handler(request(`/api/deliverables/${versionId}/preview`), params);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Content-Type"), "image/png");
  assert.match(response.headers.get("Content-Security-Policy") ?? "", /sandbox/u);
  assert.match(response.headers.get("Cache-Control") ?? "", /no-store/u);
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), png);
});

test("retained history accepts only a fixed bounded page selector", async () => {
  const seen: unknown[] = [];
  const capability = (async (operation: string, value: unknown) => { seen.push([operation, value]); return { versions: [], next_offset: null }; }) as typeof projectDeliverableCapability;
  const handler = createProjectDeliverableHandler("retired-history", { capability, gatewayPort: "8890" });
  assert.equal((await handler(request("/api/deliverables/history?offset=50"), params)).status, 200);
  assert.deepEqual(seen, [["retired-history", { offset: 50 }]]);
  for (const query of ["?offset=51", "?offset=-50", "?offset=50&offset=100", "?path=private"]) {
    assert.equal((await handler(request(`/api/deliverables/history${query}`), params)).status, 400);
  }
  assert.equal(seen.length, 1);
});
