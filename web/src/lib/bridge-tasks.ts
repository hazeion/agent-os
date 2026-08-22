export const PUBLIC_TASKS_PATH = "/api/tasks";
const PRIVATE_PATH = "/bridge/v1/tasks";
const MAX_BYTES = 1_048_576;

type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export type PublicTask = { id: string; title: string; project: string; status: string; priority: string; due_date: string | null; tags: string[]; needs_attention: boolean; review_required: boolean; updated_at: string };
export type PublicBridgeTasks = { schema_version: 1; service: "mentat-local-bridge"; runtime: "python"; status: "ready"; tasks: PublicTask[]; count: number };

export class BridgeTasksError extends Error {
  readonly code: string;

  constructor(code: string) { super(code); this.code = code; this.name = "BridgeTasksError"; }
}

function config(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? ""); } catch { throw new BridgeTasksError("bridge_configuration_invalid"); }
  const host = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (origin.protocol !== "http:" || !new Set(["127.0.0.1", "::1"]).has(host) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new BridgeTasksError("bridge_configuration_invalid");
  return { origin: origin.origin, token };
}

const validText = (value: unknown, max: number) => typeof value === "string" && value.trim() === value && value.length > 0 && value.length <= max && !value.includes("\0");
function validTask(value: unknown): value is PublicTask {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const task = value as Record<string, unknown>;
  return Object.keys(task).sort().join(",") === "due_date,id,needs_attention,priority,project,review_required,status,tags,title,updated_at"
    && typeof task.id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u.test(task.id)
    && validText(task.title, 160) && validText(task.project, 120)
    && ["todo", "in progress", "waiting", "needs attention", "completed"].includes(task.status as string)
    && ["high", "medium", "low"].includes(task.priority as string)
    && (task.due_date === null || typeof task.due_date === "string" && /^\d{4}-\d{2}-\d{2}$/u.test(task.due_date))
    && Array.isArray(task.tags) && task.tags.length <= 64 && task.tags.every((tag) => validText(tag, 48))
    && new Set(task.tags).size === task.tags.length && typeof task.needs_attention === "boolean" && typeof task.review_required === "boolean"
    && typeof task.updated_at === "string" && task.updated_at.length <= 40;
}
function fixed(payload: unknown, expected: string) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  const item = payload as Record<string, unknown>;
  return Object.keys(item).sort().join(",") === "runtime,schema_version,service,status" && item.schema_version === 1 && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === expected;
}
async function bounded(response: Response) {
  const length = response.headers.get("content-length");
  if (length && (!/^\d{1,10}$/u.test(length) || Number(length) > MAX_BYTES)) throw new BridgeTasksError("bridge_response_invalid");
  if (!response.body) throw new BridgeTasksError("bridge_response_invalid");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { while (true) { const { done, value } = await reader.read(); if (done) break; total += value.byteLength; if (total > MAX_BYTES) { await reader.cancel(); throw new BridgeTasksError("bridge_response_invalid"); } chunks.push(value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let raw: string; try { raw = new TextDecoder("utf-8", { fatal: true }).decode(bytes); } catch { throw new BridgeTasksError("bridge_response_invalid"); }
  try { return JSON.parse(raw) as unknown; } catch { throw new BridgeTasksError("bridge_response_invalid"); }
}
export async function fetchBridgeTasks(fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicBridgeTasks> {
  const bridge = config(environment); let response: Response;
  try { response = await fetcher(new URL(PRIVATE_PATH, bridge.origin), { method: "GET", cache: "no-store", redirect: "error", headers: { Accept: "application/json", "X-Mentat-Bridge-Token": bridge.token }, signal: AbortSignal.timeout(1500) }); } catch { throw new BridgeTasksError("bridge_unavailable"); }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new BridgeTasksError("bridge_response_invalid");
  const payload = await bounded(response);
  if (response.status === 200 && payload && typeof payload === "object" && !Array.isArray(payload)) {
    const item = payload as Record<string, unknown>;
    if (Object.keys(item).sort().join(",") === "count,runtime,schema_version,service,status,tasks" && item.schema_version === 1 && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === "ready" && Array.isArray(item.tasks) && item.tasks.length <= 2048 && Number.isInteger(item.count) && item.count === item.tasks.length && item.tasks.every(validTask) && new Set(item.tasks.map((task) => task.id)).size === item.tasks.length) return { ...item, tasks: item.tasks.map((task) => ({ ...task, tags: [...task.tags] })) } as PublicBridgeTasks;
  }
  if (response.status === 404 && payload && typeof payload === "object" && !Array.isArray(payload) && Object.keys(payload).join(",") === "error" && (payload as Record<string, unknown>).error === "bridge_route_not_found") throw new BridgeTasksError("bridge_unsupported");
  if (response.status === 501 && fixed(payload, "unsupported")) throw new BridgeTasksError("bridge_unsupported");
  if (response.status === 503 && fixed(payload, "unavailable")) throw new BridgeTasksError("bridge_unavailable");
  throw new BridgeTasksError("bridge_response_invalid");
}
