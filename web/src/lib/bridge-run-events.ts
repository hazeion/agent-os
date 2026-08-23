import { createHash } from "node:crypto";

const PRIVATE_PATH_PREFIX = "/bridge/v1/runs/";
const MAX_BYTES = 262_144;
const MAX_EVENTS = 100;
const RUN_ID = /^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/u;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u;
const EVENT_TYPES = new Set(["run.created", "dispatch.reserved", "run.started", "submission.unknown", "run.interrupted", "tool.requested", "tool.completed", "approval.required", "artifact.created", "cost", "run.stopped", "run.completed", "run.failed", "message"]);
const METRICS = new Set(["input_tokens", "output_tokens", "total_tokens", "context_tokens", "context_length"]);

type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export type PublicRunEvent = { id: string; run_id: string; sequence: number; type: string; occurred_at: string; summary: string; message: string | null; metrics: Record<string, number> };
export type PublicBridgeRunEvents = { schema_version: 1; service: "mentat-local-bridge"; runtime: "python"; status: "ready"; run_id: string; after: number; next_cursor: number; cursor_reset_required: boolean; events: PublicRunEvent[] };

export class BridgeRunEventsError extends Error {
  readonly code: string;

  constructor(code: string) { super(code); this.code = code; this.name = "BridgeRunEventsError"; }
}

function config(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? ""); } catch { throw new BridgeRunEventsError("bridge_configuration_invalid"); }
  const host = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (origin.protocol !== "http:" || !new Set(["127.0.0.1", "::1"]).has(host) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new BridgeRunEventsError("bridge_configuration_invalid");
  return { origin: origin.origin, token };
}

function cursor(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= 1_000_000_000; }
function timestamp(value: unknown): value is string { return typeof value === "string" && value.length > 0 && value.length <= 40 && TIMESTAMP.test(value) && !Number.isNaN(Date.parse(value)); }
function trustedVercelMessageId(runId: string): string {
  const source = `vercel_message_${createHash("sha256").update(`${runId}:message`, "utf8").digest("hex").slice(0, 24)}`;
  return `event_${createHash("sha256").update(`${runId}:${source}`, "utf8").digest("hex").slice(0, 24)}`;
}
function validEvent(value: unknown, runId: string): value is PublicRunEvent {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const event = value as Record<string, unknown>;
  if (Object.keys(event).sort().join(",") !== "id,message,metrics,occurred_at,run_id,sequence,summary,type") return false;
  if (typeof event.id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(event.id) || event.run_id !== runId || !cursor(event.sequence) || event.sequence < 1 || typeof event.type !== "string" || !EVENT_TYPES.has(event.type) || !timestamp(event.occurred_at) || typeof event.summary !== "string" || event.summary.length === 0 || event.summary.length > 500 || event.summary.trim() !== event.summary || event.summary.includes("\0") || (event.message !== null && (event.type !== "message" || event.id !== trustedVercelMessageId(runId) || typeof event.message !== "string" || event.message.length === 0 || event.message.length > 20_000 || event.message.trim() !== event.message || event.message.includes("\0"))) || !event.metrics || typeof event.metrics !== "object" || Array.isArray(event.metrics)) return false;
  const metricMap = event.metrics as Record<string, unknown>;
  return Object.entries(metricMap).every(([name, metric]) => typeof metric === "number" && METRICS.has(name) && Number.isSafeInteger(metric) && metric >= 0 && metric <= 1_000_000_000);
}
function fixed(payload: unknown, expected: string) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  const item = payload as Record<string, unknown>;
  return Object.keys(item).sort().join(",") === "runtime,schema_version,service,status" && item.schema_version === 1 && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === expected;
}
async function bounded(response: Response) {
  const length = response.headers.get("content-length");
  if (length && (!/^\d{1,10}$/u.test(length) || Number(length) > MAX_BYTES)) throw new BridgeRunEventsError("bridge_response_invalid");
  if (!response.body) throw new BridgeRunEventsError("bridge_response_invalid");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { while (true) { const { done, value } = await reader.read(); if (done) break; total += value.byteLength; if (total > MAX_BYTES) { await reader.cancel(); throw new BridgeRunEventsError("bridge_response_invalid"); } chunks.push(value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new BridgeRunEventsError("bridge_response_invalid"); }
}

export function validRunId(value: unknown): value is string { return typeof value === "string" && RUN_ID.test(value); }
export function validCursor(value: unknown): value is number { return cursor(value); }
export function lastEventCursor(value: string | null): number | null {
  if (value === null || value === "") return 0;
  if (!/^\d{1,10}$/u.test(value)) return null;
  const parsed = Number(value);
  return validCursor(parsed) ? parsed : null;
}

export async function fetchBridgeRunEvents(runId: string, after: number, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicBridgeRunEvents> {
  if (!validRunId(runId) || !validCursor(after)) throw new BridgeRunEventsError("request_invalid");
  const bridge = config(environment); let response: Response;
  const path = `${PRIVATE_PATH_PREFIX}${encodeURIComponent(runId)}/events?after=${after}`;
  try { response = await fetcher(new URL(path, bridge.origin), { method: "GET", cache: "no-store", redirect: "error", headers: { Accept: "application/json", "X-Mentat-Bridge-Token": bridge.token }, signal: AbortSignal.timeout(1500) }); } catch { throw new BridgeRunEventsError("bridge_unavailable"); }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new BridgeRunEventsError("bridge_response_invalid");
  const payload = await bounded(response);
  if (response.status === 200 && payload && typeof payload === "object" && !Array.isArray(payload)) {
    const item = payload as Record<string, unknown>; const events = item.events;
    const messageCount = Array.isArray(events) ? events.filter((event) => (event as PublicRunEvent)?.message !== null).length : 0;
    if (Object.keys(item).sort().join(",") === "after,cursor_reset_required,events,next_cursor,run_id,runtime,schema_version,service,status" && item.schema_version === 1 && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === "ready" && item.run_id === runId && item.after === after && cursor(item.next_cursor) && typeof item.cursor_reset_required === "boolean" && Array.isArray(events) && events.length <= MAX_EVENTS && messageCount <= 1 && events.every((event) => validEvent(event, runId))) {
      const sequences = events.map((event) => event.sequence);
      const continuous = sequences.every((sequence, index) => index === 0 || sequence === sequences[index - 1] + 1);
      if (new Set(sequences).size === sequences.length && sequences.every((sequence) => sequence > after) && continuous && (!sequences.length || sequences.at(-1) === item.next_cursor) && (item.cursor_reset_required || item.next_cursor === after + sequences.length)) return { ...item, events: events.map((event) => ({ ...event, metrics: { ...event.metrics } })) } as PublicBridgeRunEvents;
    }
  }
  if (response.status === 404 && fixed(payload, "not_found")) throw new BridgeRunEventsError("run_not_found");
  if (response.status === 501 && fixed(payload, "unsupported")) throw new BridgeRunEventsError("bridge_unsupported");
  if (response.status === 503 && fixed(payload, "unavailable")) throw new BridgeRunEventsError("bridge_unavailable");
  throw new BridgeRunEventsError("bridge_response_invalid");
}
