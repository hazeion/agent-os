const PRIVATE_ROOT = "/bridge/v1";
const MAXIMUM_JSON_BYTES = 1_500_000;
export const MAXIMUM_ATTACHMENT_BYTES = 10 * 1024 * 1024;

type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export type BridgeMediaItem = {
  id: string;
  name: string;
  mime_type: string;
  kind: "image" | "text";
  byte_size: number;
  state: string;
  available: boolean;
  created_at: string | null;
  expires_at: string | null;
};

export type BridgeStagedItem = BridgeMediaItem & {
  source: "upload" | "workspace" | "context_pack";
  ordinal: number;
};

export type BridgeContextPackSummary = {
  id: string;
  name: string;
  description: string;
  revision: string;
  item_count: number;
};

type BridgeEnvelope = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
};

export type BridgeStagedContext = BridgeEnvelope & {
  conversation_id: string;
  attachments: BridgeStagedItem[];
  context_pack: Pick<BridgeContextPackSummary, "id" | "name" | "revision"> | null;
  limits: { direct: 5; total: 8; images: 1 };
};

export type BridgeWorkspaceFiles = BridgeEnvelope & {
  query: string;
  files: Array<{
    root_id: string;
    path: string;
    name: string;
    mime_type: string;
    kind: "image" | "text";
    byte_size: number;
  }>;
};

export type BridgeContextPacks = BridgeEnvelope & {
  context_packs: BridgeContextPackSummary[];
  max_items: 8;
};

export type BridgeConversationMedia = BridgeEnvelope & {
  conversation_id: string;
  runs: Array<{ run_id: string; created_at: string; inputs: BridgeMediaItem[]; outputs: BridgeMediaItem[] }>;
};

export type BridgeAttachmentContent = {
  body: Uint8Array;
  contentType: string;
};

export class BridgeConversationMediaError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.code = code;
    this.name = "BridgeConversationMediaError";
  }
}

const CONVERSATION_ID = /^conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u;
const ATTACHMENT_ID = /^attachment_[0-9a-f]{32}$/u;
const RUN_ID = /^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/u;
const PACK_ID = /^pack_[0-9a-f]{16}$/u;
const REVISION = /^sha256:[0-9a-f]{64}$/u;
const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u;
const CONTROL = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u;
const ATTACHMENT_STATES = new Set([
  "staged", "attached", "orphaned", "pending_delete", "missing",
]);
const IMAGE_MIME_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
const TEXT_MIME_TYPES = new Set([
  "text/plain", "text/markdown", "text/x-python", "text/javascript", "text/typescript",
  "application/json", "application/javascript", "application/x-javascript", "application/x-ndjson", "text/css", "text/html", "application/xml",
  "application/yaml", "application/toml", "text/csv", "text/tab-separated-values",
  "application/sql", "text/x-c", "text/x-c++", "text/x-java-source", "text/x-go",
  "text/x-rust", "text/x-ruby", "text/x-php", "text/x-swift", "text/x-kotlin",
  "text/x-csharp", "text/x-diff",
]);
export const UPLOAD_CONTENT_TYPES = new Set([
  ...IMAGE_MIME_TYPES,
  ...TEXT_MIME_TYPES,
  "application/octet-stream",
]);

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: string): boolean {
  return Object.keys(value).sort().join(",") === expected;
}

function safeText(value: unknown, maximum: number, allowEmpty = false): value is string {
  return typeof value === "string"
    && (allowEmpty || value.length > 0)
    && [...value].length <= maximum
    && value.trim() === value
    && !CONTROL.test(value);
}

function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 && TIMESTAMP.test(value) && !Number.isNaN(Date.parse(value));
}

function validMime(value: unknown, kind: unknown): value is string {
  return typeof value === "string"
    && (kind === "image" ? IMAGE_MIME_TYPES.has(value) : kind === "text" && TEXT_MIME_TYPES.has(value));
}

function validEnvelope(value: Record<string, unknown>): boolean {
  return value.schema_version === 1
    && value.service === "mentat-local-bridge"
    && value.runtime === "python"
    && value.status === "ready";
}

function validMediaItem(value: unknown): value is BridgeMediaItem {
  if (!record(value) || !exactKeys(value, "available,byte_size,created_at,expires_at,id,kind,mime_type,name,state")) return false;
  return typeof value.id === "string" && ATTACHMENT_ID.test(value.id)
    && safeText(value.name, 255)
    && (value.kind === "image" || value.kind === "text")
    && validMime(value.mime_type, value.kind)
    && Number.isSafeInteger(value.byte_size) && (value.byte_size as number) > 0 && (value.byte_size as number) <= MAXIMUM_ATTACHMENT_BYTES
    && typeof value.state === "string" && ATTACHMENT_STATES.has(value.state)
    && typeof value.available === "boolean"
    && (!value.available || value.state === "staged" || value.state === "attached")
    && (value.created_at === null || validTimestamp(value.created_at))
    && (value.expires_at === null || validTimestamp(value.expires_at));
}

function validStagedItem(value: unknown): value is BridgeStagedItem {
  if (!record(value) || !exactKeys(value, "available,byte_size,created_at,expires_at,id,kind,mime_type,name,ordinal,source,state")) return false;
  const base = Object.fromEntries(Object.entries(value).filter(([key]) => key !== "source" && key !== "ordinal"));
  return validMediaItem(base)
    && (value.source === "upload" || value.source === "workspace" || value.source === "context_pack")
    && Number.isInteger(value.ordinal) && (value.ordinal as number) >= 0 && (value.ordinal as number) <= 7;
}

function validPackIdentity(value: unknown): value is Pick<BridgeContextPackSummary, "id" | "name" | "revision"> {
  return record(value)
    && exactKeys(value, "id,name,revision")
    && typeof value.id === "string" && PACK_ID.test(value.id)
    && safeText(value.name, 80)
    && typeof value.revision === "string" && REVISION.test(value.revision);
}

function validPackSummary(value: unknown): value is BridgeContextPackSummary {
  return record(value)
    && exactKeys(value, "description,id,item_count,name,revision")
    && typeof value.id === "string" && PACK_ID.test(value.id)
    && safeText(value.name, 80)
    && safeText(value.description, 500, true)
    && typeof value.revision === "string" && REVISION.test(value.revision)
    && Number.isInteger(value.item_count) && (value.item_count as number) >= 0 && (value.item_count as number) <= 8;
}

function cloneMediaItem(value: BridgeMediaItem): BridgeMediaItem {
  return { ...value };
}

function parseStaged(value: unknown, expectedConversationId: string): BridgeStagedContext {
  if (!record(value) || !exactKeys(value, "attachments,context_pack,conversation_id,limits,runtime,schema_version,service,status") || !validEnvelope(value)) throw new BridgeConversationMediaError("bridge_response_invalid");
  if (value.conversation_id !== expectedConversationId || !Array.isArray(value.attachments) || value.attachments.length > 8 || !value.attachments.every(validStagedItem)) throw new BridgeConversationMediaError("bridge_response_invalid");
  const attachments = value.attachments as BridgeStagedItem[];
  const ids = new Set(attachments.map((item) => item.id));
  if (ids.size !== attachments.length || attachments.some((item, index) => index > 0 && attachments[index - 1].ordinal >= item.ordinal) || attachments.filter((item) => item.source !== "context_pack").length > 5 || attachments.filter((item) => item.kind === "image").length > 1) throw new BridgeConversationMediaError("bridge_response_invalid");
  if (value.context_pack !== null && !validPackIdentity(value.context_pack) || attachments.some((item) => item.source === "context_pack") && value.context_pack === null) throw new BridgeConversationMediaError("bridge_response_invalid");
  if (!record(value.limits) || !exactKeys(value.limits, "direct,images,total") || value.limits.direct !== 5 || value.limits.total !== 8 || value.limits.images !== 1) throw new BridgeConversationMediaError("bridge_response_invalid");
  return {
    ...(value as BridgeStagedContext),
    attachments: attachments.map((item) => ({ ...item })),
    context_pack: value.context_pack === null ? null : {
      id: (value.context_pack as Pick<BridgeContextPackSummary, "id" | "name" | "revision">).id,
      name: (value.context_pack as Pick<BridgeContextPackSummary, "id" | "name" | "revision">).name,
      revision: (value.context_pack as Pick<BridgeContextPackSummary, "id" | "name" | "revision">).revision,
    },
    limits: { direct: 5, total: 8, images: 1 },
  };
}

function parseWorkspace(value: unknown, expectedQuery: string): BridgeWorkspaceFiles {
  if (!record(value) || !exactKeys(value, "files,query,runtime,schema_version,service,status") || !validEnvelope(value) || value.query !== expectedQuery || !Array.isArray(value.files) || value.files.length > 50) throw new BridgeConversationMediaError("bridge_response_invalid");
  const files = value.files;
  const valid = files.every((entry) => {
    if (!record(entry) || !exactKeys(entry, "byte_size,kind,mime_type,name,path,root_id")) return false;
    if (!safeText(entry.root_id, 64) || !OPAQUE_ID.test(entry.root_id) || !safeText(entry.path, 1_000) || entry.path.startsWith("/") || entry.path.includes("\\")) return false;
    const segments = entry.path.split("/");
    return segments.every((part) => part && part !== "." && part !== "..")
      && safeText(entry.name, 160)
      && (entry.kind === "image" || entry.kind === "text")
      && validMime(entry.mime_type, entry.kind)
      && Number.isSafeInteger(entry.byte_size) && (entry.byte_size as number) > 0 && (entry.byte_size as number) <= MAXIMUM_ATTACHMENT_BYTES;
  });
  if (!valid) throw new BridgeConversationMediaError("bridge_response_invalid");
  return { ...(value as BridgeWorkspaceFiles), files: (files as BridgeWorkspaceFiles["files"]).map((item) => ({ ...item })) };
}

function parsePacks(value: unknown): BridgeContextPacks {
  if (!record(value) || !exactKeys(value, "context_packs,max_items,runtime,schema_version,service,status") || !validEnvelope(value) || value.max_items !== 8 || !Array.isArray(value.context_packs) || value.context_packs.length > 256 || !value.context_packs.every(validPackSummary)) throw new BridgeConversationMediaError("bridge_response_invalid");
  const packs = value.context_packs as BridgeContextPackSummary[];
  if (new Set(packs.map((pack) => pack.id)).size !== packs.length) throw new BridgeConversationMediaError("bridge_response_invalid");
  return { ...(value as BridgeContextPacks), context_packs: packs.map((pack) => ({ ...pack })) };
}

function parseMedia(value: unknown, expectedConversationId: string): BridgeConversationMedia {
  if (!record(value) || !exactKeys(value, "conversation_id,runs,runtime,schema_version,service,status") || !validEnvelope(value) || value.conversation_id !== expectedConversationId || !Array.isArray(value.runs) || value.runs.length > 50) throw new BridgeConversationMediaError("bridge_response_invalid");
  const runs = value.runs;
  if (!runs.every((run) => {
    if (!record(run) || !exactKeys(run, "created_at,inputs,outputs,run_id") || typeof run.run_id !== "string" || !RUN_ID.test(run.run_id) || !validTimestamp(run.created_at) || !Array.isArray(run.inputs) || run.inputs.length > 8 || !Array.isArray(run.outputs) || run.outputs.length > 20 || !run.inputs.every(validMediaItem) || !run.outputs.every(validMediaItem)) return false;
    const attachmentIds = new Set<string>();
    return [...run.inputs, ...run.outputs].every((item) => {
      const id = (item as BridgeMediaItem).id;
      if (attachmentIds.has(id)) return false;
      attachmentIds.add(id);
      return true;
    });
  })) throw new BridgeConversationMediaError("bridge_response_invalid");
  const publicRuns = runs as BridgeConversationMedia["runs"];
  if (new Set(publicRuns.map((run) => run.run_id)).size !== publicRuns.length) throw new BridgeConversationMediaError("bridge_response_invalid");
  return { ...(value as BridgeConversationMedia), runs: publicRuns.map((run) => ({ run_id: run.run_id, created_at: run.created_at, inputs: run.inputs.map(cloneMediaItem), outputs: run.outputs.map(cloneMediaItem) })) };
}

function configuration(environment: Environment): { origin: string; token: string } {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? ""); } catch { throw new BridgeConversationMediaError("bridge_configuration_invalid"); }
  const host = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (origin.protocol !== "http:" || !new Set(["127.0.0.1", "::1"]).has(host) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new BridgeConversationMediaError("bridge_configuration_invalid");
  return { origin: origin.origin, token };
}

async function bounded(response: Response, maximum: number): Promise<Uint8Array> {
  const declared = response.headers.get("content-length");
  if (declared !== null && (!/^(?:0|[1-9][0-9]{0,9})$/u.test(declared) || Number(declared) > maximum)) throw new BridgeConversationMediaError("bridge_response_invalid");
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const next = await reader.read();
      if (next.done) break;
      total += next.value.byteLength;
      if (total > maximum) {
        await reader.cancel();
        throw new BridgeConversationMediaError("bridge_response_invalid");
      }
      chunks.push(next.value);
    }
  } finally {
    reader.releaseLock();
  }
  const result = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; }
  if (declared !== null && result.byteLength !== Number(declared)) throw new BridgeConversationMediaError("bridge_response_invalid");
  return result;
}

function fixedFailure(response: Response, value: unknown): never {
  if (!record(value) || !exactKeys(value, "runtime,schema_version,service,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || typeof value.status !== "string") throw new BridgeConversationMediaError("bridge_response_invalid");
  const expected: Record<number, string[]> = {
    400: ["invalid"], 404: ["not_found"], 409: ["conflict"], 410: ["gone"],
    413: ["too_large"], 415: ["unsupported"], 429: ["capacity_unavailable"], 500: ["error"], 503: ["unavailable"],
  };
  if (!expected[response.status]?.includes(value.status)) throw new BridgeConversationMediaError("bridge_response_invalid");
  if (response.status === 410) throw new BridgeConversationMediaError("conversation_media_gone");
  throw new BridgeConversationMediaError(`conversation_media_${value.status}`);
}

function combinedSignal(timeoutMilliseconds: number, signal?: AbortSignal): AbortSignal {
  const timeout = AbortSignal.timeout(timeoutMilliseconds);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

async function jsonRequest(path: string, init: RequestInit, fetcher: FetchLike, environment: Environment, timeoutMilliseconds = 5_000): Promise<unknown> {
  const bridge = configuration(environment);
  let response: Response;
  try {
    response = await fetcher(new URL(path, bridge.origin), {
      ...init,
      cache: "no-store",
      redirect: "error",
      headers: { Accept: "application/json", "X-Mentat-Bridge-Token": bridge.token, ...init.headers },
      signal: combinedSignal(timeoutMilliseconds, init.signal ?? undefined),
    });
  } catch {
    if (init.signal?.aborted) throw new BridgeConversationMediaError("conversation_media_cancelled");
    throw new BridgeConversationMediaError("bridge_unavailable");
  }
  if (!["application/json", "application/json; charset=utf-8"].includes(response.headers.get("content-type")?.toLowerCase() ?? "")) throw new BridgeConversationMediaError("bridge_response_invalid");
  let value: unknown;
  try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await bounded(response, MAXIMUM_JSON_BYTES))); } catch (error) { if (error instanceof BridgeConversationMediaError) throw error; throw new BridgeConversationMediaError("bridge_response_invalid"); }
  if (!response.ok) return fixedFailure(response, value);
  return value;
}

function conversationPath(conversationId: string): string {
  if (!CONVERSATION_ID.test(conversationId)) throw new BridgeConversationMediaError("conversation_media_invalid");
  return `${PRIVATE_ROOT}/conversations/${encodeURIComponent(conversationId)}`;
}

function attachmentPath(conversationId: string, attachmentId: string): string {
  if (!ATTACHMENT_ID.test(attachmentId)) throw new BridgeConversationMediaError("conversation_media_not_found");
  return `${conversationPath(conversationId)}/attachments/${attachmentId}`;
}

export async function readBridgeStagedContext(conversationId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<BridgeStagedContext> {
  return parseStaged(await jsonRequest(`${conversationPath(conversationId)}/staged-context`, { method: "GET" }, fetcher, environment), conversationId);
}

export async function uploadBridgeConversationAttachment(conversationId: string, encodedFilename: string, contentType: string, body: Uint8Array, signal?: AbortSignal, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<BridgeStagedContext> {
  let decodedFilename = "";
  try { decodedFilename = decodeURIComponent(encodedFilename); } catch { throw new BridgeConversationMediaError("conversation_media_invalid"); }
  if (!safeText(decodedFilename, 255) || decodedFilename === "." || decodedFilename === ".." || decodedFilename.includes("/") || decodedFilename.includes("\\") || encodeURIComponent(decodedFilename) !== encodedFilename || encodedFilename.length > 1_024 || !UPLOAD_CONTENT_TYPES.has(contentType) || body.byteLength < 1 || body.byteLength > MAXIMUM_ATTACHMENT_BYTES) throw new BridgeConversationMediaError("conversation_media_invalid");
  const value = await jsonRequest(`${conversationPath(conversationId)}/attachments`, {
    method: "POST",
    headers: { "Content-Type": contentType, "Content-Length": String(body.byteLength), "X-Mentat-Filename": encodedFilename },
    body: body.slice().buffer,
    signal,
  }, fetcher, environment, 20_000);
  return parseStaged(value, conversationId);
}

export async function releaseBridgeConversationAttachment(conversationId: string, attachmentId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<BridgeStagedContext> {
  return parseStaged(await jsonRequest(`${attachmentPath(conversationId, attachmentId)}/release`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, fetcher, environment), conversationId);
}

export async function searchBridgeWorkspaceFiles(query: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<BridgeWorkspaceFiles> {
  if (!safeText(query, 200, true)) throw new BridgeConversationMediaError("conversation_media_invalid");
  const path = `${PRIVATE_ROOT}/workspace-files?query=${encodeURIComponent(query)}`;
  return parseWorkspace(await jsonRequest(path, { method: "GET" }, fetcher, environment), query);
}

export async function attachBridgeWorkspaceFile(conversationId: string, rootId: string, relativePath: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<BridgeStagedContext> {
  if (!safeText(rootId, 64) || !OPAQUE_ID.test(rootId) || !safeText(relativePath, 1_000) || relativePath.startsWith("/") || relativePath.includes("\\") || relativePath.split("/").some((part) => !part || part === "." || part === "..")) throw new BridgeConversationMediaError("conversation_media_invalid");
  return parseStaged(await jsonRequest(`${conversationPath(conversationId)}/workspace-files`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ root_id: rootId, relative_path: relativePath }) }, fetcher, environment), conversationId);
}

export async function readBridgeContextPacks(fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<BridgeContextPacks> {
  return parsePacks(await jsonRequest(`${PRIVATE_ROOT}/context-packs`, { method: "GET" }, fetcher, environment));
}

export async function applyBridgeContextPack(conversationId: string, packId: string, expectedRevision: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<BridgeStagedContext> {
  if (!PACK_ID.test(packId) || !REVISION.test(expectedRevision)) throw new BridgeConversationMediaError("conversation_media_invalid");
  return parseStaged(await jsonRequest(`${conversationPath(conversationId)}/context-packs/${packId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: expectedRevision }) }, fetcher, environment), conversationId);
}

export async function clearBridgeContextPack(conversationId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<BridgeStagedContext> {
  return parseStaged(await jsonRequest(`${conversationPath(conversationId)}/context-packs/release`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, fetcher, environment), conversationId);
}

export async function readBridgeConversationMedia(conversationId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<BridgeConversationMedia> {
  return parseMedia(await jsonRequest(`${conversationPath(conversationId)}/media`, { method: "GET" }, fetcher, environment), conversationId);
}

export async function readBridgeConversationAttachmentContent(conversationId: string, attachmentId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<BridgeAttachmentContent> {
  const bridge = configuration(environment);
  let response: Response;
  try {
    response = await fetcher(new URL(`${attachmentPath(conversationId, attachmentId)}/content`, bridge.origin), {
      method: "GET",
      cache: "no-store",
      redirect: "error",
      headers: { Accept: "image/png, image/jpeg, image/gif, image/webp, text/plain", "X-Mentat-Bridge-Token": bridge.token },
      signal: AbortSignal.timeout(5_000),
    });
  } catch { throw new BridgeConversationMediaError("bridge_unavailable"); }
  if (response.status !== 200) {
    if (!["application/json", "application/json; charset=utf-8"].includes(response.headers.get("content-type")?.toLowerCase() ?? "")) throw new BridgeConversationMediaError("bridge_response_invalid");
    let value: unknown;
    try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await bounded(response, 4_096))); } catch (error) { if (error instanceof BridgeConversationMediaError) throw error; throw new BridgeConversationMediaError("bridge_response_invalid"); }
    return fixedFailure(response, value);
  }
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  const declared = response.headers.get("content-length");
  if (
    (!IMAGE_MIME_TYPES.has(contentType) && contentType !== "text/plain; charset=utf-8")
    || !declared
    || !/^[1-9][0-9]{0,8}$/u.test(declared)
    || Number(declared) > MAXIMUM_ATTACHMENT_BYTES
    || response.headers.get("cache-control")?.toLowerCase() !== "private, no-store"
    || response.headers.get("x-content-type-options")?.toLowerCase() !== "nosniff"
    || response.headers.get("cross-origin-resource-policy")?.toLowerCase() !== "same-origin"
    || response.headers.get("content-security-policy")?.toLowerCase() !== "default-src 'none'; sandbox"
  ) throw new BridgeConversationMediaError("bridge_response_invalid");
  const body = await bounded(response, MAXIMUM_ATTACHMENT_BYTES);
  if (body.byteLength !== Number(declared)) throw new BridgeConversationMediaError("bridge_response_invalid");
  return { body, contentType };
}
