import { ownerFetch } from "../../public/owner-session.js";
import { taskInputEditor, taskInputPublished, taskInputRequest, parseTaskInputVersion, retiredTaskInputHistory, taskInputPrunePreview, taskInputPruned, TaskInputContractError, type TaskInputEditor, type TaskInputRequest, type TaskInputVersion, type RetiredTaskInputSummary } from "./task-input-contract.ts";

export class PublicTaskInputError extends Error { constructor(readonly code: string) { super(code); } }
const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const INPUT = /^task_input_[0-9a-f]{32}$/u;
const FAILURES = new Set(["invalid", "task_changed", "grant_changed", "file_scope", "files_unavailable", "revision_conflict", "capacity", "image_limit", "version_unavailable", "project_unavailable", "context_unavailable", "agent_unavailable", "file_unavailable", "current_version", "retained_plan", "stale", "unavailable"]);
async function readJson(response: Response): Promise<unknown> {
  if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new PublicTaskInputError("invalid_response");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let length = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; length += next.value.byteLength; if (length > 2 * 1024 * 1024) { await reader.cancel(); throw new PublicTaskInputError("invalid_response"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new PublicTaskInputError("invalid_response"); }
}
async function request(url: string, method: "GET" | "POST", body?: unknown): Promise<unknown> {
  try {
    const response = await ownerFetch(url, { method, cache: "no-store", credentials: "same-origin", redirect: "error",
      signal: AbortSignal.timeout(method === "GET" ? 15_000 : 35_000),
      headers: { Accept: "application/json", ...(method === "POST" ? { "Content-Type": "application/json" } : {}) },
      ...(method === "POST" ? { body: JSON.stringify(body) } : {}) });
    const payload = await readJson(response);
    if (response.status !== 200) {
      const status = payload && typeof payload === "object" && !Array.isArray(payload) && "status" in payload ? String(payload.status) : "unavailable";
      throw new PublicTaskInputError(FAILURES.has(status) ? status : "unavailable");
    }
    return payload;
  } catch (error) { if (error instanceof PublicTaskInputError) throw error; throw new PublicTaskInputError("unavailable"); }
}
export async function readTaskInputs(taskId: string, inputId?: string): Promise<TaskInputEditor> {
  if (!TASK.test(taskId) || inputId !== undefined && !INPUT.test(inputId)) throw new PublicTaskInputError("invalid");
  const suffix = inputId ? `/${inputId}` : "";
  const payload = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/inputs${suffix}`, "GET");
  try { return taskInputEditor(payload, taskId, inputId); } catch { throw new PublicTaskInputError("invalid_response"); }
}
export async function publishTaskInputs(value: unknown): Promise<{ input_id: string; revision: number }> {
  let input: TaskInputRequest;
  try { input = taskInputRequest(value); } catch (error) { if (error instanceof TaskInputContractError) throw new PublicTaskInputError("invalid"); throw error; }
  const { task_id: taskId, ...body } = input;
  const payload = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/inputs`, "POST", body);
  try { return taskInputPublished(payload, input); } catch { throw new PublicTaskInputError("invalid_response"); }
}
export async function readRetiredTaskInputs(): Promise<{ versions: RetiredTaskInputSummary[] }> {
  const payload = await request("/api/task-inputs/history", "GET");
  try { return retiredTaskInputHistory(payload); } catch { throw new PublicTaskInputError("invalid_response"); }
}
export async function readRetiredTaskInput(inputId: string): Promise<TaskInputVersion> {
  if (!INPUT.test(inputId)) throw new PublicTaskInputError("invalid");
  const payload = await request(`/api/task-inputs/${inputId}`, "GET");
  try { const version = parseTaskInputVersion(payload); if (version.id !== inputId) throw new TaskInputContractError(); return version; } catch { throw new PublicTaskInputError("invalid_response"); }
}
export async function previewTaskInputPrune(inputId: string) {
  if (!INPUT.test(inputId)) throw new PublicTaskInputError("invalid");
  const payload = await request(`/api/task-inputs/${inputId}/prune/preview`, "POST", {});
  try { return taskInputPrunePreview(payload, inputId); } catch { throw new PublicTaskInputError("invalid_response"); }
}
export async function confirmTaskInputPrune(inputId: string, confirmationId: string) {
  if (!INPUT.test(inputId) || !/^[0-9a-f]{64}$/u.test(confirmationId)) throw new PublicTaskInputError("invalid");
  const payload = await request(`/api/task-inputs/${inputId}/prune`, "POST", { confirmation_id: confirmationId, confirmed: true });
  try { return taskInputPruned(payload); } catch { throw new PublicTaskInputError("invalid_response"); }
}
