import { createBridgeProject, createBridgeProjectTask } from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, planningRequestAllowed } from "./planning-overview-route.ts";
import type { PublicPlanningProjectCreation, PublicPlanningTaskCreation } from "./public-planning.ts";

type CreateProject = (name: string) => Promise<PublicPlanningProjectCreation>;
type CreateTask = (projectId: string, title: string, assignedAgentId: string | null, dueDate: string | null) => Promise<PublicPlanningTaskCreation>;
type Params = { params: Promise<{ projectId: string }> };
function exactDate(value: string) { if (!/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false; const [year, month, day] = value.split("-").map(Number); const leap = year! % 4 === 0 && (year! % 100 !== 0 || year! % 400 === 0); const days = [0, 31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]; return year! >= 1 && month! >= 1 && month! <= 12 && day! >= 1 && day! <= days[month!]!; }

async function json(request: Request, maximum = 768): Promise<Record<string, unknown> | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const declared = request.headers.get("content-length"); if (declared && (!/^\d{1,4}$/u.test(declared) || Number(declared) > maximum)) return null;
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let total = 0; let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => { timer = setTimeout(() => reject(new Error("timeout")), 2_000); });
  try { for (;;) { const next = await Promise.race([reader.read(), deadline]); if (next.done) break; total += next.value.byteLength; if (total > maximum) { void reader.cancel().catch(() => undefined); return null; } chunks.push(next.value); } } catch { void reader.cancel().catch(() => undefined); return null; } finally { if (timer) clearTimeout(timer); reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { const parsed: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null; } catch { return null; }
}

export function createProjectHandler({ create = createBridgeProject, gatewayPort = process.env.PORT }: Readonly<{ create?: CreateProject; gatewayPort?: string }> = {}) {
  return async function postProject(request: Request) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    if (new URL(request.url).search) return planningFixed("invalid", 400); const body = await json(request);
    if (!body || Object.keys(body).join(",") !== "name" || typeof body.name !== "string" || !body.name || body.name.trim() !== body.name || [...body.name].length > 120 || /\p{C}/u.test(body.name)) return planningFixed("invalid", 400);
    try { return Response.json(await create(body.name), { headers: PLANNING_HEADERS, status: 201 }); } catch (error) { return planningFailure(error); }
  };
}

export function createProjectTaskHandler({ create = createBridgeProjectTask, gatewayPort = process.env.PORT }: Readonly<{ create?: CreateTask; gatewayPort?: string }> = {}) {
  return async function postProjectTask(request: Request, context: Params) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    if (new URL(request.url).search) return planningFixed("invalid", 400); const { projectId } = await context.params;
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u.test(projectId)) return planningFixed("invalid", 400); const body = await json(request);
    if (!body || Object.keys(body).sort().join(",") !== "assigned_agent_id,due_date,title" || typeof body.title !== "string" || !body.title || body.title.trim() !== body.title || [...body.title].length > 160 || /\p{C}/u.test(body.title) || body.assigned_agent_id !== null && (typeof body.assigned_agent_id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(body.assigned_agent_id)) || body.due_date !== null && (typeof body.due_date !== "string" || !exactDate(body.due_date))) return planningFixed("invalid", 400);
    try { return Response.json(await create(projectId, body.title, body.assigned_agent_id as string | null, body.due_date as string | null), { headers: PLANNING_HEADERS, status: 201 }); } catch (error) { return planningFailure(error); }
  };
}
