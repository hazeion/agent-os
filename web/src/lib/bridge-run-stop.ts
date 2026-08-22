import { validRunId } from "./bridge-run-events.ts";

const PRIVATE_PATH = "/bridge/v1/runs/";
const MAX_BYTES = 4_096;
type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
export type RunStopPreview = { schema_version: 1; service: "mentat-local-bridge"; runtime: "python"; status: "ready"; action: "stop"; run_id: string; requires_confirmation: true; confirmation_id: string };
export type RunStopResult = { schema_version: 1; service: "mentat-local-bridge"; runtime: "python"; status: "ready"; action: "stop"; run_id: string; disposition: "requested" };
export class BridgeRunStopError extends Error { readonly code: string; constructor(code: string) { super(code); this.code = code; this.name = "BridgeRunStopError"; } }

function config(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? ""; let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? ""); } catch { throw new BridgeRunStopError("bridge_configuration_invalid"); }
  const host = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (origin.protocol !== "http:" || !new Set(["127.0.0.1", "::1"]).has(host) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new BridgeRunStopError("bridge_configuration_invalid");
  return { origin: origin.origin, token };
}
async function bounded(response: Response): Promise<unknown> {
  const length = response.headers.get("content-length"); if (length && (!/^\d{1,10}$/u.test(length) || Number(length) > MAX_BYTES)) throw new BridgeRunStopError("bridge_response_invalid");
  const text = await response.text(); if (new TextEncoder().encode(text).byteLength > MAX_BYTES) throw new BridgeRunStopError("bridge_response_invalid");
  try { return JSON.parse(text) as unknown; } catch { throw new BridgeRunStopError("bridge_response_invalid"); }
}
function fixed(payload: unknown, expected: string): boolean { return !!payload && typeof payload === "object" && !Array.isArray(payload) && Object.keys(payload as object).sort().join(",") === "runtime,schema_version,service,status" && (payload as Record<string, unknown>).schema_version === 1 && (payload as Record<string, unknown>).service === "mentat-local-bridge" && (payload as Record<string, unknown>).runtime === "python" && (payload as Record<string, unknown>).status === expected; }
function actionPath(runId: string, suffix: string) { return `${PRIVATE_PATH}${encodeURIComponent(runId)}/stop${suffix}`; }
async function request(runId: string, suffix: string, body: object, fetcher: FetchLike, environment: Environment): Promise<{ response: Response; payload: unknown }> {
  if (!validRunId(runId)) throw new BridgeRunStopError("request_invalid");
  const bridge = config(environment); let response: Response;
  try { response = await fetcher(new URL(actionPath(runId, suffix), bridge.origin), { method: "POST", cache: "no-store", redirect: "error", headers: { Accept: "application/json", "Content-Type": "application/json", "X-Mentat-Bridge-Token": bridge.token }, body: JSON.stringify(body), signal: AbortSignal.timeout(1_500) }); } catch { throw new BridgeRunStopError("bridge_unavailable"); }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new BridgeRunStopError("bridge_response_invalid");
  return { response, payload: await bounded(response) };
}
function failure(response: Response, payload: unknown): never {
  if (response.status === 404 && fixed(payload, "not_found")) throw new BridgeRunStopError("run_not_found");
  if (response.status === 409 && fixed(payload, "conflict")) throw new BridgeRunStopError("action_conflict");
  if (response.status === 501 && fixed(payload, "unsupported")) throw new BridgeRunStopError("action_unsupported");
  if (response.status === 503 && fixed(payload, "unavailable")) throw new BridgeRunStopError("bridge_unavailable");
  throw new BridgeRunStopError("bridge_response_invalid");
}
export async function fetchBridgeRunStopPreview(runId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<RunStopPreview> {
  const { response, payload } = await request(runId, "/preview", {}, fetcher, environment);
  if (response.status === 200 && payload && typeof payload === "object" && !Array.isArray(payload)) { const item = payload as Record<string, unknown>; if (Object.keys(item).sort().join(",") === "action,confirmation_id,requires_confirmation,run_id,runtime,schema_version,service,status" && item.schema_version === 1 && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === "ready" && item.action === "stop" && item.run_id === runId && item.requires_confirmation === true && typeof item.confirmation_id === "string" && /^[0-9a-f]{64}$/u.test(item.confirmation_id)) return item as RunStopPreview; }
  return failure(response, payload);
}
export async function confirmBridgeRunStop(runId: string, confirmationId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<RunStopResult> {
  if (!/^[0-9a-f]{64}$/u.test(confirmationId)) throw new BridgeRunStopError("request_invalid");
  const { response, payload } = await request(runId, "", { confirmation_id: confirmationId }, fetcher, environment);
  if (response.status === 202 && payload && typeof payload === "object" && !Array.isArray(payload)) { const item = payload as Record<string, unknown>; if (Object.keys(item).sort().join(",") === "action,disposition,run_id,runtime,schema_version,service,status" && item.schema_version === 1 && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === "ready" && item.action === "stop" && item.run_id === runId && item.disposition === "requested") return item as RunStopResult; }
  return failure(response, payload);
}
