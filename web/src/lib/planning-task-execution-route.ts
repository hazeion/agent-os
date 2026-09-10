import {
  confirmBridgePlanningTaskRunOnce,
  fetchBridgePlanningTaskExecution,
  refreshBridgePlanningTaskExecution,
  previewBridgePlanningTaskRunOnce,
  reviewBridgePlanningTaskExecution,
} from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";
import type { PublicPlanningRunOncePreview, PublicPlanningTaskExecution, PublicPlanningTaskExecutionMutation } from "./public-planning.ts";
import { validTaskExecutionRecovery, type TaskExecutionRecovery } from "./public-planning-task-execution.ts";

type Params = { params: Promise<{ taskId: string }> };
type RunOncePreview = (taskId: string, expectedRevision: number) => Promise<PublicPlanningRunOncePreview>;
type RunOnceConfirm = (taskId: string, expectedRevision: number, idempotencyKey: string, confirmationId: string) => Promise<PublicPlanningTaskExecutionMutation>;
type ReviewExecution = (taskId: string, expectedRevision: number, action: "accept" | "request_changes", note: string | null, idempotencyKey: string, recovery?: TaskExecutionRecovery) => Promise<PublicPlanningTaskExecutionMutation>;
type RefreshExecution = (taskId: string, expectedRevision: number) => Promise<PublicPlanningTaskExecution>;

const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const CONFIRMATION = /^[0-9a-f]{64}$/u;

function positive(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 1; }
function exact(value: Record<string, unknown>, names: string[]): boolean { return Object.keys(value).sort().join(",") === [...names].sort().join(","); }
function idempotencyKey(value: unknown): value is string {
  if (typeof value !== "string" || value.includes("\x00")) return false;
  try {
    const bytes = new TextEncoder().encode(value);
    return bytes.length >= 16 && bytes.length <= 256
      && new TextDecoder("utf-8", { fatal: true }).decode(bytes) === value;
  } catch { return false; }
}

async function body(request: Request): Promise<Record<string, unknown> | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d{1,6}$/u.test(declared) || Number(declared) > 4_096)) return null;
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > 4_096) { await reader.cancel(); return null; } chunks.push(next.value); } } catch { await reader.cancel().catch(() => undefined); return null; } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null; } catch { return null; }
}

async function taskId(context: Params): Promise<string | null> { const { taskId } = await context.params; return TASK.test(taskId) ? taskId : null; }

export function createPlanningTaskExecutionGetHandler({ readExecution = fetchBridgePlanningTaskExecution, gatewayPort = process.env.PORT }: Readonly<{ readExecution?: (taskId: string) => Promise<PublicPlanningTaskExecution>; gatewayPort?: string }> = {}) {
  return withPlanningGatewayRoute<string | null>("GET", "/api/agent-console/planning-task-execution", gatewayPort, {
    validator: { validate(request) {
    const entries = [...new URL(request.url).searchParams.entries()];
    return entries.length === 1 && entries[0]![0] === "task_id" && TASK.test(entries[0]![1]) ? entries[0]![1] : null;
    } },
    handler: async ({ value }) => { if (!value) return planningFixed("invalid", 400); try { return Response.json(await readExecution(value), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); } },
  });
}

export function createPlanningTaskExecutionRefreshHandler({ refresh = refreshBridgePlanningTaskExecution, gatewayPort = process.env.PORT }: Readonly<{ refresh?: RefreshExecution; gatewayPort?: string }> = {}) {
  return withPlanningGatewayRoute<readonly [string, number] | null, Params>("POST", "/api/planning/tasks/[taskId]/execution/refresh", gatewayPort, {
    validator: { async validate(request, _context, context) {
      if (new URL(request.url).search) return null;
      const id = await taskId(context); const value = await body(request);
      return id && value && exact(value, ["expected_revision"]) && positive(value.expected_revision) ? [id, value.expected_revision] as const : null;
    } },
    handler: async ({ value }) => { if (!value) return planningFixed("invalid", 400); try { return Response.json(await refresh(...value), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); } },
  });
}

export function createPlanningTaskRunOncePreviewHandler({ preview = previewBridgePlanningTaskRunOnce, gatewayPort = process.env.PORT }: Readonly<{ preview?: RunOncePreview; gatewayPort?: string }> = {}) {
  return withPlanningGatewayRoute<readonly [string, number] | null, Params>("POST", "/api/planning/tasks/[taskId]/execution/run-once/preview", gatewayPort, {
    validator: { async validate(request, _context, context) { if (new URL(request.url).search) return null; const id = await taskId(context); const value = await body(request); return id && value && exact(value, ["expected_revision"]) && positive(value.expected_revision) ? [id, value.expected_revision] as const : null; } },
    handler: async ({ value }) => { if (!value) return planningFixed("invalid", 400); try { return Response.json(await preview(...value), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); } },
  });
}

export function createPlanningTaskRunOnceConfirmHandler({ confirm = confirmBridgePlanningTaskRunOnce, gatewayPort = process.env.PORT }: Readonly<{ confirm?: RunOnceConfirm; gatewayPort?: string }> = {}) {
  return withPlanningGatewayRoute<readonly [string, number, string, string] | null, Params>("POST", "/api/planning/tasks/[taskId]/execution/run-once", gatewayPort, {
    validator: { async validate(request, _context, context) { if (new URL(request.url).search) return null; const id = await taskId(context); const value = await body(request); return id && value && exact(value, ["confirmation_id", "expected_revision", "idempotency_key"]) && positive(value.expected_revision) && idempotencyKey(value.idempotency_key) && typeof value.confirmation_id === "string" && CONFIRMATION.test(value.confirmation_id) ? [id, value.expected_revision, value.idempotency_key, value.confirmation_id] as const : null; } },
    handler: async ({ value }) => { if (!value) return planningFixed("invalid", 400); try { return Response.json(await confirm(...value), { headers: PLANNING_HEADERS, status: 202 }); } catch (error) { return planningFailure(error); } },
  });
}

export function createPlanningTaskExecutionReviewHandler({ review = (taskId, revision, action, note, key, recovery) => reviewBridgePlanningTaskExecution(taskId, revision, action, note, key, undefined, undefined, recovery), gatewayPort = process.env.PORT }: Readonly<{ review?: ReviewExecution; gatewayPort?: string }> = {}) {
  return withPlanningGatewayRoute<readonly [string, number, "accept" | "request_changes", string | null, string, TaskExecutionRecovery | undefined] | null, Params>("POST", "/api/planning/tasks/[taskId]/execution/review", gatewayPort, {
    validator: { async validate(request, _context, context) {
      if (new URL(request.url).search) return null; const id = await taskId(context); const value = await body(request);
      if (!id || !value || !positive(value.expected_revision) || !idempotencyKey(value.idempotency_key) || (value.action !== "accept" && value.action !== "request_changes")) return null;
      const recovery = "recovery_run_id" in value || "expected_run_revision" in value
        ? { recovery_run_id: value.recovery_run_id, expected_run_revision: value.expected_run_revision }
        : undefined;
      if (recovery !== undefined && (value.action !== "request_changes" || !validTaskExecutionRecovery(recovery))) return null;
      const changes = value.action === "accept"
      ? exact(value, ["action", "expected_revision", "idempotency_key"])
      : exact(value, ["action", "expected_revision", "idempotency_key", "note", ...(recovery ? ["recovery_run_id", "expected_run_revision"] : [])]) && typeof value.note === "string" && !!value.note && value.note.trim() === value.note && [...value.note].length <= 2_000 && !/\p{C}/u.test(value.note);
      return changes ? [id, value.expected_revision, value.action, value.action === "request_changes" ? value.note as string : null, value.idempotency_key, recovery as TaskExecutionRecovery | undefined] as const : null;
    } },
    handler: async ({ value }) => { if (!value) return planningFixed("invalid", 400); try { return Response.json(await review(...value), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); } },
  });
}
