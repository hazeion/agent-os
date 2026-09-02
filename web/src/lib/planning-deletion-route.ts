import { confirmBridgePlanningDeletion, previewBridgePlanningDeletion } from "./bridge-planning-deletion.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, planningRequestAllowed } from "./planning-overview-route.ts";
import type { PlanningDeletionTargetKind, PublicPlanningDeletionMutation, PublicPlanningDeletionPreview } from "./public-planning-deletion.ts";

type Params = { params: Promise<Record<string, string>> };
type Preview = (kind: PlanningDeletionTargetKind, id: string) => Promise<PublicPlanningDeletionPreview>;
type Confirm = (kind: PlanningDeletionTargetKind, id: string, confirmationId: string) => Promise<PublicPlanningDeletionMutation>;
const PROJECT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const CONFIRMATION = /^[0-9a-f]{64}$/u;

function validId(kind: PlanningDeletionTargetKind, value: unknown): value is string { return typeof value === "string" && (kind === "task" ? TASK : PROJECT).test(value); }
async function body(request: Request): Promise<Record<string, unknown> | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d{1,6}$/u.test(declared) || Number(declared) > 1_024)) return null;
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > 1_024) { await reader.cancel(); return null; } chunks.push(next.value); } } catch { await reader.cancel().catch(() => undefined); return null; } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null; } catch { return null; }
}
async function targetId(context: Params, kind: PlanningDeletionTargetKind): Promise<string | null> { const params = await context.params; const id = kind === "task" ? params.taskId : params.targetId; return validId(kind, id) ? id : null; }

export function createPlanningDeletionPreviewHandler(kind: PlanningDeletionTargetKind, { preview = previewBridgePlanningDeletion, gatewayPort = process.env.PORT }: Readonly<{ preview?: Preview; gatewayPort?: string }> = {}) {
  return async function previewDeletion(request: Request, context: Params) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    if (new URL(request.url).search) return planningFixed("invalid", 400);
    const id = await targetId(context, kind); const value = await body(request);
    if (!id || !value || Object.keys(value).length !== 0) return planningFixed("invalid", 400);
    try { return Response.json(await preview(kind, id), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
  };
}

export function createPlanningDeletionConfirmHandler(kind: PlanningDeletionTargetKind, { confirm = confirmBridgePlanningDeletion, gatewayPort = process.env.PORT }: Readonly<{ confirm?: Confirm; gatewayPort?: string }> = {}) {
  return async function confirmDeletion(request: Request, context: Params) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    if (new URL(request.url).search) return planningFixed("invalid", 400);
    const id = await targetId(context, kind); const value = await body(request);
    if (!id || !value || Object.keys(value).sort().join(",") !== "confirmation_id,confirmed" || value.confirmed !== true || typeof value.confirmation_id !== "string" || !CONFIRMATION.test(value.confirmation_id)) return planningFixed("invalid", 400);
    try { return Response.json(await confirm(kind, id, value.confirmation_id), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
  };
}
