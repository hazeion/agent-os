import { ownerFetch } from "../../public/owner-session.js";
import { ProjectInputContractError, projectInputRequest, projectInputResult, type ProjectInputOperation, type ProjectInputResults } from "./project-planning-input-contract.ts";

export class PublicProjectInputError extends Error { constructor(readonly code: string) { super(code); } }
const FAILURES = new Set(["invalid", "version_unavailable", "project_unavailable", "capacity", "project_changed", "scope_changed", "lead_changed", "context_changed", "revision_conflict", "selection_changed", "file_scope", "files_unavailable", "image_limit", "action_conflict", "unavailable"]);
async function boundedJson(response: Response): Promise<unknown> {
  const maximum = 128 * 1024, declared = response.headers.get("content-length");
  if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json")
    || declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > maximum)) throw new ProjectInputContractError();
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > maximum) { await reader.cancel(); throw new ProjectInputContractError(); } chunks.push(next.value); } }
  finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; }
  catch { throw new ProjectInputContractError(); }
}

export async function projectInputs<K extends ProjectInputOperation>(operation: K, input: unknown): Promise<ProjectInputResults[K]> {
  let request: Record<string, unknown>;
  try { request = projectInputRequest(operation, input); } catch { throw new PublicProjectInputError("invalid"); }
  const projectId = String(request.project_id);
  const base = `/api/projects/${encodeURIComponent(projectId)}/planning-inputs`;
  const route = operation === "version" ? `${base}/${encodeURIComponent(String(request.input_id))}`
    : operation === "reconcile" ? `${base}/actions/${encodeURIComponent(String(request.action_id))}?scope_token=${encodeURIComponent(String(request.scope_token))}` : base;
  const body = { ...request }; delete body.project_id; delete body.input_id;
  const read = operation !== "publish";
  if (!read && new TextEncoder().encode(JSON.stringify(body)).length > 32768) throw new PublicProjectInputError("invalid");
  try {
    const response = await ownerFetch(route, { method: read ? "GET" : "POST", cache: "no-store", credentials: "same-origin", redirect: "error",
      signal: AbortSignal.timeout(read ? 15_000 : 35_000),
      headers: { Accept: "application/json", ...(read ? {} : { "Content-Type": "application/json" }) },
      ...(read ? {} : { body: JSON.stringify(body) }) });
    const payload = await boundedJson(response);
    if (response.status !== 200) {
      const code = payload && typeof payload === "object" && !Array.isArray(payload) && "status" in payload ? String(payload.status) : "unavailable";
      throw new PublicProjectInputError(FAILURES.has(code) ? code : "unavailable");
    }
    return projectInputResult(operation, payload, request);
  } catch (error) {
    if (error instanceof PublicProjectInputError) throw error;
    throw new PublicProjectInputError(error instanceof ProjectInputContractError ? "invalid_response" : "unavailable");
  }
}
