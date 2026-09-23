import assert from "node:assert/strict";
import test from "node:test";
import { createProjectContextHandler, PROJECT_CONTEXT_ROUTES } from "../src/lib/project-context-route.ts";
import { GATEWAY_ROUTE_MANIFEST } from "../src/lib/gateway-route-manifest.ts";
import type { projectContextCapability } from "../src/lib/bridge-project-context.ts";

const headers = { Host: "127.0.0.1:8890", Origin: "http://127.0.0.1:8890", "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json" };
const contextId = `project_context_${"a".repeat(32)}`;
const attachmentId = `attachment_${"b".repeat(32)}`;
const params = { params: Promise.resolve({ projectId: "project_garage", contextId, attachmentId }) };
function request(path: string, method = "GET", value?: unknown) { return new Request(`http://127.0.0.1:8890${path}`, { method, headers, ...(value === undefined ? {} : { body: JSON.stringify(value) }) }); }

test("every context operation uses owner admission and mutation CSRF", () => {
  for (const [method, path] of Object.values(PROJECT_CONTEXT_ROUTES)) {
    const rule = GATEWAY_ROUTE_MANIFEST.find((item) => item.method === method && item.path === path);
    assert.equal(rule?.exposure, "owner_session"); assert.equal(rule?.csrf, method === "GET" ? "not_required" : "session_bound");
  }
});

test("route binds path selectors, complete staging and exact request before transport", async () => {
  const calls: unknown[] = [];
  const capability = (async (operation: string, value: unknown) => { calls.push([operation, value]); return { context_id: contextId, revision: 1 }; }) as typeof projectContextCapability;
  const handler = createProjectContextHandler("publish", { capability, gatewayPort: "8890" });
  const path = "/api/projects/project_garage/context";
  const body = { expected_project_revision: 1, expected_revision: 0, brief: "Goals", attachment_ids: [], expected_staged_ids: [] };
  assert.equal((await handler(request(path, "POST", body), params)).status, 200);
  assert.deepEqual(calls, [["publish", { ...body, project_id: "project_garage" }]]);
  for (const invalid of [{ ...body, project_id: "project_other" }, { ...body, expected_staged_ids: null }, { ...body, raw_path: "private" }]) assert.equal((await handler(request(path, "POST", invalid), params)).status, 400);
  assert.equal((await handler(request(`${path}?extra=1`, "POST", body), params)).status, 400);
  assert.equal((await handler(request(path, "GET"), params)).status, 403);
  assert.equal((await handler(new Request(`http://127.0.0.1:8890${path}`, { method: "POST", headers: { ...headers, Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" }, body: JSON.stringify(body) }), params)).status, 403);
  assert.equal(calls.length, 1);
});

test("oversized mutation bodies are rejected before private capability", async () => {
  let calls = 0; const capability = (async () => { calls++; }) as unknown as typeof projectContextCapability;
  const handler = createProjectContextHandler("publish", { capability, gatewayPort: "8890" });
  const response = await handler(request("/api/projects/project_garage/context", "POST", { text: "x".repeat(128 * 1024) }), params);
  assert.equal(response.status, 400); assert.equal(calls, 0);
});

test("file route binds version membership and returns downloaded inert text without private JSON", async () => {
  const capability = (async (operation: string, value: unknown) => {
    assert.equal(operation, "file"); assert.deepEqual(value, { context_id: contextId, attachment_id: attachmentId });
    return { file: { name: "floor plan.html", kind: "text", mime_type: "text/html", byte_size: 15 }, content_base64: Buffer.from("<b>floorplan</b>").toString("base64") };
  }) as typeof projectContextCapability;
  const handler = createProjectContextHandler("file", { capability, gatewayPort: "8890" });
  const response = await handler(request(`/api/project-context/${contextId}/files/${attachmentId}`), params);
  assert.equal(response.status, 200); assert.equal(response.headers.get("Content-Type"), "text/plain; charset=utf-8");
  assert.match(response.headers.get("Content-Disposition") ?? "", /^attachment;/u);
  assert.match(response.headers.get("Content-Security-Policy") ?? "", /sandbox/u);
  assert.match(response.headers.get("Cache-Control") ?? "", /no-store/u);
  assert.equal(await response.text(), "<b>floorplan</b>");
});
