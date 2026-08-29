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
import { readRawAttachmentBody } from "./raw-attachment-body.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";

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

function allowed(request: Request, gatewayPort: string | undefined): boolean {
  return evaluateRequestBoundary({
    expectedPort: parseGatewayPort(gatewayPort),
    host: request.headers.get("host"),
    method: request.method,
    origin: request.headers.get("origin"),
    secFetchSite: request.headers.get("sec-fetch-site"),
  }).allowed;
}

function forbidden(): Response {
  return new Response("Forbidden\n", { headers: JSON_HEADERS, status: 403 });
}

type ConversationContext = { params: Promise<{ conversationId: string }> };
type AttachmentContext = { params: Promise<{ conversationId: string; attachmentId: string }> };
type PackContext = { params: Promise<{ conversationId: string; packId: string }> };

export function createStagedContextHandler({
  gatewayPort = process.env.PORT,
  read = readBridgeStagedContext,
}: Readonly<{ gatewayPort?: string; read?: (conversationId: string) => Promise<BridgeStagedContext> }> = {}) {
  return async (request: Request, context: ConversationContext) => {
    if (!allowed(request, gatewayPort)) return forbidden();
    if (new URL(request.url).search) return fixed("invalid", 400);
    const { conversationId } = await context.params;
    try { await waitForConversationMutation(conversationId); return Response.json(await read(conversationId), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
  };
}

export function createAttachmentUploadHandler({
  gatewayPort = process.env.PORT,
  upload = uploadBridgeConversationAttachment,
  read = readBridgeStagedContext,
}: Readonly<{
  gatewayPort?: string;
  upload?: (conversationId: string, encodedFilename: string, contentType: string, body: Uint8Array, signal?: AbortSignal) => Promise<BridgeStagedContext>;
  read?: (conversationId: string) => Promise<BridgeStagedContext>;
}> = {}) {
  return async (request: Request, context: ConversationContext) => {
    if (!allowed(request, gatewayPort)) return forbidden();
    if (new URL(request.url).search) return fixed("invalid", 400);
    const uploadId = request.headers.get("x-mentat-upload-id") ?? "";
    if (!UPLOAD_ID.test(uploadId)) return fixed("invalid", 400);
    const raw = await readRawAttachmentBody(request);
    if (!raw) return fixed("invalid", 400);
    const { conversationId } = await context.params;
    try {
      return Response.json(await runConversationMutation(conversationId, async () => {
        const before = await read(conversationId);
        try {
          const result = await upload(conversationId, raw.encodedFilename, raw.contentType, raw.body);
          storeUploadReceipt(conversationId, uploadId, before, result);
          return result;
        } catch (error) {
          try { storeUploadReceipt(conversationId, uploadId, before, await read(conversationId)); } catch { uploadReceipts.delete(receiptKey(conversationId, uploadId)); }
          throw error;
        }
      }), { headers: JSON_HEADERS, status: 201 });
    } catch (error) { return failure(error); }
  };
}

export function createAttachmentUploadReceiptHandler({ gatewayPort = process.env.PORT }: Readonly<{ gatewayPort?: string }> = {}) {
  return async (request: Request, context: { params: Promise<{ conversationId: string; uploadId: string }> }) => {
    if (!allowed(request, gatewayPort)) return forbidden();
    if (new URL(request.url).search) return fixed("invalid", 400);
    const { conversationId, uploadId } = await context.params;
    if (!UPLOAD_ID.test(uploadId)) return fixed("invalid", 400);
    await waitForConversationMutation(conversationId);
    const receipt = uploadReceipts.get(receiptKey(conversationId, uploadId));
    if (!receipt) return fixed("unavailable", 503);
    return Response.json({ schema_version: 1, status: "ready", conversation_id: conversationId, upload_id: uploadId, state: receipt.state, attachment_ids: [...receipt.attachmentIds] }, { headers: JSON_HEADERS, status: 200 });
  };
}

export function createAttachmentReleaseHandler({
  gatewayPort = process.env.PORT,
  release = releaseBridgeConversationAttachment,
}: Readonly<{ gatewayPort?: string; release?: (conversationId: string, attachmentId: string) => Promise<BridgeStagedContext> }> = {}) {
  return async (request: Request, context: AttachmentContext) => {
    if (!allowed(request, gatewayPort)) return forbidden();
    if (new URL(request.url).search || !await hasExactEmptyJsonBody(request)) return fixed("invalid", 400);
    const { conversationId, attachmentId } = await context.params;
    try { return Response.json(await runConversationMutation(conversationId, () => release(conversationId, attachmentId)), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
  };
}

export function createWorkspaceFilesHandler({
  gatewayPort = process.env.PORT,
  search = searchBridgeWorkspaceFiles,
}: Readonly<{ gatewayPort?: string; search?: (query: string) => Promise<BridgeWorkspaceFiles> }> = {}) {
  return async (request: Request) => {
    if (!allowed(request, gatewayPort)) return forbidden();
    const url = new URL(request.url);
    const values = url.searchParams.getAll("query");
    if ([...url.searchParams.keys()].join(",") !== "query" || values.length !== 1 || values[0].length > 200 || values[0].trim() !== values[0] || values[0].includes("\0")) return fixed("invalid", 400);
    try { return Response.json(await search(values[0]), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
  };
}

export function createWorkspaceAttachmentHandler({
  gatewayPort = process.env.PORT,
  attach = attachBridgeWorkspaceFile,
}: Readonly<{ gatewayPort?: string; attach?: (conversationId: string, rootId: string, relativePath: string) => Promise<BridgeStagedContext> }> = {}) {
  return async (request: Request, context: ConversationContext) => {
    if (!allowed(request, gatewayPort)) return forbidden();
    if (new URL(request.url).search) return fixed("invalid", 400);
    const body = await readWorkspaceAttachmentBody(request);
    if (!body) return fixed("invalid", 400);
    const { conversationId } = await context.params;
    try { return Response.json(await runConversationMutation(conversationId, () => attach(conversationId, body.rootId, body.relativePath)), { headers: JSON_HEADERS, status: 201 }); } catch (error) { return failure(error); }
  };
}

export function createContextPacksHandler({
  gatewayPort = process.env.PORT,
  read = readBridgeContextPacks,
}: Readonly<{ gatewayPort?: string; read?: () => Promise<BridgeContextPacks> }> = {}) {
  return async (request: Request) => {
    if (!allowed(request, gatewayPort)) return forbidden();
    if (new URL(request.url).search) return fixed("invalid", 400);
    try { return Response.json(await read(), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
  };
}

export function createContextPackApplyHandler({
  gatewayPort = process.env.PORT,
  apply = applyBridgeContextPack,
}: Readonly<{ gatewayPort?: string; apply?: (conversationId: string, packId: string, expectedRevision: string) => Promise<BridgeStagedContext> }> = {}) {
  return async (request: Request, context: PackContext) => {
    if (!allowed(request, gatewayPort)) return forbidden();
    if (new URL(request.url).search) return fixed("invalid", 400);
    const body = await readContextPackApplyBody(request);
    if (!body) return fixed("invalid", 400);
    const { conversationId, packId } = await context.params;
    try { return Response.json(await runConversationMutation(conversationId, () => apply(conversationId, packId, body.expectedRevision)), { headers: JSON_HEADERS, status: 201 }); } catch (error) { return failure(error); }
  };
}

export function createContextPackClearHandler({
  gatewayPort = process.env.PORT,
  clear = clearBridgeContextPack,
}: Readonly<{ gatewayPort?: string; clear?: (conversationId: string) => Promise<BridgeStagedContext> }> = {}) {
  return async (request: Request, context: ConversationContext) => {
    if (!allowed(request, gatewayPort)) return forbidden();
    if (new URL(request.url).search || !await hasExactEmptyJsonBody(request)) return fixed("invalid", 400);
    const { conversationId } = await context.params;
    try { return Response.json(await runConversationMutation(conversationId, () => clear(conversationId)), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
  };
}

export function createConversationMediaHandler({
  gatewayPort = process.env.PORT,
  read = readBridgeConversationMedia,
}: Readonly<{ gatewayPort?: string; read?: (conversationId: string) => Promise<BridgeConversationMedia> }> = {}) {
  return async (request: Request, context: ConversationContext) => {
    if (!allowed(request, gatewayPort)) return forbidden();
    if (new URL(request.url).search) return fixed("invalid", 400);
    const { conversationId } = await context.params;
    try { return Response.json(await read(conversationId), { headers: JSON_HEADERS, status: 200 }); } catch (error) { return failure(error); }
  };
}

export function createConversationAttachmentContentHandler({
  gatewayPort = process.env.PORT,
  read = readBridgeConversationAttachmentContent,
}: Readonly<{ gatewayPort?: string; read?: (conversationId: string, attachmentId: string) => Promise<BridgeAttachmentContent> }> = {}) {
  return async (request: Request, context: AttachmentContext) => {
    if (!allowed(request, gatewayPort)) return forbidden();
    if (new URL(request.url).search) return fixed("invalid", 400);
    const { conversationId, attachmentId } = await context.params;
    try {
      const content = await read(conversationId, attachmentId);
      if (!(content.body instanceof Uint8Array) || content.body.byteLength < 1 || content.body.byteLength > MAXIMUM_ATTACHMENT_BYTES || !CONTENT_TYPES.has(content.contentType)) throw new BridgeConversationMediaError("bridge_response_invalid");
      return new Response(content.body.slice().buffer, {
        headers: { ...CONTENT_HEADERS, "Content-Length": String(content.body.byteLength), "Content-Type": content.contentType },
        status: 200,
      });
    } catch (error) { return failure(error); }
  };
}
