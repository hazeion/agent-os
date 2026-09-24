import { ownerFetch } from "../../public/owner-session.js";
import { inboxDataResult, inboxRequest, INBOX_JSON_LIMIT, OwnerInboxContractError, type InboxOperation, type InboxResults } from "./owner-inbox-contract.ts";

export class PublicOwnerInboxError extends Error { constructor(readonly code: string) { super(code); } }
const FAILURES = new Set(["invalid", "stale", "capacity", "incomplete", "confirmation_conflict", "project_unavailable", "unavailable"]);
async function readJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > INBOX_JSON_LIMIT)) throw new PublicOwnerInboxError("invalid_response");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > INBOX_JSON_LIMIT) { await reader.cancel(); throw new PublicOwnerInboxError("invalid_response"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new PublicOwnerInboxError("invalid_response"); }
}
export async function ownerInbox<K extends InboxOperation>(operation: K, input: unknown): Promise<InboxResults[K]> {
  let request: Record<string, unknown>;
  try { request = inboxRequest(operation, input); } catch { throw new PublicOwnerInboxError("invalid"); }
  const itemId = request.item_id as string | undefined;
  const route = operation === "page" ? `/api/inbox?view=${encodeURIComponent(String(request.view))}${request.after === null ? "" : `&after=${encodeURIComponent(String(request.after))}`}`
    : operation === "open" ? `/api/inbox/${encodeURIComponent(itemId!)}`
    : operation === "mark" ? `/api/inbox/${encodeURIComponent(itemId!)}/mark`
    : operation === "preview" ? `/api/inbox/${encodeURIComponent(itemId!)}/review/preview`
    : `/api/inbox/${encodeURIComponent(itemId!)}/review/confirm`;
  const method = operation === "page" || operation === "open" ? "GET" : "POST";
  const body = { ...request }; delete body.item_id;
  try {
    const response = await ownerFetch(route, { method, cache: "no-store", credentials: "same-origin", redirect: "error",
      signal: AbortSignal.timeout(method === "POST" ? 35_000 : 15_000),
      headers: { Accept: "application/json", ...(method === "POST" ? { "Content-Type": "application/json" } : {}) },
      ...(method === "POST" ? { body: JSON.stringify(body) } : {}) });
    const payload = await readJson(response);
    if (response.status !== 200) {
      const status = payload && typeof payload === "object" && !Array.isArray(payload) && "status" in payload ? String(payload.status) : "unavailable";
      throw new PublicOwnerInboxError(FAILURES.has(status) ? status : "unavailable");
    }
    return inboxDataResult(operation, payload, request);
  } catch (error) {
    if (error instanceof PublicOwnerInboxError) throw error;
    throw new PublicOwnerInboxError(error instanceof OwnerInboxContractError ? "invalid_response" : "unavailable");
  }
}
