import { publishBridgeTaskInputs, readBridgeTaskInputs, readBridgeRetiredTaskInputs, readBridgeRetiredTaskInput, previewBridgeTaskInputPrune, confirmBridgeTaskInputPrune, TaskInputBridgeError } from "./bridge-task-inputs.ts";
import { taskInputRequest } from "./task-input-contract.ts";
import { PLANNING_HEADERS, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";

type Name = "read" | "version" | "publish" | "retired-history" | "retired-version" | "prune-preview" | "prune-confirm";
type Params = { params: Promise<{ taskId?: string; inputId?: string }> };
const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const INPUT = /^task_input_[0-9a-f]{32}$/u;
async function jsonBody(request: Request): Promise<Record<string, unknown> | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > 128 * 1024)) return null;
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let length = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; length += next.value.byteLength; if (length > 128 * 1024) { await reader.cancel(); return null; } chunks.push(next.value); } } catch { await reader.cancel().catch(() => undefined); return null; } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null; } catch { return null; }
}
export function createTaskInputRoute(name: Name, { read = readBridgeTaskInputs, publish = publishBridgeTaskInputs, history = readBridgeRetiredTaskInputs, retired = readBridgeRetiredTaskInput, prunePreview = previewBridgeTaskInputPrune, pruneConfirm = confirmBridgeTaskInputPrune, gatewayPort = process.env.PORT }: Readonly<{ read?: typeof readBridgeTaskInputs; publish?: typeof publishBridgeTaskInputs; history?: typeof readBridgeRetiredTaskInputs; retired?: typeof readBridgeRetiredTaskInput; prunePreview?: typeof previewBridgeTaskInputPrune; pruneConfirm?: typeof confirmBridgeTaskInputPrune; gatewayPort?: string }> = {}) {
  const method = ["publish", "prune-preview", "prune-confirm"].includes(name) ? "POST" : "GET";
  const path = name === "version" ? "/api/planning/tasks/[taskId]/inputs/[inputId]" : name === "read" || name === "publish" ? "/api/planning/tasks/[taskId]/inputs" : name === "retired-history" ? "/api/task-inputs/history" : name === "retired-version" ? "/api/task-inputs/[inputId]" : name === "prune-preview" ? "/api/task-inputs/[inputId]/prune/preview" : "/api/task-inputs/[inputId]/prune";
  return withPlanningGatewayRoute<Record<string, unknown> | null, Params>(method, path, gatewayPort, {
    validator: { async validate(request, _context, route) {
      if (new URL(request.url).search) return null;
      const params = await route.params;
      if (["read", "version", "publish"].includes(name) && (!params.taskId || !TASK.test(params.taskId)) || ["version", "retired-version", "prune-preview", "prune-confirm"].includes(name) && (!params.inputId || !INPUT.test(params.inputId))) return null;
      if (method === "GET") return name === "retired-history" ? {} : name === "retired-version" ? { input_id: params.inputId } : { task_id: params.taskId, ...(name === "version" ? { input_id: params.inputId } : {}) };
      const value = await jsonBody(request);
      if (!value) return null;
      if (name === "prune-preview") return Object.keys(value).length === 0 ? { input_id: params.inputId } : null;
      if (name === "prune-confirm") return Object.keys(value).sort().join(",") === "confirmation_id,confirmed" && value.confirmed === true && typeof value.confirmation_id === "string" && /^[0-9a-f]{64}$/u.test(value.confirmation_id) ? { input_id: params.inputId, confirmation_id: value.confirmation_id } : null;
      if ("task_id" in value) return null;
      try { return taskInputRequest({ ...value, task_id: params.taskId }) as unknown as Record<string, unknown>; } catch { return null; }
    } },
    handler: async ({ value }) => {
      if (!value) return planningFixed("invalid", 400);
      try {
        const data = name === "publish" ? await publish(value) : name === "read" || name === "version" ? await read(String(value.task_id), name === "version" ? String(value.input_id) : undefined) : name === "retired-history" ? await history() : name === "retired-version" ? await retired(String(value.input_id)) : name === "prune-preview" ? await prunePreview(String(value.input_id)) : await pruneConfirm(String(value.input_id), String(value.confirmation_id));
        return Response.json(data, { headers: PLANNING_HEADERS });
      } catch (error) { return error instanceof TaskInputBridgeError ? planningFixed(error.code, error.status) : planningFixed("unavailable", 503); }
    },
  });
}
