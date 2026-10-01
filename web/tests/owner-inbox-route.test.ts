import assert from "node:assert/strict";
import test from "node:test";
import { createOwnerInboxHandler, OWNER_INBOX_ROUTES } from "../src/lib/owner-inbox-route.ts";
import { GATEWAY_ROUTE_MANIFEST } from "../src/lib/gateway-route-manifest.ts";
import type { ownerInboxCapability } from "../src/lib/bridge-owner-inbox.ts";

const origin = "http://127.0.0.1:8890";
const headers = { Host: "127.0.0.1:8890", Origin: origin, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json" };
const itemId = `inbox_item_${"a".repeat(32)}`;
const params = { params: Promise.resolve({ itemId }) };
function request(path: string, method = "GET", value?: unknown) { return new Request(`${origin}${path}`, { method, headers, ...(value === undefined ? {} : { body: JSON.stringify(value) }) }); }

test("every Inbox route is owner-only and mutations require session CSRF", () => {
  for (const [method, path] of Object.values(OWNER_INBOX_ROUTES)) {
    const rule = GATEWAY_ROUTE_MANIFEST.find((item) => item.method === method && item.path === path);
    assert.equal(rule?.exposure, "owner_session");
    assert.equal(rule?.csrf, method === "GET" ? "not_required" : "session_bound");
  }
});

test("Inbox page and item routes bind exact selectors before private transport", async () => {
  const calls: unknown[] = [];
  const capability = (async (operation: string, value: unknown) => { calls.push([operation, value]); return { items: [], next_cursor: null, counts: { needs_me: 0, unread: 0, all: 0 } }; }) as typeof ownerInboxCapability;
  const page = createOwnerInboxHandler("page", { capability, gatewayPort: "8890" });
  assert.equal((await page(request("/api/inbox?view=needs_me"), params)).status, 200);
  assert.deepEqual(calls, [["page", { view: "needs_me", after: null }]]);
  for (const invalid of ["/api/inbox", "/api/inbox?view=all&view=unread", "/api/inbox?view=all&project_id=private", "/api/inbox?view=all&after=../private"])
    assert.equal((await page(request(invalid), params)).status, 400);
  const open = createOwnerInboxHandler("open", { capability, gatewayPort: "8890" });
  assert.equal((await open(request(`/api/inbox/${itemId}`), params)).status, 200);
  assert.deepEqual(calls.at(-1), ["open", { item_id: itemId }]);
  assert.equal((await open(request(`/api/inbox/${itemId}?project=other`), params)).status, 400);
});

test("Inbox review mutation rejects widened, foreign and mismatched item bodies", async () => {
  const calls: unknown[] = [];
  const capability = (async (operation: string, value: unknown) => { calls.push([operation, value]); return { id: itemId, revision: 2, duplicate: false }; }) as typeof ownerInboxCapability;
  const mark = createOwnerInboxHandler("mark", { capability, gatewayPort: "8890" });
  const path = `/api/inbox/${itemId}/mark`, body = { action: "read", expected_revision: 1 };
  assert.equal((await mark(request(path, "POST", body), params)).status, 200);
  assert.deepEqual(calls, [["mark", { ...body, item_id: itemId }]]);
  for (const invalid of [{ ...body, item_id: itemId }, { ...body, runtime_ref: "private" }, { ...body, expected_revision: true }])
    assert.equal((await mark(request(path, "POST", invalid), params)).status, 400);
  assert.equal((await mark(new Request(`${origin}${path}`, { method: "POST", headers: { ...headers, Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" }, body: JSON.stringify(body) }), params)).status, 403);
  assert.equal(calls.length, 1);
});
