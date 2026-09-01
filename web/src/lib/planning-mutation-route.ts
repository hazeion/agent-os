import { moveBridgePlanningTask, updateBridgePlanningProject, updateBridgePlanningTask } from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, planningRequestAllowed } from "./planning-overview-route.ts";

type Params = { params: Promise<{ kind: string; id: string; action: string }> };
const PROJECT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const EDIT_FIELDS = new Set(["title", "description", "priority", "due_date", "tags", "workflow_stage", "deferred", "planned_for_today", "manual_rank", "estimated_minutes", "scheduled_block", "recurrence", "subtasks", "depends_on", "note_links", "assigned_agent_id"]);

async function body(request: Request): Promise<Record<string, unknown> | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d{1,6}$/u.test(declared) || Number(declared) > 65_536)) return null;
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let total = 0; let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => { timer = setTimeout(() => reject(new Error("timeout")), 2_000); });
  try { for (;;) { const next = await Promise.race([reader.read(), deadline]); if (next.done) break; total += next.value.byteLength; if (total > 65_536) { void reader.cancel().catch(() => undefined); return null; } chunks.push(next.value); } } catch { void reader.cancel().catch(() => undefined); return null; } finally { if (timer) clearTimeout(timer); reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null; } catch { return null; }
}

function positive(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 1; }
function exact(value: Record<string, unknown>, names: string[]): boolean { return Object.keys(value).sort().join(",") === [...names].sort().join(","); }

export function createPlanningMutationHandler({
  updateProject = updateBridgePlanningProject,
  updateTask = updateBridgePlanningTask,
  moveTask = moveBridgePlanningTask,
  gatewayPort = process.env.PORT,
} = {}) {
  return async function postPlanningMutation(request: Request, context: Params) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    if (new URL(request.url).search) return planningFixed("invalid", 400);
    const { kind, id, action } = await context.params;
    const value = await body(request);
    if (!value) return planningFixed("invalid", 400);
    try {
      if (kind === "projects" && PROJECT.test(id) && ["rename", "archive", "restore"].includes(action) && exact(value, ["expected_revision", "action", "name"]) && typeof value.action === "string" && value.action === action && positive(value.expected_revision) && (action === "rename" ? typeof value.name === "string" : value.name === null)) {
        return Response.json(await updateProject(id, value.expected_revision, action as "rename" | "archive" | "restore", value.name as string | null), { headers: PLANNING_HEADERS });
      }
      if (kind === "tasks" && TASK.test(id) && action === "edit" && exact(value, ["expected_revision", "changes"]) && positive(value.expected_revision) && value.changes && typeof value.changes === "object" && !Array.isArray(value.changes) && Object.keys(value.changes as Record<string, unknown>).length > 0 && Object.keys(value.changes as Record<string, unknown>).every((field) => EDIT_FIELDS.has(field))) {
        return Response.json(await updateTask(id, value.expected_revision, value.changes as Record<string, unknown>), { headers: PLANNING_HEADERS });
      }
      if (kind === "tasks" && TASK.test(id) && action === "move" && exact(value, ["expected_task_revision", "project_id", "expected_project_revision"]) && positive(value.expected_task_revision) && typeof value.project_id === "string" && PROJECT.test(value.project_id) && positive(value.expected_project_revision)) {
        return Response.json(await moveTask(id, value.expected_task_revision, value.project_id, value.expected_project_revision), { headers: PLANNING_HEADERS });
      }
    } catch (error) { return planningFailure(error); }
    return planningFixed("invalid", 400);
  };
}
