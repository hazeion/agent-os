import assert from "node:assert/strict";
import { test } from "node:test";

import { PublicLinkPreviewError, clearLinkPreviewCache, readLinkPreviewPreference, readLinkPreviews, requestLinkPreviews, updateLinkPreviewPreference } from "../src/lib/public-link-previews.ts";

const payload = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", conversation_id: "conv_preview", message_id: "msg_preview", message_revision: 2, enabled: true, previews: [{ candidate_ordinal: 1, status: "ready", title: "Safe", display_host: "python.org", image_id: "a".repeat(32) }] };

test("public preview client uses only exact same-origin identity bodies", async () => {
  const calls: Array<{ path: string; init?: RequestInit }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => { calls.push({ path: input.toString(), init }); return Response.json(payload, { status: init?.method === "POST" ? 202 : 200 }); };
  const read = await readLinkPreviews("conv_preview", "msg_preview", 2, fetcher);
  const requested = await requestLinkPreviews("conv_preview", "msg_preview", 2, "retry", fetcher);
  assert.equal(read.previews[0].title, "Safe"); assert.equal(requested.previews[0].imageId, "a".repeat(32));
  assert.equal(calls[0].path, "/api/conversations/conv_preview/messages/msg_preview/link-previews?revision=2");
  assert.equal(calls[1].init?.body, '{"action":"retry","message_revision":2}');
  assert.equal(calls.every((call) => (call.init?.credentials ?? "same-origin") === "same-origin"), true);
});

test("public preview client rejects private fields stale targets and malformed cards", async () => {
  for (const invalid of [
    { ...payload, message_revision: 3 },
    { ...payload, previews: [{ ...payload.previews[0], raw_url: "https://secret.example" }] },
    { ...payload, previews: [{ candidate_ordinal: 1, status: "ready", display_host: "python.org" }] },
    { ...payload, previews: [{ candidate_ordinal: 1, status: "blocked", title: "leak" }] },
  ]) await assert.rejects(() => readLinkPreviews("conv_preview", "msg_preview", 2, async () => Response.json(invalid),), (error: unknown) => error instanceof PublicLinkPreviewError && error.code === "invalid_response");
});

test("public preference and cache clients validate exact results", async () => {
  const preference = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", enabled: true, revision: 1 };
  assert.deepEqual(await readLinkPreviewPreference(async () => Response.json(preference)), { enabled: true, revision: 1 });
  assert.deepEqual(await updateLinkPreviewPreference(false, 1, async () => Response.json({ ...preference, enabled: false, revision: 2 })), { enabled: false, revision: 2 });
  await clearLinkPreviewCache(async (_input, init) => { assert.equal(init?.body, "{}"); return Response.json({ schema_version: 1, status: "ready", cleared: true }); });
});

test("public client maps fixed errors without internal detail", async () => {
  await assert.rejects(() => readLinkPreviews("conv_preview", "msg_preview", 2, async () => Response.json({ schema_version: 1, status: "conflict", detail: "private" }, { status: 409 })), (error: unknown) => error instanceof PublicLinkPreviewError && error.code === "conflict");
});

test("public client bounds declared and streamed response bytes", async () => {
  await assert.rejects(() => readLinkPreviews("conv_preview", "msg_preview", 2, async () => new Response("{}", { headers: { "Content-Type": "application/json", "Content-Length": "999999" } })), (error: unknown) => error instanceof PublicLinkPreviewError && error.code === "invalid_response");
  await assert.rejects(() => readLinkPreviews("conv_preview", "msg_preview", 2, async () => new Response("x".repeat(24_577), { headers: { "Content-Type": "application/json" } })), (error: unknown) => error instanceof PublicLinkPreviewError && error.code === "invalid_response");
});
