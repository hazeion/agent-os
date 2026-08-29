import type { SafeLinkPreviewProjection } from "../app/transcript-link-previews.tsx";

const ROOT = "/api/link-previews";
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export class PublicLinkPreviewError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.code = code; this.name = "PublicLinkPreviewError"; }
}

export type PublicLinkPreviewState = {
  conversationId: string;
  messageId: string;
  messageRevision: number;
  enabled: boolean;
  previews: SafeLinkPreviewProjection[];
};

export type PublicLinkPreviewPreference = { enabled: boolean; revision: number };

async function boundedText(response: Response, maximum = 24_576): Promise<string> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > maximum)) throw new PublicLinkPreviewError("invalid_response");
  if (!response.body) return "";
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > maximum) { await reader.cancel(); throw new PublicLinkPreviewError("invalid_response"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const body = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  try { return new TextDecoder("utf-8", { fatal: true }).decode(body); } catch { throw new PublicLinkPreviewError("invalid_response"); }
}

async function request(path: string, init: RequestInit, fetcher: FetchLike): Promise<unknown> {
  let response: Response;
  try { response = await fetcher(path, { ...init, cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json", ...init.headers }, redirect: "error", signal: AbortSignal.timeout(5_000) }); } catch { throw new PublicLinkPreviewError("unavailable"); }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new PublicLinkPreviewError("invalid_response");
  const text = await boundedText(response);
  let value: unknown; try { value = JSON.parse(text); } catch { throw new PublicLinkPreviewError("invalid_response"); }
  if (!response.ok) {
    const status = value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>).status : null;
    throw new PublicLinkPreviewError(typeof status === "string" ? status : "invalid_response");
  }
  return value;
}

const conversationId = (value: unknown): value is string => typeof value === "string" && /^conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u.test(value);
const messageId = (value: unknown): value is string => typeof value === "string" && /^msg_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u.test(value);
const safe = (value: unknown, maximum: number): value is string => typeof value === "string" && value.length > 0 && value.length <= maximum && value.trim() === value && !/[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u.test(value);

function preview(value: unknown): SafeLinkPreviewProjection | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null; const item = value as Record<string, unknown>;
  if (!Number.isInteger(item.candidate_ordinal) || (item.candidate_ordinal as number) < 1 || (item.candidate_ordinal as number) > 3 || !["pending", "ready", "unavailable", "blocked", "disabled"].includes(String(item.status))) return null;
  const status = item.status as SafeLinkPreviewProjection["status"];
  if (status !== "ready" && Object.keys(item).sort().join(",") !== "candidate_ordinal,status") return null;
  if (status === "ready" && Object.keys(item).some((key) => !["candidate_ordinal", "status", "title", "description", "site_name", "display_host", "image_alt", "image_id"].includes(key))) return null;
  if (status === "ready" && (!safe(item.display_host, 253) || !(safe(item.title, 200) || safe(item.description, 500)))) return null;
  if (item.title !== undefined && !safe(item.title, 200) || item.description !== undefined && !safe(item.description, 500) || item.site_name !== undefined && !safe(item.site_name, 120) || item.image_alt !== undefined && !safe(item.image_alt, 200) || item.image_id !== undefined && (typeof item.image_id !== "string" || !/^[0-9a-f]{32}$/u.test(item.image_id))) return null;
  return {
    candidateOrdinal: item.candidate_ordinal as number,
    status,
    title: item.title as string | undefined,
    description: item.description as string | undefined,
    displayHost: item.display_host as string | undefined,
    imageAlt: item.image_alt as string | undefined,
    imageId: item.image_id as string | undefined,
  };
}

function state(value: unknown, expected: { conversationId: string; messageId: string; revision: number }): PublicLinkPreviewState {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new PublicLinkPreviewError("invalid_response"); const item = value as Record<string, unknown>; const values = item.previews;
  if (Object.keys(item).sort().join(",") !== "conversation_id,enabled,message_id,message_revision,previews,runtime,schema_version,service,status" || item.schema_version !== 1 || item.service !== "mentat-local-bridge" || item.runtime !== "python" || item.status !== "ready" || item.conversation_id !== expected.conversationId || item.message_id !== expected.messageId || item.message_revision !== expected.revision || typeof item.enabled !== "boolean" || !Array.isArray(values) || values.length > 3) throw new PublicLinkPreviewError("invalid_response");
  const previews = values.map(preview); if (previews.some((entry) => entry === null)) throw new PublicLinkPreviewError("invalid_response");
  const ready = previews as SafeLinkPreviewProjection[]; if (ready.some((entry, index) => index > 0 && ready[index - 1].candidateOrdinal >= entry.candidateOrdinal)) throw new PublicLinkPreviewError("invalid_response");
  return { conversationId: expected.conversationId, messageId: expected.messageId, messageRevision: expected.revision, enabled: item.enabled, previews: ready.map((entry) => ({ ...entry })) };
}

function messagePath(conversation: string, message: string) {
  if (!conversationId(conversation) || !messageId(message)) throw new PublicLinkPreviewError("invalid"); return `/api/conversations/${encodeURIComponent(conversation)}/messages/${encodeURIComponent(message)}/link-previews`;
}

export async function readLinkPreviews(conversation: string, message: string, revision: number, fetcher: FetchLike = fetch): Promise<PublicLinkPreviewState> {
  if (!Number.isSafeInteger(revision) || revision < 1) throw new PublicLinkPreviewError("invalid"); return state(await request(`${messagePath(conversation, message)}?revision=${revision}`, { method: "GET" }, fetcher), { conversationId: conversation, messageId: message, revision });
}
export async function requestLinkPreviews(conversation: string, message: string, revision: number, action: "enqueue" | "retry", fetcher: FetchLike = fetch): Promise<PublicLinkPreviewState> {
  if (!Number.isSafeInteger(revision) || revision < 1 || !["enqueue", "retry"].includes(action)) throw new PublicLinkPreviewError("invalid"); return state(await request(messagePath(conversation, message), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, message_revision: revision }) }, fetcher), { conversationId: conversation, messageId: message, revision });
}
export async function readLinkPreviewPreference(fetcher: FetchLike = fetch): Promise<PublicLinkPreviewPreference> {
  const value = await request(`${ROOT}/preference`, { method: "GET" }, fetcher); if (!value || typeof value !== "object" || Array.isArray(value)) throw new PublicLinkPreviewError("invalid_response"); const item = value as Record<string, unknown>;
  if (Object.keys(item).sort().join(",") !== "enabled,revision,runtime,schema_version,service,status" || item.schema_version !== 1 || item.service !== "mentat-local-bridge" || item.runtime !== "python" || item.status !== "ready" || typeof item.enabled !== "boolean" || !Number.isInteger(item.revision) || (item.revision as number) < 1) throw new PublicLinkPreviewError("invalid_response"); return { enabled: item.enabled, revision: item.revision as number };
}
export async function updateLinkPreviewPreference(enabled: boolean, expectedRevision: number, fetcher: FetchLike = fetch): Promise<PublicLinkPreviewPreference> {
  if (typeof enabled !== "boolean" || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1) throw new PublicLinkPreviewError("invalid");
  const value = await request(`${ROOT}/preference`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled, expected_revision: expectedRevision }) }, fetcher); return readLinkPreviewPreference(async () => Response.json(value));
}
export async function clearLinkPreviewCache(fetcher: FetchLike = fetch): Promise<void> {
  const value = await request(`${ROOT}/cache/clear`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, fetcher);
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join(",") !== "cleared,schema_version,status" || (value as Record<string, unknown>).schema_version !== 1 || (value as Record<string, unknown>).status !== "ready" || (value as Record<string, unknown>).cleared !== true) throw new PublicLinkPreviewError("invalid_response");
}
