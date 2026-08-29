import assert from "node:assert/strict";
import { test } from "node:test";

import { BridgeLinkPreviewError } from "../src/lib/bridge-link-previews.ts";
import { createLinkPreviewCacheClearHandler, createLinkPreviewImageHandler, createLinkPreviewMessageHandlers, createLinkPreviewPreferenceHandlers } from "../src/lib/link-preview-route.ts";

const origin = "http://127.0.0.1:8890";
const headers = { Host: "127.0.0.1:8890", Origin: origin, "Content-Type": "application/json" };
const context = { params: Promise.resolve({ conversationId: "conv_preview", messageId: "msg_preview" }) };
const payload = { schema_version: 1 as const, service: "mentat-local-bridge" as const, runtime: "python" as const, status: "ready" as const, conversation_id: "conv_preview", message_id: "msg_preview", message_revision: 2, enabled: true, previews: [] };

test("message preview routes enforce exact query bodies and same origin", async () => {
  const calls: unknown[] = [];
  const handlers = createLinkPreviewMessageHandlers({ gatewayPort: "8890", read: async (...args) => { calls.push(args); return payload; }, mutate: async (...args) => { calls.push(args); return payload; } });
  assert.equal((await handlers.GET(new Request(`${origin}/api/x?revision=2`, { headers: { Host: "127.0.0.1:8890" } }), context)).status, 200);
  assert.equal((await handlers.POST(new Request(`${origin}/api/x`, { method: "POST", headers, body: '{"action":"retry","message_revision":2}' }), context)).status, 202);
  assert.deepEqual(calls, [["conv_preview", "msg_preview", 2], ["conv_preview", "msg_preview", 2, "retry"]]);
  assert.equal((await handlers.GET(new Request(`${origin}/api/x?revision=2&url=https://example.com`, { headers: { Host: "127.0.0.1:8890" } }), context)).status, 400);
  assert.equal((await handlers.POST(new Request(`${origin}/api/x`, { method: "POST", headers, body: '{"action":"retry","message_revision":2,"url":"https://example.com"}' }), context)).status, 400);
  assert.equal((await handlers.POST(new Request(`${origin}/api/x`, { method: "POST", headers: { ...headers, Origin: "http://attacker.example" }, body: '{"action":"retry","message_revision":2}' }), context)).status, 403);
});

test("preference, clear, and image routes retain fixed boundaries", async () => {
  const preference = { schema_version: 1 as const, service: "mentat-local-bridge" as const, runtime: "python" as const, status: "ready" as const, enabled: true, revision: 1 };
  const pref = createLinkPreviewPreferenceHandlers({ gatewayPort: "8890", read: async () => preference, update: async () => ({ ...preference, enabled: false, revision: 2 }) });
  assert.equal((await pref.GET(new Request(`${origin}/api/link-previews/preference`, { headers: { Host: "127.0.0.1:8890" } }))).status, 200);
  assert.equal((await pref.POST(new Request(`${origin}/api/link-previews/preference`, { method: "POST", headers, body: '{"enabled":false,"expected_revision":1}' }))).status, 200);
  assert.equal((await pref.POST(new Request(`${origin}/api/link-previews/preference`, { method: "POST", headers, body: '{"enabled":false,"expected_revision":1,"url":"x"}' }))).status, 400);

  let cleared = 0; const clear = createLinkPreviewCacheClearHandler({ gatewayPort: "8890", clear: async () => { cleared += 1; } });
  assert.equal((await clear(new Request(`${origin}/api/link-previews/cache/clear`, { method: "POST", headers, body: "{}" }))).status, 200);
  assert.equal(cleared, 1);

  const image = createLinkPreviewImageHandler({ gatewayPort: "8890", read: async () => ({ body: new Uint8Array([1, 2]), maxAge: 120 }) });
  const response = await image(new Request(`${origin}/api/link-previews/images/${"a".repeat(32)}`, { headers: { Host: "127.0.0.1:8890" } }), { params: Promise.resolve({ imageId: "a".repeat(32) }) });
  assert.equal(response.status, 200); assert.equal(response.headers.get("content-type"), "image/webp"); assert.equal(response.headers.get("content-length"), "2");
});

test("route errors map to fixed public states", async () => {
  const handlers = createLinkPreviewMessageHandlers({ gatewayPort: "8890", read: async () => { throw new BridgeLinkPreviewError("link_preview_conflict"); } });
  const response = await handlers.GET(new Request(`${origin}/api/x?revision=2`, { headers: { Host: "127.0.0.1:8890" } }), context);
  assert.equal(response.status, 409); assert.deepEqual(await response.json(), { schema_version: 1, status: "conflict" });
});
