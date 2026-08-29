import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BridgeConversationMediaError,
  applyBridgeContextPack,
  attachBridgeWorkspaceFile,
  clearBridgeContextPack,
  readBridgeContextPacks,
  readBridgeConversationAttachmentContent,
  readBridgeConversationMedia,
  readBridgeStagedContext,
  releaseBridgeConversationAttachment,
  searchBridgeWorkspaceFiles,
  uploadBridgeConversationAttachment,
} from "../src/lib/bridge-conversation-media.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:8891", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const conversationId = "conv_media";
const attachmentId = `attachment_${"b".repeat(32)}`;
const runId = "run_media";
const revision = `sha256:${"c".repeat(64)}`;
const envelope = { schema_version: 1 as const, service: "mentat-local-bridge" as const, runtime: "python" as const, status: "ready" as const };
const item = { id: attachmentId, name: "notes.txt", mime_type: "text/plain", kind: "text" as const, byte_size: 5, state: "staged", available: true, created_at: "2026-08-29T01:02:03Z", expires_at: "2026-08-29T03:02:03Z" };
const staged = { ...envelope, conversation_id: conversationId, attachments: [{ ...item, source: "upload" as const, ordinal: 0 }], context_pack: null, limits: { direct: 5 as const, total: 8 as const, images: 1 as const } };

function json(value: object, status = 200): Response { return Response.json(value, { status }); }

test("attachment bridge uses fixed paths and forwards exact bounded raw upload metadata", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => { calls.push({ url: input.toString(), init }); return json(staged, init?.method === "POST" ? 201 : 200); };
  assert.deepEqual(await readBridgeStagedContext(conversationId, fetcher, environment), staged);
  assert.deepEqual(await uploadBridgeConversationAttachment(conversationId, "notes.txt", "text/plain", new TextEncoder().encode("hello"), undefined, fetcher, environment), staged);
  assert.deepEqual(await releaseBridgeConversationAttachment(conversationId, attachmentId, fetcher, environment), staged);
  assert.equal(calls[0].url, `http://127.0.0.1:8891/bridge/v1/conversations/${conversationId}/staged-context`);
  assert.equal(calls[1].url, `http://127.0.0.1:8891/bridge/v1/conversations/${conversationId}/attachments`);
  const uploadHeaders = new Headers(calls[1].init?.headers);
  assert.equal(uploadHeaders.get("content-length"), "5");
  assert.equal(uploadHeaders.get("content-type"), "text/plain");
  assert.equal(uploadHeaders.get("x-mentat-filename"), "notes.txt");
  assert.deepEqual(Array.from(new Uint8Array(calls[1].init?.body as ArrayBuffer)), Array.from(new TextEncoder().encode("hello")));
  assert.equal(calls[2].url, `http://127.0.0.1:8891/bridge/v1/conversations/${conversationId}/attachments/${attachmentId}/release`);
  assert.equal(calls[2].init?.body, "{}");
});

test("workspace and Context Pack bridge capabilities expose only summaries and references", async () => {
  const workspace = { ...envelope, query: "notes", files: [{ root_id: "workspace", path: "docs/notes.txt", name: "notes.txt", mime_type: "text/plain", kind: "text", byte_size: 5 }] };
  const packs = { ...envelope, context_packs: [{ id: "pack_0123456789abcdef", name: "Review", description: "Safe summary", revision, item_count: 2 }], max_items: 8 };
  const calls: Array<{ url: string; body: unknown }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: input.toString(), body: init?.body });
    if (input.toString().includes("workspace-files?")) return json(workspace);
    if (input.toString().endsWith("/context-packs")) return json(packs);
    return json(staged, 201);
  };
  assert.deepEqual(await searchBridgeWorkspaceFiles("notes", fetcher, environment), workspace);
  assert.deepEqual(await readBridgeContextPacks(fetcher, environment), packs);
  await attachBridgeWorkspaceFile(conversationId, "workspace", "docs/notes.txt", fetcher, environment);
  await applyBridgeContextPack(conversationId, "pack_0123456789abcdef", revision, fetcher, environment);
  await clearBridgeContextPack(conversationId, fetcher, environment);
  assert.equal(calls[0].url, "http://127.0.0.1:8891/bridge/v1/workspace-files?query=notes");
  assert.equal(calls[2].body, '{"root_id":"workspace","relative_path":"docs/notes.txt"}');
  assert.equal(calls[3].body, `{"expected_revision":"${revision}"}`);
  assert.equal(calls[4].url, `http://127.0.0.1:8891/bridge/v1/conversations/${conversationId}/context-packs/release`);
  assert.equal(calls[4].body, "{}");
  assert.equal(JSON.stringify(packs).includes("instructions"), false);
  assert.equal(JSON.stringify(packs).includes("relative_path"), false);
});

test("media projection remains grouped by canonical Run and rejects URLs or private fields", async () => {
  const media = { ...envelope, conversation_id: conversationId, runs: [{ run_id: runId, created_at: "2026-08-29T01:02:03Z", inputs: [{ ...item, state: "attached", expires_at: null }], outputs: [] }] };
  assert.deepEqual(await readBridgeConversationMedia(conversationId, async () => json(media), environment), media);
  for (const payload of [
    { ...media, conversation_id: "conv_other" },
    { ...media, runs: [{ ...media.runs[0], inputs: [{ ...media.runs[0].inputs[0], content_url: "/private/x" }] }] },
    { ...media, runs: [{ ...media.runs[0], inputs: [{ ...media.runs[0].inputs[0], storage_key: "aa/hash" }] }] },
    { ...media, runs: [{ ...media.runs[0], outputs: media.runs[0].inputs }] },
  ]) {
    await assert.rejects(() => readBridgeConversationMedia(conversationId, async () => json(payload), environment), (error: unknown) => error instanceof BridgeConversationMediaError && error.code === "bridge_response_invalid");
  }
});

test("content bridge requires approved MIME, exact length, and every security header", async () => {
  const response = () => new Response(new TextEncoder().encode("hello"), { headers: { "Cache-Control": "private, no-store", "Content-Length": "5", "Content-Security-Policy": "default-src 'none'; sandbox", "Content-Type": "text/plain; charset=utf-8", "Cross-Origin-Resource-Policy": "same-origin", "X-Content-Type-Options": "nosniff" } });
  const result = await readBridgeConversationAttachmentContent(conversationId, attachmentId, async (input) => {
    assert.equal(input.toString(), `http://127.0.0.1:8891/bridge/v1/conversations/${conversationId}/attachments/${attachmentId}/content`);
    return response();
  }, environment);
  assert.equal(result.contentType, "text/plain; charset=utf-8");
  assert.equal(new TextDecoder().decode(result.body), "hello");
  for (const headers of [
    { "Cache-Control": "private, no-store", "Content-Length": "4", "Content-Security-Policy": "default-src 'none'; sandbox", "Content-Type": "text/plain; charset=utf-8", "Cross-Origin-Resource-Policy": "same-origin", "X-Content-Type-Options": "nosniff" },
    { "Cache-Control": "private, no-store", "Content-Length": "5", "Content-Security-Policy": "default-src 'none'; sandbox", "Content-Type": "text/html", "Cross-Origin-Resource-Policy": "same-origin", "X-Content-Type-Options": "nosniff" },
    { "Cache-Control": "private, no-store", "Content-Length": "5", "Content-Type": "text/plain; charset=utf-8", "Cross-Origin-Resource-Policy": "same-origin", "X-Content-Type-Options": "nosniff" },
  ]) {
    await assert.rejects(() => readBridgeConversationAttachmentContent(conversationId, attachmentId, async () => new Response(new TextEncoder().encode("hello"), { headers: new Headers(headers as Record<string, string>) }), environment), (error: unknown) => error instanceof BridgeConversationMediaError && error.code === "bridge_response_invalid");
  }
});

test("bridge projections reject extra fields, impossible availability, and unsafe workspace paths", async () => {
  const invalidStaged = [
    { ...staged, attachments: [{ ...staged.attachments[0], path: "/tmp/private" }] },
    { ...staged, attachments: [{ ...staged.attachments[0], state: "missing", available: true }] },
    { ...staged, attachments: [{ ...staged.attachments[0], ordinal: 0 }, { ...staged.attachments[0], id: `attachment_${"d".repeat(32)}`, ordinal: 0 }] },
  ];
  for (const payload of invalidStaged) await assert.rejects(() => readBridgeStagedContext(conversationId, async () => json(payload), environment), BridgeConversationMediaError);
  const badWorkspace = { ...envelope, query: "x", files: [{ root_id: "workspace", path: "../secret", name: "secret", mime_type: "text/plain", kind: "text", byte_size: 1 }] };
  await assert.rejects(() => searchBridgeWorkspaceFiles("x", async () => json(badWorkspace), environment), BridgeConversationMediaError);
});

test("fixed failure envelopes map without forwarding detail", async () => {
  for (const [status, state, code] of [[400, "invalid", "conversation_media_invalid"], [404, "not_found", "conversation_media_not_found"], [409, "conflict", "conversation_media_conflict"], [413, "too_large", "conversation_media_too_large"], [415, "unsupported", "conversation_media_unsupported"], [503, "unavailable", "conversation_media_unavailable"]] as const) {
    await assert.rejects(() => readBridgeStagedContext(conversationId, async () => json({ ...envelope, status: state }, status), environment), (error: unknown) => error instanceof BridgeConversationMediaError && error.code === code);
  }
});
