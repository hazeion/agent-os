import { ownerFetch } from "../../public/owner-session.js";
import { ProjectLeadContractError, projectLeadRequest, projectLeadResult, type LeadOperation, type ProjectLead } from "./project-lead-contract.ts";

export class PublicProjectLeadError extends Error { constructor(readonly code: string) { super(code); } }
const FAILURES = new Set(["invalid", "project_changed", "revision_conflict", "selection_changed", "agent_unavailable", "capacity", "project_unavailable", "unavailable"]);
async function boundedJson(response: Response): Promise<unknown> {
  const maximum = 256 * 1024, declared = response.headers.get("content-length");
  if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json")
    || declared && (!/^\d{1,6}$/u.test(declared) || Number(declared) > maximum)) throw new ProjectLeadContractError();
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > maximum) { await reader.cancel(); throw new ProjectLeadContractError(); } chunks.push(next.value); } }
  finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new ProjectLeadContractError(); }
}
export async function projectLeads(operation: LeadOperation, input: unknown): Promise<ProjectLead> {
  let request: Record<string, unknown>;
  try { request = projectLeadRequest(operation, input); } catch { throw new PublicProjectLeadError("invalid"); }
  const url = `/api/projects/${encodeURIComponent(String(request.project_id))}/lead`;
  const body = { ...request }; delete body.project_id;
  try {
    const response = await ownerFetch(url, { method: operation === "project" ? "GET" : "POST", cache: "no-store", credentials: "same-origin", redirect: "error",
      signal: AbortSignal.timeout(operation === "project" ? 15_000 : 35_000),
      headers: { Accept: "application/json", ...(operation === "select" ? { "Content-Type": "application/json" } : {}) },
      ...(operation === "select" ? { body: JSON.stringify(body) } : {}) });
    const payload = await boundedJson(response);
    if (response.status !== 200) {
      const code = payload && typeof payload === "object" && !Array.isArray(payload) && "status" in payload ? String(payload.status) : "unavailable";
      throw new PublicProjectLeadError(FAILURES.has(code) ? code : "unavailable");
    }
    return projectLeadResult(payload, request);
  } catch (error) {
    if (error instanceof PublicProjectLeadError) throw error;
    throw new PublicProjectLeadError(error instanceof ProjectLeadContractError ? "invalid_response" : "unavailable");
  }
}
