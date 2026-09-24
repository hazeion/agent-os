import { ownerBridgeHeaders } from "./owner-request-context.ts";
import { PROJECT_PLAN_READS, ProjectPlanContractError, projectPlanRequest, projectPlanResult, type ProjectPlanOperation, type ProjectPlanResults } from "./project-plan-contract.ts";

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
type Environment = Readonly<Record<string, string | undefined>>;
const FAILURES = new Set(["invalid", "capacity", "project_changed", "context_unavailable", "context_changed", "revision_conflict", "agent_unavailable", "task_changed", "input_changed", "grant_changed", "agent_changed", "version_unavailable", "project_unavailable", "unavailable"]);
export class ProjectPlanBridgeError extends Error { constructor(readonly code = "unavailable", readonly status = 503) { super("project_plan_bridge_unavailable"); } }

function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN ?? ""); } catch { throw new ProjectPlanBridgeError(); }
  if (origin.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(origin.hostname) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new ProjectPlanBridgeError();
  return { origin: origin.origin, token };
}
async function boundedJson(response: Response): Promise<unknown> {
  const maximum = 128 * 1024, declared = response.headers.get("content-length");
  if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > maximum)) throw new ProjectPlanContractError();
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > maximum) { await reader.cancel(); throw new ProjectPlanContractError(); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new ProjectPlanContractError(); }
}

export async function projectPlanCapability<K extends ProjectPlanOperation>(operation: K, input: unknown, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<ProjectPlanResults[K]> {
  let request: Record<string, unknown>;
  try { request = projectPlanRequest(operation, input); } catch { throw new ProjectPlanBridgeError("invalid", 400); }
  const bridge = configuration(environment), read = PROJECT_PLAN_READS.has(operation);
  const url = new URL(`/bridge/v1/project-plans/${operation}`, bridge.origin);
  if (read) for (const [key, value] of Object.entries(request)) url.searchParams.set(key, String(value));
  try {
    const response = await fetcher(url, { method: read ? "GET" : "POST", ...(read ? {} : { body: JSON.stringify(request) }),
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(read ? 15_000 : 35_000),
      headers: { Accept: "application/json", ...(read ? {} : { "Content-Type": "application/json" }), ...ownerBridgeHeaders(), "X-Mentat-Bridge-Token": bridge.token } });
    const raw = await boundedJson(response);
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new ProjectPlanContractError();
    const payload = raw as Record<string, unknown>;
    if (response.status !== 200) {
      if (Object.keys(payload).sort().join(",") !== "schema_version,status" || payload.schema_version !== 1 || typeof payload.status !== "string" || !FAILURES.has(payload.status)) throw new ProjectPlanContractError();
      if (response.status === 400 && ["invalid", "capacity"].includes(payload.status)
        || response.status === 404 && ["version_unavailable", "project_unavailable"].includes(payload.status)
        || response.status === 409 && !["invalid", "unavailable", "version_unavailable", "project_unavailable"].includes(payload.status)
        || response.status === 503 && payload.status === "unavailable") throw new ProjectPlanBridgeError(payload.status, response.status);
      throw new ProjectPlanContractError();
    }
    if (Object.keys(payload).sort().join(",") !== "data,runtime,schema_version,service,status" || payload.schema_version !== 1 || payload.runtime !== "python" || payload.service !== "mentat-local-bridge" || payload.status !== "ready") throw new ProjectPlanContractError();
    return projectPlanResult(operation, payload.data, request);
  } catch (error) {
    if (error instanceof ProjectPlanBridgeError) throw error;
    throw new ProjectPlanBridgeError(error instanceof ProjectPlanContractError ? "invalid_response" : "unavailable", error instanceof ProjectPlanContractError ? 502 : 503);
  }
}
