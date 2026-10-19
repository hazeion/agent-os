import { ownerBridgeHeaders } from "./owner-request-context.ts";
import { CONTEXT_READS, CONTEXT_UPLOAD_LIMIT, contextRequest, contextResult, ContextContractError, type ContextOperation, type ContextResults } from "./project-context-contract.ts";

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
type Environment = Readonly<Record<string, string | undefined>>;
const FAILURES = new Set(["invalid", "file_unavailable", "stale", "project_changed", "project_unavailable", "context_unavailable", "agent_unavailable", "version_unavailable", "current_version", "granted_version", "task_input", "capacity", "blob_capacity", "staging_changed", "revision_conflict", "file_scope", "files_invalid", "brief_invalid", "revision_invalid", "confirmation_invalid", "unavailable"]);
export class ProjectContextBridgeError extends Error {
  constructor(readonly code = "unavailable", readonly status = 503) { super("project_context_unavailable"); }
}
function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN ?? ""); } catch { throw new ProjectContextBridgeError(); }
  if (origin.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(origin.hostname) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new ProjectContextBridgeError();
  return { origin: origin.origin, token };
}
async function boundedJson(response: Response, maximum: number): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > maximum)) throw new ContextContractError();
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let length = 0;
  try {
    for (;;) { const next = await reader.read(); if (next.done) break; length += next.value.byteLength; if (length > maximum) { await reader.cancel(); throw new ContextContractError(); } chunks.push(next.value); }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
}
/** Fixed private capabilities. GET reads retain independent session admission. */
export async function projectContextCapability<K extends ContextOperation>(operation: K, input: unknown, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<ContextResults[K]> {
  let request: Record<string, unknown>;
  try { request = contextRequest(operation, input); } catch { throw new ProjectContextBridgeError("invalid", 400); }
  const bridge = configuration(environment); const read = CONTEXT_READS.has(operation);
  const url = new URL(`/bridge/v1/project-context/${operation}`, bridge.origin);
  if (read) for (const [key, value] of Object.entries(request)) url.searchParams.set(key, String(value));
  try {
    const response = await fetcher(url, {
      method: read ? "GET" : "POST", ...(read ? {} : { body: JSON.stringify(request) }),
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(30_000),
      headers: { Accept: "application/json", ...(!read ? { "Content-Type": "application/json" } : {}), ...ownerBridgeHeaders(), "X-Mentat-Bridge-Token": bridge.token },
    });
    const raw = await boundedJson(response, operation === "file" ? CONTEXT_UPLOAD_LIMIT : 512 * 1024);
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new ContextContractError();
    const payload = raw as Record<string, unknown>;
    if (response.status !== 200) {
      if (Object.keys(payload).sort().join(",") !== "schema_version,status" || payload.schema_version !== 1 || typeof payload.status !== "string" || !FAILURES.has(payload.status)) throw new ContextContractError();
      if (response.status === 400 && payload.status === "invalid" || response.status === 409 && payload.status !== "invalid" || response.status === 503 && payload.status === "unavailable") throw new ProjectContextBridgeError(payload.status, response.status);
      throw new ContextContractError();
    }
    if (Object.keys(payload).sort().join(",") !== "data,runtime,schema_version,service,status" || payload.schema_version !== 1 || payload.runtime !== "python" || payload.service !== "mentat-local-bridge" || payload.status !== "ready") throw new ContextContractError();
    const result = contextResult(operation, payload.data, request);
    if (operation === "file") {
      const file = result as ContextResults["file"];
      const bytes = Buffer.from(file.content_base64, "base64");
      if (bytes.length !== file.file.byte_size || bytes.toString("base64") !== file.content_base64) throw new ContextContractError();
    }
    return result;
  } catch (error) {
    if (error instanceof ProjectContextBridgeError) throw error;
    throw new ProjectContextBridgeError(error instanceof ContextContractError ? "invalid_response" : "unavailable", error instanceof ContextContractError ? 502 : 503);
  }
}
