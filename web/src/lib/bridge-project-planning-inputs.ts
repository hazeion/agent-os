import { ownerBridgeHeaders } from "./owner-request-context.ts";
import { ProjectInputContractError, projectInputRequest, projectInputResult, type ProjectInputOperation, type ProjectInputResults } from "./project-planning-input-contract.ts";

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
type Environment = Readonly<Record<string, string | undefined>>;
const FAILURES = new Set(["invalid", "version_unavailable", "project_unavailable", "capacity", "project_changed", "scope_changed", "lead_changed", "context_changed", "revision_conflict", "selection_changed", "file_scope", "files_unavailable", "image_limit", "action_conflict", "unavailable"]);
export class ProjectInputBridgeError extends Error { constructor(readonly code = "unavailable", readonly status = 503) { super(code); } }

function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN ?? ""); } catch { throw new ProjectInputBridgeError(); }
  if (origin.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(origin.hostname) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new ProjectInputBridgeError();
  return { origin: origin.origin, token };
}
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

export async function projectInputCapability<K extends ProjectInputOperation>(operation: K, input: unknown, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<ProjectInputResults[K]> {
  let request: Record<string, unknown>;
  try { request = projectInputRequest(operation, input); } catch { throw new ProjectInputBridgeError("invalid", 400); }
  const bridge = configuration(environment), read = operation !== "publish";
  const url = new URL(`/bridge/v1/project-planning-inputs/${operation}`, bridge.origin);
  if (read) for (const [key, value] of Object.entries(request)) url.searchParams.set(key, String(value));
  try {
    const response = await fetcher(url, { method: read ? "GET" : "POST", cache: "no-store", redirect: "error",
      signal: AbortSignal.timeout(read ? 15_000 : 35_000),
      headers: { Accept: "application/json", ...(read ? {} : { "Content-Type": "application/json" }), ...ownerBridgeHeaders(), "X-Mentat-Bridge-Token": bridge.token },
      ...(read ? {} : { body: JSON.stringify(request) }) });
    const payload = await boundedJson(response);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new ProjectInputContractError();
    const value = payload as Record<string, unknown>;
    if (response.status !== 200) {
      if (Object.keys(value).sort().join(",") !== "schema_version,status" || value.schema_version !== 1 || typeof value.status !== "string" || !FAILURES.has(value.status)) throw new ProjectInputContractError();
      if (response.status === 400 && value.status === "invalid"
        || response.status === 404 && ["version_unavailable", "project_unavailable"].includes(value.status)
        || response.status === 409 && !["invalid", "version_unavailable", "project_unavailable", "unavailable"].includes(value.status)
        || response.status === 503 && value.status === "unavailable") throw new ProjectInputBridgeError(value.status, response.status);
      throw new ProjectInputContractError();
    }
    if (Object.keys(value).sort().join(",") !== "data,runtime,schema_version,service,status" || value.schema_version !== 1 || value.runtime !== "python" || value.service !== "mentat-local-bridge" || value.status !== "ready") throw new ProjectInputContractError();
    return projectInputResult(operation, value.data, request);
  } catch (error) {
    if (error instanceof ProjectInputBridgeError) throw error;
    throw new ProjectInputBridgeError(error instanceof ProjectInputContractError ? "invalid_response" : "unavailable", error instanceof ProjectInputContractError ? 502 : 503);
  }
}
