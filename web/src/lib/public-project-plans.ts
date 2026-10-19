import { ownerFetch } from "../../public/owner-session.js";
import { PROJECT_PLAN_JSON_LIMIT, ProjectPlanContractError, projectPlanRequest, projectPlanResult, type ProjectPlanOperation, type ProjectPlanResults } from "./project-plan-contract.ts";

export class PublicProjectPlanError extends Error { constructor(readonly code: string) { super(code); } }
const FAILURES = new Set(["invalid", "capacity", "project_changed", "context_unavailable", "context_changed", "revision_conflict", "agent_unavailable", "task_changed", "input_changed", "grant_changed", "agent_changed", "version_unavailable", "project_unavailable", "unavailable"]);

async function boundedJson(response: Response): Promise<unknown> {
  const maximum = 128 * 1024, declared = response.headers.get("content-length");
  if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > maximum)) throw new PublicProjectPlanError("invalid_response");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > maximum) { await reader.cancel(); throw new PublicProjectPlanError("invalid_response"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new PublicProjectPlanError("invalid_response"); }
}

export async function projectPlans<K extends ProjectPlanOperation>(operation: K, input: unknown): Promise<ProjectPlanResults[K]> {
  let request: Record<string, unknown>;
  try { request = projectPlanRequest(operation, input); } catch { throw new PublicProjectPlanError("invalid"); }
  const projectId = request.project_id as string, versionId = request.version_id as string | undefined;
  const route = `/api/projects/${encodeURIComponent(projectId)}/plan${operation === "version" ? `/${encodeURIComponent(versionId!)}` : ""}`;
  const method = operation === "publish" ? "POST" : "GET";
  const body = { ...request }; delete body.project_id; delete body.version_id;
  if (method === "POST" && new TextEncoder().encode(JSON.stringify(body)).length > PROJECT_PLAN_JSON_LIMIT) throw new PublicProjectPlanError("invalid");
  try {
    const response = await ownerFetch(route, { method, cache: "no-store", credentials: "same-origin", redirect: "error",
      signal: AbortSignal.timeout(method === "POST" ? 35_000 : 15_000),
      headers: { Accept: "application/json", ...(method === "POST" ? { "Content-Type": "application/json" } : {}) },
      ...(method === "POST" ? { body: JSON.stringify(body) } : {}) });
    const payload = await boundedJson(response);
    if (response.status !== 200) {
      const status = payload && typeof payload === "object" && !Array.isArray(payload) && "status" in payload ? String(payload.status) : "unavailable";
      throw new PublicProjectPlanError(FAILURES.has(status) ? status : "unavailable");
    }
    return projectPlanResult(operation, payload, request);
  } catch (error) {
    if (error instanceof PublicProjectPlanError) throw error;
    throw new PublicProjectPlanError(error instanceof ProjectPlanContractError ? "invalid_response" : "unavailable");
  }
}
