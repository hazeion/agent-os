import { ownerFetch } from "../../public/owner-session.js";
import { DeliverableContractError, deliverableRequest, deliverableResult, type DeliverableOperation, type DeliverableResults } from "./project-deliverable-contract.ts";

export class PublicDeliverableError extends Error { constructor(readonly code: string) { super(code); } }
const FAILURES = new Set(["invalid", "revision_conflict", "source_changed", "project_changed", "task_changed", "version_unavailable", "project_unavailable", "capacity", "inbox_capacity", "content_invalid", "content_capacity", "preview_unavailable", "preview_capacity", "link_invalid", "slot_invalid", "revision_invalid", "incomplete", "stale", "confirmation_conflict", "unavailable"]);
const VERSION = /^deliverable_version_[0-9a-f]{32}$/u;
export function deliverablePreviewUrl(versionId: string): string {
  if (!VERSION.test(versionId)) throw new PublicDeliverableError("invalid");
  return `/api/deliverables/${encodeURIComponent(versionId)}/preview`;
}
async function readJson(response: Response): Promise<unknown> {
  if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new PublicDeliverableError("invalid_response");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > 512 * 1024) { await reader.cancel(); throw new PublicDeliverableError("invalid_response"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new PublicDeliverableError("invalid_response"); }
}
export async function projectDeliverables<K extends Exclude<DeliverableOperation, "preview">>(operation: K, input: unknown): Promise<DeliverableResults[K]> {
  let request: Record<string, unknown>;
  try { request = deliverableRequest(operation, input); } catch { throw new PublicDeliverableError("invalid"); }
  const projectId = request.project_id as string | undefined, versionId = request.version_id as string | undefined;
  const route = operation === "project" || operation === "publish" ? `/api/projects/${encodeURIComponent(projectId!)}/deliverables`
    : operation === "review-status" ? `/api/projects/${encodeURIComponent(projectId!)}/deliverables/review`
    : operation === "review-preview" ? `/api/projects/${encodeURIComponent(projectId!)}/deliverables/review/preview`
    : operation === "review-confirm" ? `/api/projects/${encodeURIComponent(projectId!)}/deliverables/review/confirm`
    : operation === "version" ? `/api/projects/${encodeURIComponent(projectId!)}/deliverables/${encodeURIComponent(versionId!)}`
    : operation === "retired-history" ? `/api/deliverables/history${"offset" in request ? `?offset=${request.offset}` : ""}` : `/api/deliverables/${encodeURIComponent(versionId!)}`;
  const method = operation === "publish" || operation === "review-preview" || operation === "review-confirm" ? "POST" : "GET";
  const body = { ...request }; delete body.project_id; delete body.version_id;
  try {
    const response = await ownerFetch(route, { method, cache: "no-store", credentials: "same-origin", redirect: "error",
      signal: AbortSignal.timeout(method === "POST" ? 35_000 : 15_000),
      headers: { Accept: "application/json", ...(method === "POST" ? { "Content-Type": "application/json" } : {}) },
      ...(method === "POST" ? { body: JSON.stringify(body) } : {}) });
    const payload = await readJson(response);
    if (response.status !== 200) {
      const status = payload && typeof payload === "object" && !Array.isArray(payload) && "status" in payload ? String(payload.status) : "unavailable";
      throw new PublicDeliverableError(FAILURES.has(status) ? status : "unavailable");
    }
    return deliverableResult(operation, payload, request);
  } catch (error) {
    if (error instanceof PublicDeliverableError) throw error;
    throw new PublicDeliverableError(error instanceof DeliverableContractError ? "invalid_response" : "unavailable");
  }
}
