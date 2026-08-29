import assert from "node:assert/strict";
import { test } from "node:test";

import {
  PublicConversationMediaError,
  applyContextPack,
  attachWorkspaceFile,
  clearContextPack,
  conversationAttachmentContentUrl,
  listContextPacks,
  readConversationMedia,
  readConversationUploadReceipt,
  readStagedConversationContext,
  releaseConversationAttachment,
  searchWorkspaceFiles,
  uploadConversationAttachment,
} from "../src/lib/public-conversation-media.ts";

const conversationId = "conv_media";
const attachmentId = `attachment_${"a".repeat(32)}`;
const revision = `sha256:${"b".repeat(64)}`;
const uploadId = `upload_${"c".repeat(32)}`;
const envelope = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready" };
const item = { id: attachmentId, name: "a.png", mime_type: "image/png", kind: "image", byte_size: 8, state: "staged", available: true, created_at: "2026-08-29T01:02:03Z", expires_at: "2026-08-29T03:02:03Z" };
const staged = { ...envelope, conversation_id: conversationId, attachments: [{ ...item, source: "upload", ordinal: 0 }], context_pack: null, limits: { direct: 5, total: 8, images: 1 } };

function json(value: object, status = 200): Response { return Response.json(value, { status }); }

test("public staging clients use fixed routes and construct content URLs locally", async () => {
  const calls: Array<{ path: string; init?: RequestInit }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => { calls.push({ path: input.toString(), init }); return json(staged, init?.method === "POST" ? 201 : 200); };
  const state = await readStagedConversationContext(conversationId, fetcher);
  assert.equal(state.attachments[0].contentUrl, `/api/conversations/${conversationId}/attachments/${attachmentId}/content`);
  assert.equal(JSON.stringify(staged).includes("content_url"), false);
  await releaseConversationAttachment(conversationId, attachmentId, fetcher);
  await attachWorkspaceFile(conversationId, "workspace", "docs/a.txt", fetcher);
  await applyContextPack(conversationId, "pack_0123456789abcdef", revision, fetcher);
  await clearContextPack(conversationId, fetcher);
  assert.deepEqual(calls.map((call) => call.path), [
    `/api/conversations/${conversationId}/staged-context`,
    `/api/conversations/${conversationId}/attachments/${attachmentId}/release`,
    `/api/conversations/${conversationId}/workspace-files`,
    `/api/conversations/${conversationId}/context-packs/pack_0123456789abcdef`,
    `/api/conversations/${conversationId}/context-packs/release`,
  ]);
  assert.equal(conversationAttachmentContentUrl(conversationId, attachmentId), state.attachments[0].contentUrl);
  assert.throws(() => conversationAttachmentContentUrl(conversationId, "https://example.com/x"), PublicConversationMediaError);
});

test("browser upload forwards the File directly and supports cancellation", async () => {
  const controller = new AbortController();
  const file = new File(["hello"], "café notes.txt", { type: "text/plain" });
  let init: RequestInit | undefined;
  const result = await uploadConversationAttachment(conversationId, file, uploadId, controller.signal, async (_input, requestInit) => { init = requestInit; return json(staged, 201); });
  assert.equal(result.conversationId, conversationId);
  assert.equal(init?.body, file);
  assert.equal(init?.signal, controller.signal);
  assert.equal(new Headers(init?.headers).get("x-mentat-filename"), "caf%C3%A9%20notes.txt");
  assert.equal(new Headers(init?.headers).get("x-mentat-upload-id"), uploadId);
  assert.equal(new Headers(init?.headers).has("content-length"), false);
  controller.abort();
  await assert.rejects(() => uploadConversationAttachment(conversationId, file, uploadId, controller.signal, async (_input, requestInit) => { throw requestInit?.signal?.reason; }), (error: unknown) => error instanceof PublicConversationMediaError && error.code === "cancelled");

  assert.deepEqual(await readConversationUploadReceipt(conversationId, uploadId, async () => json({ schema_version: 1, status: "ready", conversation_id: conversationId, upload_id: uploadId, state: "staged", attachment_ids: [attachmentId] })), { state: "staged", attachmentIds: [attachmentId] });
});

test("workspace and Context Pack clients accept summaries only", async () => {
  const workspace = { ...envelope, query: "docs", files: [{ root_id: "workspace", path: "docs/a.txt", name: "a.txt", mime_type: "text/plain", kind: "text", byte_size: 5 }] };
  const packs = { ...envelope, context_packs: [{ id: "pack_0123456789abcdef", name: "Review", description: "Summary", revision, item_count: 2 }], max_items: 8 };
  assert.deepEqual(await searchWorkspaceFiles("docs", async () => json(workspace)), { query: "docs", files: [{ rootId: "workspace", path: "docs/a.txt", name: "a.txt", mimeType: "text/plain", kind: "text", byteSize: 5 }] });
  assert.deepEqual(await listContextPacks(async () => json(packs)), { contextPacks: [{ id: "pack_0123456789abcdef", name: "Review", description: "Summary", revision, itemCount: 2 }], maxItems: 8 });
  for (const privateField of ["instructions", "note_paths", "workspace_files"]) {
    const hostile = { ...packs, context_packs: [{ ...packs.context_packs[0], [privateField]: ["private"] }] };
    await assert.rejects(() => listContextPacks(async () => json(hostile)), PublicConversationMediaError);
  }
});

test("media client groups safe items by Run and never trusts a supplied URL", async () => {
  const media = { ...envelope, conversation_id: conversationId, runs: [{ run_id: "run_media", created_at: "2026-08-29T01:02:03Z", inputs: [{ ...item, state: "attached", expires_at: null }], outputs: [] }] };
  const parsed = await readConversationMedia(conversationId, async () => json(media));
  assert.equal(parsed.runs[0].inputs[0].contentUrl, `/api/conversations/${conversationId}/attachments/${attachmentId}/content`);
  const hostile = { ...media, runs: [{ ...media.runs[0], inputs: [{ ...media.runs[0].inputs[0], content_url: "https://attacker.example/x" }] }] };
  await assert.rejects(() => readConversationMedia(conversationId, async () => json(hostile)), PublicConversationMediaError);
});

test("public client rejects oversized, cross-Conversation, and malformed envelopes", async () => {
  for (const payload of [
    { ...staged, conversation_id: "conv_other" },
    { ...staged, attachments: [{ ...staged.attachments[0], byte_size: 10 * 1024 * 1024 + 1 }] },
    { ...staged, attachments: [{ ...staged.attachments[0], state: "missing", available: true }] },
    { ...staged, token: "private" },
  ]) await assert.rejects(() => readStagedConversationContext(conversationId, async () => json(payload)), PublicConversationMediaError);
});
