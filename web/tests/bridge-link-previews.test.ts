import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BridgeLinkPreviewError,
  clearBridgeLinkPreviewCache,
  mutateBridgeLinkPreviews,
  readBridgeLinkPreviewImage,
  readBridgeLinkPreviewPreference,
  readBridgeLinkPreviews,
  updateBridgeLinkPreviewPreference,
} from "../src/lib/bridge-link-previews.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:8891", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const conversation = "conv_preview";
const message = "msg_preview";
const ready = {
  schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready",
  conversation_id: conversation, message_id: message, message_revision: 2, enabled: true,
  previews: [{ candidate_ordinal: 2, status: "ready", title: "Safe", display_host: "python.org", image_id: "b".repeat(32) }],
};

function json(value: object, status = 200) { return Response.json(value, { status }); }

test("link preview bridge uses exact identity-only read and mutation paths", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => { calls.push({ url: input.toString(), init }); return json(ready, init?.method === "POST" ? 202 : 200); };
  assert.deepEqual(await readBridgeLinkPreviews(conversation, message, 2, fetcher, environment), ready);
  assert.deepEqual(await mutateBridgeLinkPreviews(conversation, message, 2, "enqueue", fetcher, environment), ready);
  assert.equal(calls[0].url, `http://127.0.0.1:8891/bridge/v1/conversations/${conversation}/messages/${message}/link-previews?revision=2`);
  assert.equal(calls[1].url, `http://127.0.0.1:8891/bridge/v1/conversations/${conversation}/messages/${message}/link-previews`);
  assert.equal(calls[1].init?.body, '{"action":"enqueue","message_revision":2}');
  assert.equal(calls.every((call) => !(call.init?.body as string | undefined)?.includes("url")), true);
});

test("link preview bridge preserves a canonical public IPv6 display host", async () => {
  const ipv6 = { ...ready, previews: [{ ...ready.previews[0], display_host: "2606:4700:4700::1111" }] };
  assert.deepEqual(await readBridgeLinkPreviews(conversation, message, 2, async () => json(ipv6), environment), ipv6);
});

test("link preview bridge rejects private fields malformed states and cross-target payloads", async () => {
  const invalid = [
    { ...ready, message_id: "msg_other" },
    { ...ready, previews: [{ ...ready.previews[0], raw_html: "<secret>" }] },
    { ...ready, previews: [{ candidate_ordinal: 1, status: "ready", display_host: "python.org" }] },
    { ...ready, previews: [{ candidate_ordinal: 2, status: "blocked", title: "leak" }] },
    { ...ready, previews: [{ ...ready.previews[0], image_id: "https://tracker.example/x" }] },
  ];
  for (const payload of invalid) {
    await assert.rejects(() => readBridgeLinkPreviews(conversation, message, 2, async () => json(payload), environment), (error: unknown) => error instanceof BridgeLinkPreviewError && error.code === "bridge_response_invalid");
  }
});

test("preference and clear bridge mutations are exact", async () => {
  const preference = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", enabled: false, revision: 2 };
  const calls: string[] = [];
  const fetcher = async (_input: string | URL | Request, init?: RequestInit) => { calls.push(String(init?.body ?? "GET")); return json(init?.body === "{}" ? { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", cleared: true } : preference); };
  assert.deepEqual(await readBridgeLinkPreviewPreference(fetcher, environment), preference);
  assert.deepEqual(await updateBridgeLinkPreviewPreference(false, 1, fetcher, environment), preference);
  await clearBridgeLinkPreviewCache(fetcher, environment);
  assert.deepEqual(calls, ["GET", '{"enabled":false,"expected_revision":1}', "{}"]);
});

test("opaque image bridge enforces fixed WebP headers bytes and IDs", async () => {
  const imageId = "c".repeat(32);
  const result = await readBridgeLinkPreviewImage(imageId, async (input, init) => {
    assert.equal(input.toString(), `http://127.0.0.1:8891/bridge/v1/link-previews/images/${imageId}`);
    assert.equal(new Headers(init?.headers).get("accept"), "image/webp");
    return new Response(new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "image/webp", "Content-Length": "3", "Cache-Control": "private, max-age=120, no-transform", "X-Content-Type-Options": "nosniff" } });
  }, environment);
  assert.deepEqual(Array.from(result.body), [1, 2, 3]);
  assert.equal(result.maxAge, 120);
  await assert.rejects(() => readBridgeLinkPreviewImage(imageId, async () => new Response(new Uint8Array([1, 2]), { headers: { "Content-Type": "image/webp", "Content-Length": "3", "Cache-Control": "private, max-age=1, no-transform", "X-Content-Type-Options": "nosniff" } }), environment), (error: unknown) => error instanceof BridgeLinkPreviewError && error.code === "bridge_response_invalid");
  await assert.rejects(() => readBridgeLinkPreviewImage("https://example.com/x", async () => { throw new Error("must not fetch"); }, environment), (error: unknown) => error instanceof BridgeLinkPreviewError && error.code === "link_preview_not_found");
});

test("fixed bridge failure states map without internal detail", async () => {
  for (const [status, state, code] of [[400, "invalid", "link_preview_invalid"], [404, "not_found", "link_preview_not_found"], [409, "conflict", "link_preview_conflict"], [429, "capacity_unavailable", "link_preview_capacity_unavailable"], [503, "unavailable", "bridge_unavailable"]] as const) {
    await assert.rejects(() => readBridgeLinkPreviews(conversation, message, 2, async () => json({ schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: state }, status), environment), (error: unknown) => error instanceof BridgeLinkPreviewError && error.code === code);
  }
});
