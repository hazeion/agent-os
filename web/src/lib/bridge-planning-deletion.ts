import { BridgePlanningError, PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS } from "./bridge-planning.ts";
import {
  parsePlanningDeletionMutation,
  parsePlanningDeletionPreview,
  type PlanningDeletionTargetKind,
  PublicPlanningDeletionError,
  type PublicPlanningDeletionMutation,
  type PublicPlanningDeletionPreview,
} from "./public-planning-deletion.ts";

const PREVIEW_PATH = "/bridge/v1/agent-console/planning-deletion/preview";
const CONFIRM_PATH = "/bridge/v1/agent-console/planning-deletion/confirm";
const PROJECT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const CONFIRMATION = /^[0-9a-f]{64}$/u;
const MAXIMUM_RESPONSE_BYTES = 64 * 1024;
type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

function validTarget(kind: unknown, id: unknown): kind is PlanningDeletionTargetKind { return kind === "task" && typeof id === "string" && TASK.test(id) || kind === "project" && typeof id === "string" && PROJECT.test(id); }
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
function failure(response: Response, payload: unknown): never {
  if (!validFailure(payload)) throw new BridgePlanningError("bridge_response_invalid");
  const mapped: Record<string, string> = { "400:invalid": "planning_request_invalid", "404:not_found": "planning_not_found", "409:conflict": "planning_conflict", "409:active_run": "planning_active_run", "409:queue_active": "planning_queue_active", "501:unsupported": "bridge_unsupported", "503:unavailable": "bridge_unavailable" };
  throw new BridgePlanningError(mapped[`${response.status}:${payload.status}`] ?? "bridge_response_invalid");
}
async function responseJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_RESPONSE_BYTES) || !response.body) throw new BridgePlanningError("bridge_response_invalid");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > MAXIMUM_RESPONSE_BYTES) { await reader.cancel(); throw new BridgePlanningError("bridge_response_invalid"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new BridgePlanningError("bridge_response_invalid"); }
}
async function request(path: string, body: Record<string, unknown>, fetcher: FetchLike, environment: Environment) {
  const bridge = configuration(environment);
  try {
    const response = await fetcher(new URL(path, bridge.origin), { body: JSON.stringify(body), cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json", "X-Mentat-Bridge-Token": bridge.token }, method: "POST", redirect: "error", signal: AbortSignal.timeout(PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS) });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new BridgePlanningError("bridge_response_invalid");
    return { response, payload: await responseJson(response) };
  } catch (error) { if (error instanceof BridgePlanningError) throw error; throw new BridgePlanningError("bridge_unavailable"); }
}
function parse<T>(operation: () => T): T { try { return operation(); } catch (error) { if (error instanceof PublicPlanningDeletionError) throw new BridgePlanningError("bridge_response_invalid"); throw error; } }

export async function previewBridgePlanningDeletion(targetKind: PlanningDeletionTargetKind, targetId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningDeletionPreview> {
  if (!validTarget(targetKind, targetId)) throw new BridgePlanningError("planning_request_invalid");
  const { response, payload } = await request(PREVIEW_PATH, { target_id: targetId, target_kind: targetKind }, fetcher, environment);
  if (response.status === 200) return parse(() => parsePlanningDeletionPreview(payload, targetKind, targetId));
  failure(response, payload);
}

export async function confirmBridgePlanningDeletion(targetKind: PlanningDeletionTargetKind, targetId: string, confirmationId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningDeletionMutation> {
  if (!validTarget(targetKind, targetId) || typeof confirmationId !== "string" || !CONFIRMATION.test(confirmationId)) throw new BridgePlanningError("planning_request_invalid");
  const { response, payload } = await request(CONFIRM_PATH, { confirmation_id: confirmationId, confirmed: true, target_id: targetId, target_kind: targetKind }, fetcher, environment);
  if (response.status === 200) return parse(() => parsePlanningDeletionMutation(payload, targetKind, targetId));
  failure(response, payload);
}
