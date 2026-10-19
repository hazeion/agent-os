import { ownerBridgeHeaders } from "./owner-request-context.ts";
import { taskInputEditor, taskInputPublished, taskInputRequest, parseTaskInputVersion, retiredTaskInputHistory, taskInputPrunePreview, taskInputPruned, TaskInputContractError, type TaskInputEditor, type TaskInputRequest, type RetiredTaskInputSummary, type TaskInputVersion } from "./task-input-contract.ts";

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
type Environment = Readonly<Record<string, string | undefined>>;
const FAILURES = new Set(["invalid", "revision_invalid", "instructions_invalid", "files_invalid", "task_changed", "grant_changed", "file_scope", "files_unavailable", "revision_conflict", "capacity", "image_limit", "version_unavailable", "adapter_limits_invalid", "project_unavailable", "context_unavailable", "agent_unavailable", "file_unavailable", "current_version", "retained_plan", "stale", "unavailable"]);
export class TaskInputBridgeError extends Error { constructor(readonly code = "unavailable", readonly status = 503) { super("task_input_unavailable"); } }
function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN ?? ""); } catch { throw new TaskInputBridgeError(); }
  if (origin.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(origin.hostname) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new TaskInputBridgeError();
  return { origin: origin.origin, token };
}
async function boundedJson(response: Response): Promise<unknown> {
  const maximum = 2 * 1024 * 1024;
  const declared = response.headers.get("content-length");
  if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > maximum)) throw new TaskInputContractError();
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let length = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; length += next.value.byteLength; if (length > maximum) { await reader.cancel(); throw new TaskInputContractError(); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; }
  catch { throw new TaskInputContractError(); }
}
type Operation = "task" | "version" | "publish" | "retired-history" | "retired-version" | "prune-preview" | "prune-confirm";
async function request(operation: Operation, body: Record<string, unknown>, fetcher: FetchLike, environment: Environment): Promise<unknown> {
  const bridge = configuration(environment); const read = ["task", "version", "retired-history", "retired-version"].includes(operation);
  const url = new URL(`/bridge/v1/task-inputs/${operation}`, bridge.origin);
  if (read) for (const [key, value] of Object.entries(body)) url.searchParams.set(key, String(value));
  try {
    const response = await fetcher(url, { method: read ? "GET" : "POST", ...(read ? {} : { body: JSON.stringify(body) }),
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(read ? 10_000 : 30_000),
      headers: { Accept: "application/json", ...(!read ? { "Content-Type": "application/json" } : {}), ...ownerBridgeHeaders(), "X-Mentat-Bridge-Token": bridge.token } });
    const raw = await boundedJson(response);
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new TaskInputContractError();
    const value = raw as Record<string, unknown>;
    if (response.status !== 200) {
      if (Object.keys(value).sort().join(",") !== "schema_version,status" || value.schema_version !== 1 || typeof value.status !== "string" || !FAILURES.has(value.status)) throw new TaskInputContractError();
      if (response.status === 400 && value.status === "invalid" || response.status === 409 && value.status !== "invalid" && value.status !== "unavailable" || response.status === 503 && value.status === "unavailable") throw new TaskInputBridgeError(value.status, response.status);
      throw new TaskInputContractError();
    }
    if (Object.keys(value).sort().join(",") !== "data,runtime,schema_version,service,status" || value.schema_version !== 1 || value.runtime !== "python" || value.service !== "mentat-local-bridge" || value.status !== "ready") throw new TaskInputContractError();
    return value.data;
  } catch (error) {
    if (error instanceof TaskInputBridgeError) throw error;
    throw new TaskInputBridgeError(error instanceof TaskInputContractError ? "invalid_response" : "unavailable", error instanceof TaskInputContractError ? 502 : 503);
  }
}
const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const VERSION = /^task_input_[0-9a-f]{32}$/u;
export async function readBridgeTaskInputs(taskId: string, inputId?: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<TaskInputEditor> {
  if (!TASK.test(taskId) || inputId !== undefined && !VERSION.test(inputId)) throw new TaskInputBridgeError("invalid", 400);
  const payload = await request(inputId === undefined ? "task" : "version", inputId === undefined ? { task_id: taskId } : { task_id: taskId, input_id: inputId }, fetcher, environment);
  try { return taskInputEditor(payload, taskId, inputId); } catch { throw new TaskInputBridgeError("invalid_response", 502); }
}
export async function publishBridgeTaskInputs(value: unknown, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<{ input_id: string; revision: number }> {
  let body: TaskInputRequest;
  try { body = taskInputRequest(value); } catch { throw new TaskInputBridgeError("invalid", 400); }
  const payload = await request("publish", body as unknown as Record<string, unknown>, fetcher, environment);
  try { return taskInputPublished(payload, body); } catch { throw new TaskInputBridgeError("invalid_response", 502); }
}
export async function readBridgeRetiredTaskInputs(fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<{ versions: RetiredTaskInputSummary[] }> {
  const payload = await request("retired-history", {}, fetcher, environment);
  try { return retiredTaskInputHistory(payload); } catch { throw new TaskInputBridgeError("invalid_response", 502); }
}
export async function readBridgeRetiredTaskInput(inputId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<TaskInputVersion> {
  if (!VERSION.test(inputId)) throw new TaskInputBridgeError("invalid", 400);
  const payload = await request("retired-version", { input_id: inputId }, fetcher, environment);
  try { const version = parseTaskInputVersion(payload); if (version.id !== inputId) throw new TaskInputContractError(); return version; } catch { throw new TaskInputBridgeError("invalid_response", 502); }
}
export async function previewBridgeTaskInputPrune(inputId: string, fetcher: FetchLike = fetch, environment: Environment = process.env) {
  if (!VERSION.test(inputId)) throw new TaskInputBridgeError("invalid", 400);
  const payload = await request("prune-preview", { input_id: inputId }, fetcher, environment);
  try { return taskInputPrunePreview(payload, inputId); } catch { throw new TaskInputBridgeError("invalid_response", 502); }
}
export async function confirmBridgeTaskInputPrune(inputId: string, confirmationId: string, fetcher: FetchLike = fetch, environment: Environment = process.env) {
  if (!VERSION.test(inputId) || !/^[0-9a-f]{64}$/u.test(confirmationId)) throw new TaskInputBridgeError("invalid", 400);
  const payload = await request("prune-confirm", { input_id: inputId, confirmation_id: confirmationId, confirmed: true }, fetcher, environment);
  try { return taskInputPruned(payload); } catch { throw new TaskInputBridgeError("invalid_response", 502); }
}
