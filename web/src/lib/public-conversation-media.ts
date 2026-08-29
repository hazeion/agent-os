const MAXIMUM_JSON_BYTES = 1_500_000;
const MAXIMUM_ATTACHMENT_BYTES = 10 * 1024 * 1024;
const CONVERSATION_ID = /^conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u;
const ATTACHMENT_ID = /^attachment_[0-9a-f]{32}$/u;
const RUN_ID = /^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/u;
const PACK_ID = /^pack_[0-9a-f]{16}$/u;
const REVISION = /^sha256:[0-9a-f]{64}$/u;
const UPLOAD_ID = /^upload_[0-9a-f]{32}$/u;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u;
const CONTROL = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u;
const STATES = new Set(["staged", "attached", "orphaned", "pending_delete", "missing"]);
const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
const TEXT_TYPES = new Set([
  "text/plain", "text/markdown", "text/x-python", "text/javascript", "text/typescript", "application/json",
  "application/javascript", "application/x-javascript", "application/x-ndjson", "text/css", "text/html", "application/xml", "application/yaml", "application/toml", "text/csv",
  "text/tab-separated-values", "application/sql", "text/x-c", "text/x-c++", "text/x-java-source", "text/x-go",
  "text/x-rust", "text/x-ruby", "text/x-php", "text/x-swift", "text/x-kotlin", "text/x-csharp", "text/x-diff",
]);

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export type ConversationMediaItem = {
  id: string;
  name: string;
  mimeType: string;
  kind: "image" | "text";
  byteSize: number;
  state: string;
  available: boolean;
  createdAt: string | null;
  expiresAt: string | null;
  contentUrl: string | null;
};

export type StagedConversationItem = ConversationMediaItem & {
  source: "upload" | "workspace" | "context_pack";
  ordinal: number;
};

export type StagedConversationContext = {
  conversationId: string;
  attachments: StagedConversationItem[];
  contextPack: { id: string; name: string; revision: string } | null;
  limits: { direct: 5; total: 8; images: 1 };
};

export type WorkspaceFile = { rootId: string; path: string; name: string; mimeType: string; kind: "image" | "text"; byteSize: number };
export type ContextPackSummary = { id: string; name: string; description: string; revision: string; itemCount: number };
export type ConversationMedia = { conversationId: string; runs: Array<{ runId: string; createdAt: string; inputs: ConversationMediaItem[]; outputs: ConversationMediaItem[] }> };

export class PublicConversationMediaError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.code = code;
    this.name = "PublicConversationMediaError";
  }
}

function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function keys(value: Record<string, unknown>, expected: string): boolean { return Object.keys(value).sort().join(",") === expected; }
function text(value: unknown, maximum: number, empty = false): value is string { return typeof value === "string" && (empty || value.length > 0) && [...value].length <= maximum && value.trim() === value && !CONTROL.test(value); }
function timestamp(value: unknown): value is string { return typeof value === "string" && value.length <= 40 && TIMESTAMP.test(value) && !Number.isNaN(Date.parse(value)); }
function envelope(value: Record<string, unknown>): boolean { return value.schema_version === 1 && value.service === "mentat-local-bridge" && value.runtime === "python" && value.status === "ready"; }
function validMime(value: unknown, kind: unknown): value is string { return typeof value === "string" && (kind === "image" ? IMAGE_TYPES.has(value) : kind === "text" && TEXT_TYPES.has(value)); }

function contentUrl(conversationId: string, attachmentId: string): string {
  if (!CONVERSATION_ID.test(conversationId) || !ATTACHMENT_ID.test(attachmentId)) throw new PublicConversationMediaError("invalid");
  return `/api/conversations/${encodeURIComponent(conversationId)}/attachments/${attachmentId}/content`;
}

export function conversationAttachmentContentUrl(conversationId: string, attachmentId: string): string {
  return contentUrl(conversationId, attachmentId);
}

function mediaItem(value: unknown, conversationId: string): ConversationMediaItem | null {
  if (!record(value) || !keys(value, "available,byte_size,created_at,expires_at,id,kind,mime_type,name,state")) return null;
  if (
    typeof value.id !== "string" || !ATTACHMENT_ID.test(value.id)
    || !text(value.name, 255)
    || value.kind !== "image" && value.kind !== "text"
    || !validMime(value.mime_type, value.kind)
    || !Number.isSafeInteger(value.byte_size) || (value.byte_size as number) < 1 || (value.byte_size as number) > MAXIMUM_ATTACHMENT_BYTES
    || typeof value.state !== "string" || !STATES.has(value.state)
    || typeof value.available !== "boolean" || value.available && value.state !== "staged" && value.state !== "attached"
    || value.created_at !== null && !timestamp(value.created_at)
    || value.expires_at !== null && !timestamp(value.expires_at)
  ) return null;
  return {
    id: value.id,
    name: value.name,
    mimeType: value.mime_type as string,
    kind: value.kind,
    byteSize: value.byte_size as number,
    state: value.state,
    available: value.available,
    createdAt: value.created_at as string | null,
    expiresAt: value.expires_at as string | null,
    contentUrl: value.available ? contentUrl(conversationId, value.id) : null,
  };
}

function parseStaged(value: unknown, conversationId: string): StagedConversationContext {
  if (!record(value) || !keys(value, "attachments,context_pack,conversation_id,limits,runtime,schema_version,service,status") || !envelope(value) || value.conversation_id !== conversationId || !Array.isArray(value.attachments) || value.attachments.length > 8) throw new PublicConversationMediaError("invalid_response");
  const attachments = value.attachments.map((item): StagedConversationItem | null => {
    if (!record(item) || !keys(item, "available,byte_size,created_at,expires_at,id,kind,mime_type,name,ordinal,source,state")) return null;
    const base = Object.fromEntries(Object.entries(item).filter(([key]) => key !== "source" && key !== "ordinal"));
    const parsed = mediaItem(base, conversationId);
    if (!parsed || !["upload", "workspace", "context_pack"].includes(String(item.source)) || !Number.isInteger(item.ordinal) || (item.ordinal as number) < 0 || (item.ordinal as number) > 7) return null;
    return { ...parsed, source: item.source as StagedConversationItem["source"], ordinal: item.ordinal as number };
  });
  if (attachments.some((item) => item === null)) throw new PublicConversationMediaError("invalid_response");
  const ready = attachments as StagedConversationItem[];
  if (new Set(ready.map((item) => item.id)).size !== ready.length || ready.some((item, index) => index > 0 && ready[index - 1].ordinal >= item.ordinal) || ready.filter((item) => item.source !== "context_pack").length > 5 || ready.filter((item) => item.kind === "image").length > 1) throw new PublicConversationMediaError("invalid_response");
  let contextPack: StagedConversationContext["contextPack"] = null;
  if (value.context_pack !== null) {
    if (!record(value.context_pack) || !keys(value.context_pack, "id,name,revision") || typeof value.context_pack.id !== "string" || !PACK_ID.test(value.context_pack.id) || !text(value.context_pack.name, 80) || typeof value.context_pack.revision !== "string" || !REVISION.test(value.context_pack.revision)) throw new PublicConversationMediaError("invalid_response");
    contextPack = { id: value.context_pack.id, name: value.context_pack.name, revision: value.context_pack.revision };
  }
  if (ready.some((item) => item.source === "context_pack") && contextPack === null || !record(value.limits) || !keys(value.limits, "direct,images,total") || value.limits.direct !== 5 || value.limits.total !== 8 || value.limits.images !== 1) throw new PublicConversationMediaError("invalid_response");
  return { conversationId, attachments: ready.map((item) => ({ ...item })), contextPack, limits: { direct: 5, total: 8, images: 1 } };
}

async function boundedJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_JSON_BYTES)) throw new PublicConversationMediaError("invalid_response");
  if (!response.body) throw new PublicConversationMediaError("invalid_response");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > MAXIMUM_JSON_BYTES) { await reader.cancel(); throw new PublicConversationMediaError("invalid_response"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  if (declared && bytes.byteLength !== Number(declared)) throw new PublicConversationMediaError("invalid_response");
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); } catch { throw new PublicConversationMediaError("invalid_response"); }
}

async function request(path: string, init: RequestInit, fetcher: FetchLike): Promise<unknown> {
  let response: Response;
  try { response = await fetcher(path, { cache: "no-store", redirect: "error", ...init }); } catch { if (init.signal?.aborted) throw new PublicConversationMediaError("cancelled"); throw new PublicConversationMediaError("unavailable"); }
  if (response.headers.get("content-type")?.toLowerCase() !== "application/json") throw new PublicConversationMediaError("invalid_response");
  const value = await boundedJson(response);
  if (!response.ok) {
    const status = record(value) && typeof value.status === "string" ? value.status : "invalid_response";
    throw new PublicConversationMediaError(status);
  }
  return value;
}

function conversationPath(conversationId: string): string {
  if (!CONVERSATION_ID.test(conversationId)) throw new PublicConversationMediaError("invalid");
  return `/api/conversations/${encodeURIComponent(conversationId)}`;
}

export async function readStagedConversationContext(conversationId: string, fetcher: FetchLike = fetch): Promise<StagedConversationContext> {
  return parseStaged(await request(`${conversationPath(conversationId)}/staged-context`, { method: "GET" }, fetcher), conversationId);
}

export async function uploadConversationAttachment(conversationId: string, file: Blob & { name: string }, uploadId: string, signal?: AbortSignal, fetcher: FetchLike = fetch): Promise<StagedConversationContext> {
  if (!text(file?.name, 255) || file.size < 1 || file.size > MAXIMUM_ATTACHMENT_BYTES || !UPLOAD_ID.test(uploadId)) throw new PublicConversationMediaError("invalid");
  const contentType = file.type.trim().toLowerCase() || "application/octet-stream";
  const value = await request(`${conversationPath(conversationId)}/attachments`, { method: "POST", headers: { "Content-Type": contentType, "X-Mentat-Filename": encodeURIComponent(file.name), "X-Mentat-Upload-Id": uploadId }, body: file, signal }, fetcher);
  return parseStaged(value, conversationId);
}

export async function readConversationUploadReceipt(conversationId: string, uploadId: string, fetcher: FetchLike = fetch): Promise<{ state: "failed" | "staged"; attachmentIds: string[] }> {
  if (!UPLOAD_ID.test(uploadId)) throw new PublicConversationMediaError("invalid");
  const value = await request(`${conversationPath(conversationId)}/uploads/${uploadId}`, { method: "GET" }, fetcher);
  if (!record(value) || !keys(value, "attachment_ids,conversation_id,schema_version,state,status,upload_id") || value.schema_version !== 1 || value.status !== "ready" || value.conversation_id !== conversationId || value.upload_id !== uploadId || value.state !== "failed" && value.state !== "staged" || !Array.isArray(value.attachment_ids) || value.attachment_ids.length > 8 || !value.attachment_ids.every((item) => typeof item === "string" && ATTACHMENT_ID.test(item)) || new Set(value.attachment_ids).size !== value.attachment_ids.length || value.state === "failed" && value.attachment_ids.length !== 0 || value.state === "staged" && value.attachment_ids.length === 0) throw new PublicConversationMediaError("invalid_response");
  return { state: value.state, attachmentIds: [...value.attachment_ids] };
}

export async function releaseConversationAttachment(conversationId: string, attachmentId: string, fetcher: FetchLike = fetch): Promise<StagedConversationContext> {
  if (!ATTACHMENT_ID.test(attachmentId)) throw new PublicConversationMediaError("invalid");
  return parseStaged(await request(`${conversationPath(conversationId)}/attachments/${attachmentId}/release`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, fetcher), conversationId);
}

export async function searchWorkspaceFiles(query: string, fetcher: FetchLike = fetch): Promise<{ query: string; files: WorkspaceFile[] }> {
  if (!text(query, 200, true)) throw new PublicConversationMediaError("invalid");
  const value = await request(`/api/workspace-files?query=${encodeURIComponent(query)}`, { method: "GET" }, fetcher);
  if (!record(value) || !keys(value, "files,query,runtime,schema_version,service,status") || !envelope(value) || value.query !== query || !Array.isArray(value.files) || value.files.length > 50) throw new PublicConversationMediaError("invalid_response");
  const files = value.files.map((item): WorkspaceFile | null => {
    if (!record(item) || !keys(item, "byte_size,kind,mime_type,name,path,root_id") || !text(item.root_id, 64) || !text(item.path, 1_000) || item.path.startsWith("/") || item.path.includes("\\") || item.path.split("/").some((part) => !part || part === "." || part === "..") || !text(item.name, 160) || item.kind !== "image" && item.kind !== "text" || !validMime(item.mime_type, item.kind) || !Number.isSafeInteger(item.byte_size) || (item.byte_size as number) < 1 || (item.byte_size as number) > MAXIMUM_ATTACHMENT_BYTES) return null;
    return { rootId: item.root_id, path: item.path, name: item.name, mimeType: item.mime_type as string, kind: item.kind, byteSize: item.byte_size as number };
  });
  if (files.some((item) => item === null)) throw new PublicConversationMediaError("invalid_response");
  return { query, files: files as WorkspaceFile[] };
}

export async function attachWorkspaceFile(conversationId: string, rootId: string, relativePath: string, fetcher: FetchLike = fetch): Promise<StagedConversationContext> {
  if (!text(rootId, 64) || !text(relativePath, 1_000) || relativePath.startsWith("/") || relativePath.includes("\\") || relativePath.split("/").some((part) => !part || part === "." || part === "..")) throw new PublicConversationMediaError("invalid");
  const value = await request(`${conversationPath(conversationId)}/workspace-files`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ root_id: rootId, relative_path: relativePath }) }, fetcher);
  return parseStaged(value, conversationId);
}

export async function listContextPacks(fetcher: FetchLike = fetch): Promise<{ contextPacks: ContextPackSummary[]; maxItems: 8 }> {
  const value = await request("/api/context-packs", { method: "GET" }, fetcher);
  if (!record(value) || !keys(value, "context_packs,max_items,runtime,schema_version,service,status") || !envelope(value) || value.max_items !== 8 || !Array.isArray(value.context_packs) || value.context_packs.length > 256) throw new PublicConversationMediaError("invalid_response");
  const packs = value.context_packs.map((pack): ContextPackSummary | null => {
    if (!record(pack) || !keys(pack, "description,id,item_count,name,revision") || typeof pack.id !== "string" || !PACK_ID.test(pack.id) || !text(pack.name, 80) || !text(pack.description, 500, true) || typeof pack.revision !== "string" || !REVISION.test(pack.revision) || !Number.isInteger(pack.item_count) || (pack.item_count as number) < 0 || (pack.item_count as number) > 8) return null;
    return { id: pack.id, name: pack.name, description: pack.description, revision: pack.revision, itemCount: pack.item_count as number };
  });
  if (packs.some((item) => item === null) || new Set(packs.map((item) => item?.id)).size !== packs.length) throw new PublicConversationMediaError("invalid_response");
  return { contextPacks: packs as ContextPackSummary[], maxItems: 8 };
}

export async function applyContextPack(conversationId: string, packId: string, expectedRevision: string, fetcher: FetchLike = fetch): Promise<StagedConversationContext> {
  if (!PACK_ID.test(packId) || !REVISION.test(expectedRevision)) throw new PublicConversationMediaError("invalid");
  const value = await request(`${conversationPath(conversationId)}/context-packs/${packId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: expectedRevision }) }, fetcher);
  return parseStaged(value, conversationId);
}

export async function clearContextPack(conversationId: string, fetcher: FetchLike = fetch): Promise<StagedConversationContext> {
  const value = await request(`${conversationPath(conversationId)}/context-packs/release`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, fetcher);
  return parseStaged(value, conversationId);
}

export async function readConversationMedia(conversationId: string, fetcher: FetchLike = fetch): Promise<ConversationMedia> {
  const value = await request(`${conversationPath(conversationId)}/media`, { method: "GET" }, fetcher);
  if (!record(value) || !keys(value, "conversation_id,runs,runtime,schema_version,service,status") || !envelope(value) || value.conversation_id !== conversationId || !Array.isArray(value.runs) || value.runs.length > 50) throw new PublicConversationMediaError("invalid_response");
  const runs = value.runs.map((run): ConversationMedia["runs"][number] | null => {
    if (!record(run) || !keys(run, "created_at,inputs,outputs,run_id") || typeof run.run_id !== "string" || !RUN_ID.test(run.run_id) || !timestamp(run.created_at) || !Array.isArray(run.inputs) || run.inputs.length > 8 || !Array.isArray(run.outputs) || run.outputs.length > 20) return null;
    const inputs = run.inputs.map((item) => mediaItem(item, conversationId));
    const outputs = run.outputs.map((item) => mediaItem(item, conversationId));
    const ids = new Set<string>();
    if ([...inputs, ...outputs].some((item) => item === null || ids.has(item.id))) return null;
    for (const item of [...inputs, ...outputs] as ConversationMediaItem[]) ids.add(item.id);
    return { runId: run.run_id, createdAt: run.created_at, inputs: inputs as ConversationMediaItem[], outputs: outputs as ConversationMediaItem[] };
  });
  if (runs.some((run) => run === null) || new Set(runs.map((run) => run?.runId)).size !== runs.length) throw new PublicConversationMediaError("invalid_response");
  return { conversationId, runs: runs as ConversationMedia["runs"] };
}
