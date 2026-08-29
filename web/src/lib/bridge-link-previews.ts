const PRIVATE_ROOT = "/bridge/v1";
const MAXIMUM_JSON_BYTES = 24_576;
const MAXIMUM_IMAGE_BYTES = 512 * 1024;

type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export type PublicLinkPreview = {
  candidate_ordinal: number;
  status: "pending" | "ready" | "unavailable" | "blocked" | "disabled";
  title?: string;
  description?: string;
  site_name?: string;
  display_host?: string;
  image_alt?: string;
  image_id?: string;
};

export type PublicLinkPreviewPayload = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  conversation_id: string;
  message_id: string;
  message_revision: number;
  enabled: boolean;
  previews: PublicLinkPreview[];
};

export type PublicLinkPreviewPreference = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  enabled: boolean;
  revision: number;
};

export class BridgeLinkPreviewError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.code = code; this.name = "BridgeLinkPreviewError"; }
}

function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? ""); } catch { throw new BridgeLinkPreviewError("bridge_configuration_invalid"); }
  const hostname = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (origin.protocol !== "http:" || !new Set(["127.0.0.1", "::1"]).has(hostname) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new BridgeLinkPreviewError("bridge_configuration_invalid");
  return { origin: origin.origin, token };
}

const conversationId = (value: unknown): value is string => typeof value === "string" && /^conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u.test(value);
const messageId = (value: unknown): value is string => typeof value === "string" && /^msg_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u.test(value);
const safeText = (value: unknown, maximum: number): value is string => typeof value === "string" && value.length > 0 && value.length <= maximum && value.trim() === value && !/[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u.test(value);
const validDisplayHost = (value: string): boolean => {
  if (/^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/u.test(value)) return true;
  if (!/^[0-9a-f:]{2,45}$/u.test(value)) return false;
  try { return new URL(`https://[${value}]/`).hostname === `[${value}]`; } catch { return false; }
};

async function bounded(response: Response, maximum = MAXIMUM_JSON_BYTES): Promise<Uint8Array> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > maximum)) throw new BridgeLinkPreviewError("bridge_response_invalid");
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > maximum) { await reader.cancel(); throw new BridgeLinkPreviewError("bridge_response_invalid"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const result = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; } return result;
}

function validPreview(value: unknown): value is PublicLinkPreview {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  if (!Number.isInteger(item.candidate_ordinal) || (item.candidate_ordinal as number) < 1 || (item.candidate_ordinal as number) > 3 || !["pending", "ready", "unavailable", "blocked", "disabled"].includes(String(item.status))) return false;
  if (item.status !== "ready") return Object.keys(item).sort().join(",") === "candidate_ordinal,status";
  if (Object.keys(item).some((key) => !["candidate_ordinal", "status", "title", "description", "site_name", "display_host", "image_alt", "image_id"].includes(key))) return false;
  if (!safeText(item.display_host, 253) || !validDisplayHost(item.display_host)) return false;
  if (!(safeText(item.title, 200) || safeText(item.description, 500))) return false;
  return (item.title === undefined || safeText(item.title, 200))
    && (item.description === undefined || safeText(item.description, 500))
    && (item.site_name === undefined || safeText(item.site_name, 120))
    && (item.image_alt === undefined || safeText(item.image_alt, 200))
    && (item.image_id === undefined || typeof item.image_id === "string" && /^[0-9a-f]{32}$/u.test(item.image_id));
}

function validPayload(value: unknown, conversation: string, message: string, revision: number): value is PublicLinkPreviewPayload {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>; const previews = item.previews;
  return Object.keys(item).sort().join(",") === "conversation_id,enabled,message_id,message_revision,previews,runtime,schema_version,service,status"
    && item.schema_version === 1 && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === "ready"
    && item.conversation_id === conversation && item.message_id === message && item.message_revision === revision && typeof item.enabled === "boolean"
    && Array.isArray(previews) && previews.length <= 3 && previews.every(validPreview)
    && previews.every((preview, index) => index === 0 || previews[index - 1].candidate_ordinal < preview.candidate_ordinal);
}

function fixedFailure(response: Response, value: unknown): never {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new BridgeLinkPreviewError("bridge_response_invalid");
  const item = value as Record<string, unknown>;
  if (Object.keys(item).sort().join(",") !== "runtime,schema_version,service,status" || item.schema_version !== 1 || item.service !== "mentat-local-bridge" || item.runtime !== "python") throw new BridgeLinkPreviewError("bridge_response_invalid");
  const map: Record<string, string> = { invalid: "link_preview_invalid", not_found: "link_preview_not_found", conflict: "link_preview_conflict", capacity_unavailable: "link_preview_capacity_unavailable", unavailable: "bridge_unavailable" };
  const expected: Record<number, string[]> = { 400: ["invalid"], 404: ["not_found"], 409: ["conflict"], 429: ["capacity_unavailable"], 503: ["unavailable"] };
  if (!expected[response.status]?.includes(String(item.status)) || !map[String(item.status)]) throw new BridgeLinkPreviewError("bridge_response_invalid");
  throw new BridgeLinkPreviewError(map[String(item.status)]);
}

async function jsonRequest(path: string, init: RequestInit, fetcher: FetchLike, environment: Environment) {
  const bridge = configuration(environment); let response: Response;
  try { response = await fetcher(new URL(path, bridge.origin), { ...init, cache: "no-store", redirect: "error", headers: { Accept: "application/json", "X-Mentat-Bridge-Token": bridge.token, ...init.headers }, signal: AbortSignal.timeout(3_500) }); } catch { throw new BridgeLinkPreviewError("bridge_unavailable"); }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new BridgeLinkPreviewError("bridge_response_invalid");
  let value: unknown; try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await bounded(response))); } catch (error) { if (error instanceof BridgeLinkPreviewError) throw error; throw new BridgeLinkPreviewError("bridge_response_invalid"); }
  return { response, value };
}

function pathFor(conversation: string, message: string): string {
  if (!conversationId(conversation) || !messageId(message)) throw new BridgeLinkPreviewError("link_preview_invalid");
  return `${PRIVATE_ROOT}/conversations/${encodeURIComponent(conversation)}/messages/${encodeURIComponent(message)}/link-previews`;
}

export async function readBridgeLinkPreviews(conversation: string, message: string, revision: number, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicLinkPreviewPayload> {
  if (!Number.isSafeInteger(revision) || revision < 1) throw new BridgeLinkPreviewError("link_preview_invalid");
  const { response, value } = await jsonRequest(`${pathFor(conversation, message)}?revision=${revision}`, { method: "GET" }, fetcher, environment);
  if (response.status === 200 && validPayload(value, conversation, message, revision)) return { ...(value as PublicLinkPreviewPayload), previews: (value as PublicLinkPreviewPayload).previews.map((item) => ({ ...item })) };
  return fixedFailure(response, value);
}

export async function mutateBridgeLinkPreviews(conversation: string, message: string, revision: number, action: "enqueue" | "retry", fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicLinkPreviewPayload> {
  if (!Number.isSafeInteger(revision) || revision < 1 || !["enqueue", "retry"].includes(action)) throw new BridgeLinkPreviewError("link_preview_invalid");
  const { response, value } = await jsonRequest(pathFor(conversation, message), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, message_revision: revision }) }, fetcher, environment);
  if (response.status === 202 && validPayload(value, conversation, message, revision)) return { ...(value as PublicLinkPreviewPayload), previews: (value as PublicLinkPreviewPayload).previews.map((item) => ({ ...item })) };
  return fixedFailure(response, value);
}

function validPreference(value: unknown): value is PublicLinkPreviewPreference {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false; const item = value as Record<string, unknown>;
  return Object.keys(item).sort().join(",") === "enabled,revision,runtime,schema_version,service,status" && item.schema_version === 1 && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === "ready" && typeof item.enabled === "boolean" && Number.isInteger(item.revision) && (item.revision as number) >= 1;
}

export async function readBridgeLinkPreviewPreference(fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicLinkPreviewPreference> {
  const { response, value } = await jsonRequest(`${PRIVATE_ROOT}/link-previews/preference`, { method: "GET" }, fetcher, environment); if (response.status === 200 && validPreference(value)) return { ...value }; return fixedFailure(response, value);
}

export async function updateBridgeLinkPreviewPreference(enabled: boolean, expectedRevision: number, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicLinkPreviewPreference> {
  if (typeof enabled !== "boolean" || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1) throw new BridgeLinkPreviewError("link_preview_invalid");
  const { response, value } = await jsonRequest(`${PRIVATE_ROOT}/link-previews/preference`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled, expected_revision: expectedRevision }) }, fetcher, environment); if (response.status === 200 && validPreference(value)) return { ...value }; return fixedFailure(response, value);
}

export async function clearBridgeLinkPreviewCache(fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<void> {
  const { response, value } = await jsonRequest(`${PRIVATE_ROOT}/link-previews/cache/clear`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, fetcher, environment);
  if (response.status === 200 && value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === "cleared,runtime,schema_version,service,status" && (value as Record<string, unknown>).cleared === true && (value as Record<string, unknown>).schema_version === 1 && (value as Record<string, unknown>).service === "mentat-local-bridge" && (value as Record<string, unknown>).runtime === "python" && (value as Record<string, unknown>).status === "ready") return;
  return fixedFailure(response, value);
}

export async function readBridgeLinkPreviewImage(imageId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<{ body: Uint8Array; maxAge: number }> {
  if (!/^[0-9a-f]{32}$/u.test(imageId)) throw new BridgeLinkPreviewError("link_preview_not_found"); const bridge = configuration(environment); let response: Response;
  try { response = await fetcher(new URL(`${PRIVATE_ROOT}/link-previews/images/${imageId}`, bridge.origin), { method: "GET", cache: "no-store", redirect: "error", headers: { Accept: "image/webp", "X-Mentat-Bridge-Token": bridge.token }, signal: AbortSignal.timeout(1_500) }); } catch { throw new BridgeLinkPreviewError("bridge_unavailable"); }
  if (response.status === 404) throw new BridgeLinkPreviewError("link_preview_not_found");
  const match = /^private, max-age=(\d{1,3}), no-transform$/u.exec(response.headers.get("cache-control") ?? "");
  const declared = response.headers.get("content-length");
  if (response.status !== 200 || response.headers.get("content-type")?.toLowerCase() !== "image/webp" || response.headers.get("x-content-type-options")?.toLowerCase() !== "nosniff" || !match || Number(match[1]) > 300 || !declared || !/^\d{1,10}$/u.test(declared) || Number(declared) < 1 || Number(declared) > MAXIMUM_IMAGE_BYTES) throw new BridgeLinkPreviewError("bridge_response_invalid");
  const body = await bounded(response, MAXIMUM_IMAGE_BYTES); if (body.byteLength !== Number(declared)) throw new BridgeLinkPreviewError("bridge_response_invalid");
  return { body, maxAge: Number(match[1]) };
}
