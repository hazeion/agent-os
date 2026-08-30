import { fetchBridgeConversationPlanningContext, updateBridgeConversationPlanningContext } from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, planningRequestAllowed } from "./planning-overview-route.ts";
import type { PublicConversationPlanningContext, PublicConversationPlanningMutation } from "./public-planning.ts";

const CONVERSATION_ID = /^conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u;
const PROJECT_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const TASK_ID = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
type Params = { params: Promise<{ conversationId: string }> };
type ReadContext = (id: string) => Promise<PublicConversationPlanningContext>;
type UpdateContext = (id: string, revision: number, projectId: string | null, taskId: string | null) => Promise<PublicConversationPlanningMutation>;

async function readBody(request: Request): Promise<{ expectedRevision: number; projectId: string | null; taskId: string | null } | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const declared = request.headers.get("content-length"); if (declared && (!/^\d{1,4}$/u.test(declared) || Number(declared) > 768)) return null;
  const reader = request.body.getReader(); const parts: Uint8Array[] = []; let total = 0; let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => { timer = setTimeout(() => reject(new Error("timeout")), 2_000); });
  try { for (;;) { const next = await Promise.race([reader.read(), deadline]); if (next.done) break; total += next.value.byteLength; if (total > 768) { void reader.cancel().catch(() => undefined); return null; } parts.push(next.value); } } catch { void reader.cancel().catch(() => undefined); return null; } finally { if (timer) clearTimeout(timer); reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
  let value: unknown; try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); } catch { return null; }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null; const body = value as Record<string, unknown>;
  if (Object.keys(body).sort().join(",") !== "expected_revision,project_id,task_id" || !Number.isSafeInteger(body.expected_revision) || (body.expected_revision as number) < 1) return null;
  if (body.project_id !== null && (typeof body.project_id !== "string" || !PROJECT_ID.test(body.project_id)) || body.task_id !== null && (typeof body.task_id !== "string" || !TASK_ID.test(body.task_id) || body.project_id === null)) return null;
  return { expectedRevision: body.expected_revision as number, projectId: body.project_id as string | null, taskId: body.task_id as string | null };
}

export function createConversationPlanningContextGetHandler({ gatewayPort = process.env.PORT, readContext = fetchBridgeConversationPlanningContext }: Readonly<{ gatewayPort?: string; readContext?: ReadContext }> = {}) {
  return async function getConversationPlanningContext(request: Request, context: Params) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    if (new URL(request.url).search) return planningFixed("invalid", 400); const { conversationId } = await context.params;
    if (!CONVERSATION_ID.test(conversationId)) return planningFixed("invalid", 400);
    try { return Response.json(await readContext(conversationId), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
  };
}

export function createConversationPlanningContextPostHandler({ gatewayPort = process.env.PORT, updateContext = updateBridgeConversationPlanningContext }: Readonly<{ gatewayPort?: string; updateContext?: UpdateContext }> = {}) {
  return async function postConversationPlanningContext(request: Request, context: Params) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    if (new URL(request.url).search) return planningFixed("invalid", 400); const { conversationId } = await context.params;
    if (!CONVERSATION_ID.test(conversationId)) return planningFixed("invalid", 400); const body = await readBody(request); if (!body) return planningFixed("invalid", 400);
    try { return Response.json(await updateContext(conversationId, body.expectedRevision, body.projectId, body.taskId), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
  };
}
