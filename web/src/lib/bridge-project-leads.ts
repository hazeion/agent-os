import { ownerBridgeHeaders } from "./owner-request-context.ts";
import { ProjectLeadContractError, projectLeadRequest, projectLeadResult, type LeadOperation, type ProjectLead } from "./project-lead-contract.ts";

const FAILURES = new Set(["invalid", "project_changed", "revision_conflict", "selection_changed", "agent_unavailable", "capacity", "project_unavailable", "unavailable"]);
export class ProjectLeadBridgeError extends Error { constructor(readonly code = "unavailable", readonly status = 503) { super(code); } }
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
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
export async function projectLeadCapability(operation: LeadOperation, input: unknown, fetcher: FetchLike = fetch, environment: Readonly<Record<string, string | undefined>> = process.env): Promise<ProjectLead> {
  let request: Record<string, unknown>;
  try { request = projectLeadRequest(operation, input); } catch { throw new ProjectLeadBridgeError("invalid", 400); }
  let origin: URL; const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN ?? ""); } catch { throw new ProjectLeadBridgeError(); }
  if (origin.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(origin.hostname) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new ProjectLeadBridgeError();
  const url = new URL(`/bridge/v1/project-leads/${operation}`, origin.origin);
  if (operation === "project") url.searchParams.set("project_id", String(request.project_id));
  try {
    const response = await fetcher(url, { method: operation === "project" ? "GET" : "POST", cache: "no-store", redirect: "error",
      signal: AbortSignal.timeout(operation === "project" ? 15_000 : 35_000),
      headers: { Accept: "application/json", ...(operation === "select" ? { "Content-Type": "application/json" } : {}), ...ownerBridgeHeaders(), "X-Mentat-Bridge-Token": token },
      ...(operation === "select" ? { body: JSON.stringify(request) } : {}) });
    const payload = await boundedJson(response);
    if (response.status !== 200) {
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new ProjectLeadContractError();
      const failure = payload as Record<string, unknown>;
      if (Object.keys(failure).sort().join(",") !== "schema_version,status" || failure.schema_version !== 1 || typeof failure.status !== "string" || !FAILURES.has(failure.status)) throw new ProjectLeadContractError();
      throw new ProjectLeadBridgeError(failure.status, response.status);
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new ProjectLeadContractError();
    const success = payload as Record<string, unknown>;
    if (Object.keys(success).sort().join(",") !== "data,runtime,schema_version,service,status" || success.schema_version !== 1 || success.runtime !== "python" || success.service !== "mentat-local-bridge" || success.status !== "ready") throw new ProjectLeadContractError();
    return projectLeadResult(success.data, request);
  } catch (error) {
    if (error instanceof ProjectLeadBridgeError) throw error;
    throw new ProjectLeadBridgeError(error instanceof ProjectLeadContractError ? "invalid_response" : "unavailable", error instanceof ProjectLeadContractError ? 502 : 503);
  }
}
