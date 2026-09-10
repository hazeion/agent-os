import {
  BridgeConversationMediaError,
  MAXIMUM_ATTACHMENT_BYTES,
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
  type BridgeAttachmentContent,
  type BridgeContextPacks,
  type BridgeConversationMedia,
  type BridgeStagedContext,
  type BridgeWorkspaceFiles,
} from "./bridge-conversation-media.ts";
import { hasExactEmptyJsonBody, readContextPackApplyBody, readWorkspaceAttachmentBody } from "./exact-json-body.ts";
import { createGatewayAuthority, PROCESS_GATEWAY_AUTHORITY } from "./gateway-authority.ts";
import { GATEWAY_ROUTE_MANIFEST } from "./gateway-route-manifest.ts";
import { withGatewayRoute } from "./gateway-request-context.ts";
import { readRawAttachmentBody } from "./raw-attachment-body.ts";

const JSON_HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

const CONTENT_HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Disposition": "inline",
  "Content-Security-Policy": "sandbox; default-src 'none'; frame-ancestors 'none'",
  "Cross-Origin-Resource-Policy": "same-origin",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};
const CONTENT_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp", "text/plain; charset=utf-8"]);
const UPLOAD_ID = /^upload_[0-9a-f]{32}$/u;
const conversationMutations = new Map<string, Promise<void>>();
const uploadReceipts = new Map<string, { attachmentIds: string[]; state: "failed" | "staged" }>();

function receiptKey(conversationId: string, uploadId: string): string { return `${conversationId}:${uploadId}`; }
function storeUploadReceipt(conversationId: string, uploadId: string, before: BridgeStagedContext, after: BridgeStagedContext) {
  const prior = new Set(before.attachments.map((item) => item.id));
  const attachmentIds = after.attachments.filter((item) => !prior.has(item.id)).map((item) => item.id);
  uploadReceipts.delete(receiptKey(conversationId, uploadId));
  uploadReceipts.set(receiptKey(conversationId, uploadId), { attachmentIds, state: attachmentIds.length ? "staged" : "failed" });
  while (uploadReceipts.size > 256) uploadReceipts.delete(uploadReceipts.keys().next().value as string);
}

async function runConversationMutation<T>(conversationId: string, operation: () => Promise<T>): Promise<T> {
  const prior = conversationMutations.get(conversationId) ?? Promise.resolve();
  const result = prior.catch(() => undefined).then(operation);
  const terminal = result.then(() => undefined, () => undefined);
  conversationMutations.set(conversationId, terminal);
  try { return await result; } finally { if (conversationMutations.get(conversationId) === terminal) conversationMutations.delete(conversationId); }
}

async function waitForConversationMutation(conversationId: string): Promise<void> {
  await (conversationMutations.get(conversationId) ?? Promise.resolve());
}

function fixed(status: string, code: number): Response {
  return Response.json({ schema_version: 1, status }, { headers: JSON_HEADERS, status: code });
}

function failure(error: unknown): Response {
  if (!(error instanceof BridgeConversationMediaError)) return fixed("error", 502);
  const mapped: Record<string, [string, number]> = {
    bridge_unavailable: ["unavailable", 503],
    conversation_media_cancelled: ["cancelled", 499],
    conversation_media_capacity_unavailable: ["capacity_unavailable", 429],
    conversation_media_conflict: ["conflict", 409],
    conversation_media_gone: ["gone", 410],
    conversation_media_invalid: ["invalid", 400],
    conversation_media_not_found: ["not_found", 404],
    conversation_media_too_large: ["too_large", 413],
    conversation_media_unsupported: ["unsupported", 415],
    conversation_media_unavailable: ["unavailable", 503],
  };
  const result = mapped[error.code];
  return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

type ConversationContext = { params: Promise<{ conversationId: string }> };
type AttachmentContext = { params: Promise<{ conversationId: string; attachmentId: string }> };
type PackContext = { params: Promise<{ conversationId: string; packId: string }> };
type UploadContext = { params: Promise<{ conversationId: string; uploadId: string }> };

const STAGED_CONTEXT_RULE = requiredRule("GET", "/api/conversations/[conversationId]/staged-context");
const ATTACHMENT_UPLOAD_RULE = requiredRule("POST", "/api/conversations/[conversationId]/attachments");
const ATTACHMENT_RECEIPT_RULE = requiredRule("GET", "/api/conversations/[conversationId]/uploads/[uploadId]");
const ATTACHMENT_RELEASE_RULE = requiredRule("POST", "/api/conversations/[conversationId]/attachments/[attachmentId]/release");
const WORKSPACE_FILES_RULE = requiredRule("GET", "/api/workspace-files");
const WORKSPACE_ATTACHMENT_RULE = requiredRule("POST", "/api/conversations/[conversationId]/workspace-files");
const CONTEXT_PACKS_RULE = requiredRule("GET", "/api/context-packs");
const CONTEXT_PACK_APPLY_RULE = requiredRule("POST", "/api/conversations/[conversationId]/context-packs/[packId]");
const CONTEXT_PACK_CLEAR_RULE = requiredRule("POST", "/api/conversations/[conversationId]/context-packs/release");
const CONVERSATION_MEDIA_RULE = requiredRule("GET", "/api/conversations/[conversationId]/media");
const ATTACHMENT_CONTENT_RULE = requiredRule("GET", "/api/conversations/[conversationId]/attachments/[attachmentId]/content");

function requiredRule(method: "GET" | "POST", path: string) {
  const rule = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === method && candidate.path === path);
  if (!rule) throw new Error(`missing gateway manifest rule for ${method} ${path}`);
  return rule;
}

function authority(gatewayPort: string | undefined) {
  return gatewayPort === undefined ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}

export function createStagedContextHandler({
  gatewayPort,
  read = readBridgeStagedContext,
}: Readonly<{ gatewayPort?: string; read?: (conversationId: string) => Promise<BridgeStagedContext> }> = {}) {
  return withGatewayRoute<string | null, ConversationContext>(STAGED_CONTEXT_RULE, {
    authority: authority(gatewayPort),
    handler: async ({ value: conversationId }) => {
      if (!conversationId) return fixed("invalid", 400);
      try { await waitForConversationMutation(conversationId); return Response.json(await read(conversationId), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        return (await context.params).conversationId;
      },
    },
  });
}

export function createAttachmentUploadHandler({
  gatewayPort,
  upload = uploadBridgeConversationAttachment,
  read = readBridgeStagedContext,
}: Readonly<{
  gatewayPort?: string;
  upload?: (conversationId: string, encodedFilename: string, contentType: string, body: Uint8Array, signal?: AbortSignal) => Promise<BridgeStagedContext>;
  read?: (conversationId: string) => Promise<BridgeStagedContext>;
}> = {}) {
  type UploadInput = { conversationId: string; raw: NonNullable<Awaited<ReturnType<typeof readRawAttachmentBody>>>; uploadId: string } | null;
  return withGatewayRoute<UploadInput, ConversationContext>(ATTACHMENT_UPLOAD_RULE, {
    authority: authority(gatewayPort),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try {
        return Response.json(await runConversationMutation(value.conversationId, async () => {
          const before = await read(value.conversationId);
          try {
            const result = await upload(value.conversationId, value.raw.encodedFilename, value.raw.contentType, value.raw.body);
            storeUploadReceipt(value.conversationId, value.uploadId, before, result);
            return result;
          } catch (error) {
            try { storeUploadReceipt(value.conversationId, value.uploadId, before, await read(value.conversationId)); } catch { uploadReceipts.delete(receiptKey(value.conversationId, value.uploadId)); }
            throw error;
          }
        }), { headers: JSON_HEADERS, status: 201 });
      } catch (error) { return failure(error); }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        const uploadId = request.headers.get("x-mentat-upload-id") ?? "";
        if (!UPLOAD_ID.test(uploadId)) return null;
        const raw = await readRawAttachmentBody(request);
        if (!raw) return null;
        return { conversationId: (await context.params).conversationId, raw, uploadId };
      },
    },
  });
}

export function createAttachmentUploadReceiptHandler({ gatewayPort }: Readonly<{ gatewayPort?: string }> = {}) {
  type ReceiptInput = { conversationId: string; uploadId: string } | null;
  return withGatewayRoute<ReceiptInput, UploadContext>(ATTACHMENT_RECEIPT_RULE, {
    authority: authority(gatewayPort),
    handler: async ({ value }) => {
    if (!value) return fixed("invalid", 400);
    await waitForConversationMutation(value.conversationId);
    const receipt = uploadReceipts.get(receiptKey(value.conversationId, value.uploadId));
    if (!receipt) return fixed("unavailable", 503);
    return Response.json({ schema_version: 1, status: "ready", conversation_id: value.conversationId, upload_id: value.uploadId, state: receipt.state, attachment_ids: [...receipt.attachmentIds] }, { headers: JSON_HEADERS, status: 200 });
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        const { conversationId, uploadId } = await context.params;
        return UPLOAD_ID.test(uploadId) ? { conversationId, uploadId } : null;
      },
    },
  });
}

export function createAttachmentReleaseHandler({
  gatewayPort,
  release = releaseBridgeConversationAttachment,
}: Readonly<{ gatewayPort?: string; release?: (conversationId: string, attachmentId: string) => Promise<BridgeStagedContext> }> = {}) {
  type ReleaseInput = { attachmentId: string; conversationId: string } | null;
  return withGatewayRoute<ReleaseInput, AttachmentContext>(ATTACHMENT_RELEASE_RULE, {
    authority: authority(gatewayPort),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try { return Response.json(await runConversationMutation(value.conversationId, () => release(value.conversationId, value.attachmentId)), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search || !await hasExactEmptyJsonBody(request)) return null;
        return await context.params;
      },
    },
  });
}

export function createWorkspaceFilesHandler({
  gatewayPort,
  search = searchBridgeWorkspaceFiles,
}: Readonly<{ gatewayPort?: string; search?: (query: string) => Promise<BridgeWorkspaceFiles> }> = {}) {
  return withGatewayRoute<string | null>(WORKSPACE_FILES_RULE, {
    authority: authority(gatewayPort),
    handler: async ({ value: query }) => {
      if (query === null) return fixed("invalid", 400);
      try { return Response.json(await search(query), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
    validator: {
      validate(request) {
        const url = new URL(request.url);
        const values = url.searchParams.getAll("query");
        return [...url.searchParams.keys()].join(",") !== "query" || values.length !== 1 || values[0].length > 200 || values[0].trim() !== values[0] || values[0].includes("\0") ? null : values[0];
      },
    },
  });
}

export function createWorkspaceAttachmentHandler({
  gatewayPort,
  attach = attachBridgeWorkspaceFile,
}: Readonly<{ gatewayPort?: string; attach?: (conversationId: string, rootId: string, relativePath: string) => Promise<BridgeStagedContext> }> = {}) {
  type WorkspaceInput = { body: NonNullable<Awaited<ReturnType<typeof readWorkspaceAttachmentBody>>>; conversationId: string } | null;
  return withGatewayRoute<WorkspaceInput, ConversationContext>(WORKSPACE_ATTACHMENT_RULE, {
    authority: authority(gatewayPort),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try { return Response.json(await runConversationMutation(value.conversationId, () => attach(value.conversationId, value.body.rootId, value.body.relativePath)), { headers: JSON_HEADERS, status: 201 }); } catch (error) { return failure(error); }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        const body = await readWorkspaceAttachmentBody(request);
        return body ? { body, conversationId: (await context.params).conversationId } : null;
      },
    },
  });
}

export function createContextPacksHandler({
  gatewayPort,
  read = readBridgeContextPacks,
}: Readonly<{ gatewayPort?: string; read?: () => Promise<BridgeContextPacks> }> = {}) {
  return withGatewayRoute<boolean>(CONTEXT_PACKS_RULE, {
    authority: authority(gatewayPort),
    handler: async ({ value: valid }) => {
      if (!valid) return fixed("invalid", 400);
      try { return Response.json(await read(), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
    validator: { validate: (request) => !new URL(request.url).search },
  });
}

export function createContextPackApplyHandler({
  gatewayPort,
  apply = applyBridgeContextPack,
}: Readonly<{ gatewayPort?: string; apply?: (conversationId: string, packId: string, expectedRevision: string) => Promise<BridgeStagedContext> }> = {}) {
  type PackInput = { conversationId: string; expectedRevision: string; packId: string } | null;
  return withGatewayRoute<PackInput, PackContext>(CONTEXT_PACK_APPLY_RULE, {
    authority: authority(gatewayPort),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try { return Response.json(await runConversationMutation(value.conversationId, () => apply(value.conversationId, value.packId, value.expectedRevision)), { headers: JSON_HEADERS, status: 201 }); } catch (error) { return failure(error); }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        const body = await readContextPackApplyBody(request);
        if (!body) return null;
        const { conversationId, packId } = await context.params;
        return { conversationId, expectedRevision: body.expectedRevision, packId };
      },
    },
  });
}

export function createContextPackClearHandler({
  gatewayPort,
  clear = clearBridgeContextPack,
}: Readonly<{ gatewayPort?: string; clear?: (conversationId: string) => Promise<BridgeStagedContext> }> = {}) {
  return withGatewayRoute<string | null, ConversationContext>(CONTEXT_PACK_CLEAR_RULE, {
    authority: authority(gatewayPort),
    handler: async ({ value: conversationId }) => {
      if (!conversationId) return fixed("invalid", 400);
      try { return Response.json(await runConversationMutation(conversationId, () => clear(conversationId)), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search || !await hasExactEmptyJsonBody(request)) return null;
        return (await context.params).conversationId;
      },
    },
  });
}

export function createConversationMediaHandler({
  gatewayPort,
  read = readBridgeConversationMedia,
}: Readonly<{ gatewayPort?: string; read?: (conversationId: string) => Promise<BridgeConversationMedia> }> = {}) {
  return withGatewayRoute<string | null, ConversationContext>(CONVERSATION_MEDIA_RULE, {
    authority: authority(gatewayPort),
    handler: async ({ value: conversationId }) => {
      if (!conversationId) return fixed("invalid", 400);
      try { return Response.json(await read(conversationId), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        return (await context.params).conversationId;
      },
    },
  });
}

export function createConversationAttachmentContentHandler({
  gatewayPort,
  read = readBridgeConversationAttachmentContent,
}: Readonly<{ gatewayPort?: string; read?: (conversationId: string, attachmentId: string) => Promise<BridgeAttachmentContent> }> = {}) {
  type ContentInput = { attachmentId: string; conversationId: string } | null;
  return withGatewayRoute<ContentInput, AttachmentContext>(ATTACHMENT_CONTENT_RULE, {
    authority: authority(gatewayPort),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try {
        const content = await read(value.conversationId, value.attachmentId);
        if (!(content.body instanceof Uint8Array) || content.body.byteLength < 1 || content.body.byteLength > MAXIMUM_ATTACHMENT_BYTES || !CONTENT_TYPES.has(content.contentType)) throw new BridgeConversationMediaError("bridge_response_invalid");
        return new Response(content.body.slice().buffer, {
          headers: { ...CONTENT_HEADERS, "Content-Length": String(content.body.byteLength), "Content-Type": content.contentType },
          status: 200,
        });
      } catch (error) { return failure(error); }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        return await context.params;
      },
    },
  });
}
