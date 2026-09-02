import { BridgePlanningError } from "./bridge-planning.ts";
import { parsePlanningSearch, PublicPlanningSearchError, type PublicPlanningSearch } from "./public-planning-search.ts";

const PATH = "/bridge/v1/agent-console/planning-search";
const MAXIMUM_RESPONSE_BYTES = 64 * 1024;
const TIMEOUT_MILLISECONDS = 3_500;
type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

function validQuery(value: unknown): value is string { return typeof value === "string" && !!value && value.trim() === value && [...value].length <= 160 && !/\p{C}/u.test(value); }
function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? ""); } catch { throw new BridgePlanningError("bridge_configuration_invalid"); }
  const hostname = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (origin.protocol !== "http:" || !new Set(["127.0.0.1", "::1"]).has(hostname) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new BridgePlanningError("bridge_configuration_invalid");
  return { origin: origin.origin, token };
}
function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function validFailure(value: unknown): value is Record<string, unknown> { return record(value) && Object.keys(value).sort().join(",") === "runtime,schema_version,service,status" && value.schema_version === 1 && value.service === "mentat-local-bridge" && value.runtime === "python"; }
async function responseJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_RESPONSE_BYTES) || !response.body) throw new BridgePlanningError("bridge_response_invalid");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > MAXIMUM_RESPONSE_BYTES) { await reader.cancel(); throw new BridgePlanningError("bridge_response_invalid"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new BridgePlanningError("bridge_response_invalid"); }
}
function boundedSignal(signal: AbortSignal | undefined): AbortSignal {
  const timeout = AbortSignal.timeout(TIMEOUT_MILLISECONDS);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}
function failure(response: Response, payload: unknown): never {
  if (!validFailure(payload)) throw new BridgePlanningError("bridge_response_invalid");
  const mapped: Record<string, string> = { "400:invalid": "planning_request_invalid", "503:unavailable": "bridge_unavailable" };
  throw new BridgePlanningError(mapped[`${response.status}:${payload.status}`] ?? "bridge_response_invalid");
}

export async function fetchBridgePlanningSearch(query: string, fetcher: FetchLike = fetch, environment: Environment = process.env, signal?: AbortSignal): Promise<PublicPlanningSearch> {
  if (!validQuery(query)) throw new BridgePlanningError("planning_request_invalid");
  const bridge = configuration(environment);
  try {
    const response = await fetcher(new URL(`${PATH}?${new URLSearchParams({ q: query }).toString()}`, bridge.origin), { cache: "no-store", headers: { Accept: "application/json", "X-Mentat-Bridge-Token": bridge.token }, method: "GET", redirect: "error", signal: boundedSignal(signal) });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new BridgePlanningError("bridge_response_invalid");
    const payload = await responseJson(response);
    if (response.status === 200) {
      try { return parsePlanningSearch(payload, query); } catch (error) { if (error instanceof PublicPlanningSearchError) throw new BridgePlanningError("bridge_response_invalid"); throw error; }
    }
    failure(response, payload);
  } catch (error) { if (error instanceof BridgePlanningError) throw error; throw new BridgePlanningError("bridge_unavailable"); }
}
