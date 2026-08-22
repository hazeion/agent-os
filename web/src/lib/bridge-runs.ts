export const PUBLIC_RUNS_PATH = "/api/runs";
const PRIVATE_PATH = "/bridge/v1/runs";
const MAX_BYTES = 1_048_576;
type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
export type PublicRun = { id: string; source: string; task_id: string | null; agent_id: string | null; runtime_type: string; status: string; dispatch_state: string; partial: boolean; timeline_truncated: boolean; created_at: string; updated_at: string; started_at: string | null; completed_at: string | null };
export type PublicBridgeRuns = { schema_version: 1; service: "mentat-local-bridge"; runtime: "python"; status: "ready"; runs: PublicRun[]; count: number };
export class BridgeRunsError extends Error { readonly code: string; constructor(code: string) { super(code); this.code = code; this.name = "BridgeRunsError"; } }
function config(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? ""; let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? ""); } catch { throw new BridgeRunsError("bridge_configuration_invalid"); }
  const host = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (origin.protocol !== "http:" || !new Set(["127.0.0.1", "::1"]).has(host) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new BridgeRunsError("bridge_configuration_invalid");
  return { origin: origin.origin, token };
}
const timestamp = (value: unknown) => typeof value === "string" && value.length > 0 && value.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u.test(value) && !Number.isNaN(Date.parse(value));
function validRun(value: unknown): value is PublicRun {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const run = value as Record<string, unknown>;
  return Object.keys(run).sort().join(",") === "agent_id,completed_at,created_at,dispatch_state,id,partial,runtime_type,source,started_at,status,task_id,timeline_truncated,updated_at"
    && typeof run.id === "string" && /^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/u.test(run.id)
    && typeof run.source === "string" && /^[a-z][a-z0-9_.-]{0,63}$/u.test(run.source)
    && (run.task_id === null || typeof run.task_id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u.test(run.task_id))
    && (run.agent_id === null || typeof run.agent_id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(run.agent_id))
    && typeof run.runtime_type === "string" && /^[a-z][a-z0-9_-]{0,31}$/u.test(run.runtime_type)
    && ["reserved", "queued", "submitting", "starting", "running", "cancelling", "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown", "completed", "failed", "cancelled", "stopped", "interrupted"].includes(run.status as string)
    && ["legacy", "reserved", "submitting", "accepted", "rejected", "unknown"].includes(run.dispatch_state as string)
    && typeof run.partial === "boolean" && typeof run.timeline_truncated === "boolean" && timestamp(run.created_at) && timestamp(run.updated_at)
    && (run.started_at === null || timestamp(run.started_at)) && (run.completed_at === null || timestamp(run.completed_at));
}
function fixed(payload: unknown, expected: string) { if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false; const item = payload as Record<string, unknown>; return Object.keys(item).sort().join(",") === "runtime,schema_version,service,status" && item.schema_version === 1 && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === expected; }
async function bounded(response: Response) {
  const length = response.headers.get("content-length"); if (length && (!/^\d{1,10}$/u.test(length) || Number(length) > MAX_BYTES)) throw new BridgeRunsError("bridge_response_invalid");
  if (!response.body) throw new BridgeRunsError("bridge_response_invalid"); const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { while (true) { const { done, value } = await reader.read(); if (done) break; total += value.byteLength; if (total > MAX_BYTES) { await reader.cancel(); throw new BridgeRunsError("bridge_response_invalid"); } chunks.push(value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new BridgeRunsError("bridge_response_invalid"); }
}
export async function fetchBridgeRuns(fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicBridgeRuns> {
  const bridge = config(environment); let response: Response;
  try { response = await fetcher(new URL(PRIVATE_PATH, bridge.origin), { method: "GET", cache: "no-store", redirect: "error", headers: { Accept: "application/json", "X-Mentat-Bridge-Token": bridge.token }, signal: AbortSignal.timeout(1500) }); } catch { throw new BridgeRunsError("bridge_unavailable"); }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new BridgeRunsError("bridge_response_invalid"); const payload = await bounded(response);
  if (response.status === 200 && payload && typeof payload === "object" && !Array.isArray(payload)) { const item = payload as Record<string, unknown>; if (Object.keys(item).sort().join(",") === "count,runs,runtime,schema_version,service,status" && item.schema_version === 1 && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === "ready" && Array.isArray(item.runs) && item.runs.length <= 50 && Number.isInteger(item.count) && item.count === item.runs.length && item.runs.every(validRun) && new Set(item.runs.map((run) => run.id)).size === item.runs.length) return { ...item, runs: item.runs.map((run) => ({ ...run })) } as PublicBridgeRuns; }
  if (response.status === 404 && payload && typeof payload === "object" && !Array.isArray(payload) && Object.keys(payload).join(",") === "error" && (payload as Record<string, unknown>).error === "bridge_route_not_found") throw new BridgeRunsError("bridge_unsupported");
  if (response.status === 501 && fixed(payload, "unsupported")) throw new BridgeRunsError("bridge_unsupported"); if (response.status === 503 && fixed(payload, "unavailable")) throw new BridgeRunsError("bridge_unavailable"); throw new BridgeRunsError("bridge_response_invalid");
}
