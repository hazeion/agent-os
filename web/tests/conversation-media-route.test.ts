import assert from "node:assert/strict";
import { test } from "node:test";

import { BridgeConversationMediaError } from "../src/lib/bridge-conversation-media.ts";
import {
  createAttachmentReleaseHandler,
  createAttachmentUploadReceiptHandler,
  createAttachmentUploadHandler,
  createContextPackApplyHandler,
  createContextPackClearHandler,
  createConversationAttachmentContentHandler,
  createConversationMediaHandler,
  createStagedContextHandler,
  createWorkspaceAttachmentHandler,
  createWorkspaceFilesHandler,
} from "../src/lib/conversation-media-route.ts";
import { readRawAttachmentBody } from "../src/lib/raw-attachment-body.ts";

const origin = "http://127.0.0.1:8890";
const mutationHeaders = { Host: "127.0.0.1:8890", Origin: origin };
const conversationContext = { params: Promise.resolve({ conversationId: "conv_media" }) };
const attachmentId = `attachment_${"a".repeat(32)}`;
const attachmentContext = { params: Promise.resolve({ conversationId: "conv_media", attachmentId }) };
const revision = `sha256:${"b".repeat(64)}`;
const uploadId = `upload_${"c".repeat(32)}`;
const staged = { schema_version: 1 as const, service: "mentat-local-bridge" as const, runtime: "python" as const, status: "ready" as const, conversation_id: "conv_media", attachments: [], context_pack: null, limits: { direct: 5 as const, total: 8 as const, images: 1 as const } };

test("raw upload validates exact length, canonical filename, encoding, and deadline", async () => {
  const request = (body: BodyInit, headers: Record<string, string>) => new Request(`${origin}/api/conversations/conv_media/attachments`, { method: "POST", body, headers: { ...mutationHeaders, "Content-Type": "text/plain", ...headers } });
  const valid = await readRawAttachmentBody(request("hello", { "Content-Length": "5", "X-Mentat-Filename": "caf%C3%A9.txt" }));
  assert.equal(new TextDecoder().decode(valid?.body), "hello");
  assert.equal(valid?.encodedFilename, "caf%C3%A9.txt");
  for (const candidate of [
    request("hello", { "Content-Length": "4", "X-Mentat-Filename": "notes.txt" }),
    request("hello", { "Content-Length": "5", "Transfer-Encoding": "chunked", "X-Mentat-Filename": "notes.txt" }),
    request("hello", { "Content-Length": "5", "X-Mentat-Filename": "../secret.txt" }),
    request("hello", { "Content-Length": "5", "X-Mentat-Filename": "%6eotes.txt" }),
  ]) assert.equal(await readRawAttachmentBody(candidate), null);

  const stalled = new Request(`${origin}/api/x`, { method: "POST", headers: { "Content-Type": "text/plain", "Content-Length": "5", "X-Mentat-Filename": "a.txt" }, body: new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode("h")); } }), duplex: "half" } as RequestInit);
  assert.equal(await readRawAttachmentBody(stalled, 20), null);
});

test("upload route rejects cross-origin and malformed raw requests before mutation", async () => {
  const calls: unknown[] = [];
  const handler = createAttachmentUploadHandler({ gatewayPort: "8890", read: async () => staged, upload: async (...args) => { calls.push(args); return staged; } });
  const valid = new Request(`${origin}/api/conversations/conv_media/attachments`, { method: "POST", headers: { ...mutationHeaders, "Content-Type": "text/plain", "Content-Length": "5", "X-Mentat-Filename": "notes.txt", "X-Mentat-Upload-Id": uploadId }, body: "hello" });
  assert.equal((await handler(valid, conversationContext)).status, 201);
  assert.equal((calls[0] as unknown[])[0], "conv_media");
  assert.equal(new TextDecoder().decode((calls[0] as unknown[])[3] as Uint8Array), "hello");
  const crossOrigin = new Request(`${origin}/api/x`, { method: "POST", headers: { ...mutationHeaders, Origin: "http://attacker.example", "Content-Type": "text/plain", "Content-Length": "5", "X-Mentat-Filename": "notes.txt", "X-Mentat-Upload-Id": uploadId }, body: "hello" });
  assert.equal((await handler(crossOrigin, conversationContext)).status, 403);
  const chunked = new Request(`${origin}/api/x`, { method: "POST", headers: { ...mutationHeaders, "Content-Type": "text/plain", "Transfer-Encoding": "chunked", "X-Mentat-Filename": "notes.txt", "X-Mentat-Upload-Id": uploadId }, body: "hello" });
  assert.equal((await handler(chunked, conversationContext)).status, 400);
  assert.equal(calls.length, 1);
});

test("staged-context reconciliation waits for an accepted upload mutation", async () => {
  const uploaded = { ...staged, attachments: [{ id: attachmentId, name: "notes.txt", mime_type: "text/plain", kind: "text" as const, byte_size: 5, state: "staged", available: true, created_at: "2026-08-29T01:02:03Z", expires_at: "2026-08-29T03:02:03Z", source: "upload" as const, ordinal: 0 }] };
  let resolveUpload: ((value: typeof uploaded) => void) | undefined;
  const pendingUpload = new Promise<typeof uploaded>((resolve) => { resolveUpload = resolve; });
  let reads = 0;
  const before = { ...staged, attachments: [] };
  const upload = createAttachmentUploadHandler({ gatewayPort: "8890", read: async () => before, upload: async () => await pendingUpload });
  const read = createStagedContextHandler({ gatewayPort: "8890", read: async () => { reads += 1; return staged; } });
  const uploadRequest = new Request(`${origin}/api/conversations/conv_media/attachments`, { method: "POST", headers: { ...mutationHeaders, "Content-Type": "text/plain", "Content-Length": "5", "X-Mentat-Filename": "notes.txt", "X-Mentat-Upload-Id": uploadId }, body: "hello" });
  const uploadResponse = upload(uploadRequest, conversationContext);
  await new Promise((resolve) => setTimeout(resolve, 0));
  const readResponse = read(new Request(`${origin}/api/conversations/conv_media/staged-context`, { headers: { Host: "127.0.0.1:8890" } }), conversationContext);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(reads, 0);
  resolveUpload?.(uploaded);
  assert.equal((await uploadResponse).status, 201);
  assert.equal((await readResponse).status, 200);
  assert.equal(reads, 1);
  const receipt = createAttachmentUploadReceiptHandler({ gatewayPort: "8890" });
  const receiptResponse = await receipt(new Request(`${origin}/api/x`, { headers: { Host: "127.0.0.1:8890" } }), { params: Promise.resolve({ conversationId: "conv_media", uploadId }) });
  assert.equal(receiptResponse.status, 200);
  assert.deepEqual((await receiptResponse.json() as { attachment_ids: string[] }).attachment_ids, [attachmentId]);
});

test("JSON mutations accept only exact same-origin bodies", async () => {
  const releaseCalls: unknown[] = [];
  const release = createAttachmentReleaseHandler({ gatewayPort: "8890", release: async (...args) => { releaseCalls.push(args); return staged; } });
  assert.equal((await release(new Request(`${origin}/api/x`, { method: "POST", headers: { ...mutationHeaders, "Content-Type": "application/json" }, body: "{}" }), attachmentContext)).status, 200);
  assert.equal((await release(new Request(`${origin}/api/x`, { method: "POST", headers: { ...mutationHeaders, "Content-Type": "application/json" }, body: '{"force":true}' }), attachmentContext)).status, 400);

  const workspaceCalls: unknown[] = [];
  const workspace = createWorkspaceAttachmentHandler({ gatewayPort: "8890", attach: async (...args) => { workspaceCalls.push(args); return staged; } });
  assert.equal((await workspace(new Request(`${origin}/api/x`, { method: "POST", headers: { ...mutationHeaders, "Content-Type": "application/json" }, body: '{"root_id":"workspace","relative_path":"docs/a.txt"}' }), conversationContext)).status, 201);
  assert.equal((await workspace(new Request(`${origin}/api/x`, { method: "POST", headers: { ...mutationHeaders, "Content-Type": "application/json" }, body: '{"root_id":"workspace","relative_path":"../a.txt"}' }), conversationContext)).status, 400);
  assert.deepEqual(workspaceCalls, [["conv_media", "workspace", "docs/a.txt"]]);

  const packCalls: unknown[] = [];
  const pack = createContextPackApplyHandler({ gatewayPort: "8890", apply: async (...args) => { packCalls.push(args); return staged; } });
  const packContext = { params: Promise.resolve({ conversationId: "conv_media", packId: "pack_0123456789abcdef" }) };
  assert.equal((await pack(new Request(`${origin}/api/x`, { method: "POST", headers: { ...mutationHeaders, "Content-Type": "application/json" }, body: `{"expected_revision":"${revision}"}` }), packContext)).status, 201);
  assert.deepEqual(packCalls, [["conv_media", "pack_0123456789abcdef", revision]]);

  const clearCalls: string[] = [];
  const clear = createContextPackClearHandler({ gatewayPort: "8890", clear: async (conversationId) => { clearCalls.push(conversationId); return staged; } });
  assert.equal((await clear(new Request(`${origin}/api/x`, { method: "POST", headers: { ...mutationHeaders, "Content-Type": "application/json" }, body: "{}" }), conversationContext)).status, 200);
  assert.equal((await clear(new Request(`${origin}/api/x`, { method: "POST", headers: { ...mutationHeaders, "Content-Type": "application/json" }, body: '{"force":true}' }), conversationContext)).status, 400);
  assert.deepEqual(clearCalls, ["conv_media"]);
});

test("read routes reject unexpected queries and preserve fixed security headers", async () => {
  const stagedHandler = createStagedContextHandler({ gatewayPort: "8890", read: async () => staged });
  assert.equal((await stagedHandler(new Request(`${origin}/api/x`, { headers: { Host: "127.0.0.1:8890" } }), conversationContext)).status, 200);
  assert.equal((await stagedHandler(new Request(`${origin}/api/x?path=/tmp`, { headers: { Host: "127.0.0.1:8890" } }), conversationContext)).status, 400);

  const searchCalls: string[] = [];
  const search = createWorkspaceFilesHandler({ gatewayPort: "8890", search: async (query) => { searchCalls.push(query); return { ...staged, query, files: [] }; } });
  assert.equal((await search(new Request(`${origin}/api/workspace-files?query=docs`, { headers: { Host: "127.0.0.1:8890" } }))).status, 200);
  assert.equal((await search(new Request(`${origin}/api/workspace-files?query=x&root=/`, { headers: { Host: "127.0.0.1:8890" } }))).status, 400);
  assert.deepEqual(searchCalls, ["docs"]);

  const media = createConversationMediaHandler({ gatewayPort: "8890", read: async () => ({ ...staged, runs: [] }) });
  const response = await media(new Request(`${origin}/api/x`, { headers: { Host: "127.0.0.1:8890" } }), conversationContext);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
});

test("content route returns only exact same-origin bytes with defensive headers", async () => {
  const handler = createConversationAttachmentContentHandler({ gatewayPort: "8890", read: async () => ({ body: new TextEncoder().encode("hello"), contentType: "text/plain; charset=utf-8" }) });
  const response = await handler(new Request(`${origin}/api/x`, { headers: { Host: "127.0.0.1:8890" } }), attachmentContext);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-length"), "5");
  assert.equal(response.headers.get("content-type"), "text/plain; charset=utf-8");
  assert.equal(response.headers.get("content-security-policy"), "sandbox; default-src 'none'; frame-ancestors 'none'");
  assert.equal(response.headers.get("cross-origin-resource-policy"), "same-origin");
  assert.equal(await response.text(), "hello");
  const hostile = createConversationAttachmentContentHandler({ gatewayPort: "8890", read: async () => ({ body: new TextEncoder().encode("<script>"), contentType: "text/html" }) });
  assert.equal((await hostile(new Request(`${origin}/api/x`, { headers: { Host: "127.0.0.1:8890" } }), attachmentContext)).status, 502);
});

test("bridge errors map to fixed public states", async () => {
  const handler = createStagedContextHandler({ gatewayPort: "8890", read: async () => { throw new BridgeConversationMediaError("conversation_media_conflict"); } });
  const response = await handler(new Request(`${origin}/api/x`, { headers: { Host: "127.0.0.1:8890" } }), conversationContext);
  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), { schema_version: 1, status: "conflict" });
});
