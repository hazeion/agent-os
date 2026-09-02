import {
  failure,
  keys,
  PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS,
  PublicPlanningError,
  record,
  request,
  text,
  timestamp,
  validEnvelope,
  type ServiceEnvelope,
} from "./public-planning.ts";

const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const TARGET = /^[A-Za-z0-9][A-Za-z0-9_-]*$/u;
const PACK = /^pack_[0-9a-f]{16}$/u;
const DELEGATE_CONFIRMATION = /^task_delegate_[0-9a-f]{24}$/u;
const ACTION_CONFIRMATION = /^delegation_action_[0-9a-f]{24}$/u;
const ACTIONS = ["delegate", "accept", "reply", "retry", "stop", "request_revision", "mark_blocked"] as const;
const NOTE_ACTIONS = ["reply", "request_revision", "mark_blocked"] as const;
const STATES = ["queued", "running", "needs_input", "blocked", "ready_for_review", "completed", "failed", "cancelled"] as const;
const SYNCS = ["pending", "synced", "stale", "error"] as const;
const REVIEWS = ["pending", "accepted", "revision_requested", "blocked"] as const;
const OUTCOMES = ["completed", "blocked", "failed", "cancelled", "timed_out", "reclaimed"] as const;

export type DelegationAction = typeof ACTIONS[number];
export type DelegationTask = { id: string; revision: number };
export type DelegationState =
  | { available: false; reason: "not_delegated" | "unavailable" }
  | {
    available: true;
    state: typeof STATES[number]; sync_state: typeof SYNCS[number]; review_state: typeof REVIEWS[number];
    summary: string | null; latest_question: string | null; last_outcome: typeof OUTCOMES[number] | null;
    attempts: number; updated_at: string; last_synced_at: string | null; artifact_count: number;
  };
export type PublicPlanningTaskDelegationCurrent = ServiceEnvelope & { task: DelegationTask; delegation: DelegationState };
export type PublicPlanningTaskDelegationOptions = PublicPlanningTaskDelegationCurrent & {
  options: { available: false } | { available: true; profiles: Array<{ id: string; name: string }>; boards: Array<{ id: string; name: string }>; workspaces: ["scratch", "worktree"] };
};
export type PublicPlanningTaskDelegationPreview = PublicPlanningTaskDelegationCurrent & {
  action: DelegationAction; requires_confirmation: true; confirmation_id: string; effects: string[];
  target?: { profile_id: string; board_id: string; workspace: "scratch" | "worktree" };
};
export type PublicPlanningTaskDelegationMutation = PublicPlanningTaskDelegationCurrent & { action: DelegationAction; duplicate: boolean };
export type PublicPlanningTaskDelegationRefresh = PublicPlanningTaskDelegationCurrent & { action: "refresh" };
export type PublicPlanningTaskDelegationRecovery = PublicPlanningTaskDelegationMutation & { recovered: boolean };

function positive(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 1; }
function identifier(value: unknown, maximum: number): value is string { return typeof value === "string" && value.length <= maximum && TARGET.test(value); }
function idempotency(value: unknown): value is string {
  if (typeof value !== "string" || value.includes("\x00")) return false;
  try { const bytes = new TextEncoder().encode(value); return bytes.length >= 16 && bytes.length <= 256 && new TextDecoder("utf-8", { fatal: true }).decode(bytes) === value; } catch { return false; }
}
function input(value: unknown, maximum: number): value is string { return typeof value === "string" && [...value].length <= maximum && !/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/u.test(value); }
function validTask(value: unknown, taskId?: string): value is DelegationTask { return record(value) && keys(value, "id,revision") && typeof value.id === "string" && TASK.test(value.id) && (taskId === undefined || value.id === taskId) && positive(value.revision); }
function validState(value: unknown): value is DelegationState {
  if (!record(value) || typeof value.available !== "boolean") return false;
  if (!value.available) return keys(value, "available,reason") && (value.reason === "not_delegated" || value.reason === "unavailable");
  return keys(value, "artifact_count,attempts,available,last_outcome,last_synced_at,latest_question,review_state,state,summary,sync_state,updated_at")
    && STATES.includes(value.state as typeof STATES[number]) && SYNCS.includes(value.sync_state as typeof SYNCS[number]) && REVIEWS.includes(value.review_state as typeof REVIEWS[number])
    && (value.summary === null || text(value.summary, 4_000)) && (value.latest_question === null || text(value.latest_question, 2_000))
    && (value.last_outcome === null || OUTCOMES.includes(value.last_outcome as typeof OUTCOMES[number]))
    && Number.isSafeInteger(value.attempts) && (value.attempts as number) >= 0 && (value.attempts as number) <= 1_000_000
    && Number.isSafeInteger(value.artifact_count) && (value.artifact_count as number) >= 0 && (value.artifact_count as number) <= 1_000_000
    && timestamp(value.updated_at) && (value.last_synced_at === null || timestamp(value.last_synced_at));
}
function validCurrent(value: unknown, taskId?: string): value is PublicPlanningTaskDelegationCurrent { return record(value) && keys(value, "delegation,runtime,schema_version,service,status,task") && validEnvelope(value) && validTask(value.task, taskId) && validState(value.delegation); }
function validAction(value: unknown): value is DelegationAction { return typeof value === "string" && ACTIONS.includes(value as DelegationAction); }
function validConfirmation(value: unknown, action: DelegationAction): value is string { return typeof value === "string" && (action === "delegate" ? DELEGATE_CONFIRMATION : ACTION_CONFIRMATION).test(value); }

export function parsePlanningTaskDelegationCurrent(value: unknown, taskId?: string): PublicPlanningTaskDelegationCurrent {
  if (!validCurrent(value, taskId)) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskDelegationCurrent;
}
export function parsePlanningTaskDelegationOptions(value: unknown, taskId?: string): PublicPlanningTaskDelegationOptions {
  if (!record(value) || !keys(value, "delegation,options,runtime,schema_version,service,status,task")) throw new PublicPlanningError("response_invalid");
  const { options: rawOptions, ...current } = value;
  if (!validCurrent(current, taskId) || !record(rawOptions) || typeof rawOptions.available !== "boolean") throw new PublicPlanningError("response_invalid");
  const options = rawOptions;
  if (!options.available && keys(options, "available")) return structuredClone(value) as PublicPlanningTaskDelegationOptions;
  if (!options.available || !keys(options, "available,boards,profiles,workspaces") || !Array.isArray(options.profiles) || !Array.isArray(options.boards) || !Array.isArray(options.workspaces) || options.workspaces.length !== 2 || options.workspaces[0] !== "scratch" || options.workspaces[1] !== "worktree" || ![options.profiles, options.boards].every((items, index) => items.length >= 1 && items.length <= 128 && items.every((item) => record(item) && keys(item, "id,name") && identifier(item.id, index === 0 ? 80 : 64) && text(item.name, 160)) && new Set(items.map((item) => String((item as Record<string, unknown>).id))).size === items.length)) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskDelegationOptions;
}
export function parsePlanningTaskDelegationPreview(value: unknown, taskId?: string): PublicPlanningTaskDelegationPreview {
  if (!record(value)) throw new PublicPlanningError("response_invalid");
  const { action, confirmation_id, effects, requires_confirmation, target, ...current } = value;
  if (!validCurrent(current, taskId) || !validAction(action) || requires_confirmation !== true || !validConfirmation(confirmation_id, action) || !Array.isArray(effects) || effects.length > (action === "delegate" ? 8 : 4) || !effects.every((item: unknown) => text(item, 500))) throw new PublicPlanningError("response_invalid");
  const expected = action === "delegate" ? "action,confirmation_id,delegation,effects,requires_confirmation,runtime,schema_version,service,status,target,task" : "action,confirmation_id,delegation,effects,requires_confirmation,runtime,schema_version,service,status,task";
  if (!keys(value, expected)) throw new PublicPlanningError("response_invalid");
  if (action === "delegate" && (!record(target) || !keys(target, "board_id,profile_id,workspace") || !identifier(target.profile_id, 80) || !identifier(target.board_id, 64) || (target.workspace !== "scratch" && target.workspace !== "worktree"))) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskDelegationPreview;
}
export function parsePlanningTaskDelegationMutation(value: unknown, taskId?: string): PublicPlanningTaskDelegationMutation {
  if (!record(value) || !keys(value, "action,delegation,duplicate,runtime,schema_version,service,status,task")) throw new PublicPlanningError("response_invalid");
  const { action, duplicate, ...current } = value;
  if (!validCurrent(current, taskId) || !validAction(action) || typeof duplicate !== "boolean") throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskDelegationMutation;
}
export function parsePlanningTaskDelegationRefresh(value: unknown, taskId?: string): PublicPlanningTaskDelegationRefresh {
  if (!record(value) || !keys(value, "action,delegation,runtime,schema_version,service,status,task")) throw new PublicPlanningError("response_invalid");
  const { action, ...current } = value;
  if (!validCurrent(current, taskId) || action !== "refresh") throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskDelegationRefresh;
}
export function parsePlanningTaskDelegationRecovery(value: unknown, taskId?: string): PublicPlanningTaskDelegationRecovery {
  if (!record(value) || !keys(value, "action,delegation,duplicate,recovered,runtime,schema_version,service,status,task")) throw new PublicPlanningError("response_invalid");
  const { action, duplicate, recovered, ...current } = value;
  if (!validCurrent(current, taskId) || !validAction(action) || typeof duplicate !== "boolean" || typeof recovered !== "boolean" || duplicate === recovered) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskDelegationRecovery;
}

export async function readPlanningTaskDelegationOptions(taskId: string): Promise<PublicPlanningTaskDelegationOptions> { if (!TASK.test(taskId)) throw new PublicPlanningError("invalid"); const { response, payload } = await request(`/api/agent-console/planning-task-delegation/options?${new URLSearchParams({ task_id: taskId })}`); if (response.status === 200) return parsePlanningTaskDelegationOptions(payload, taskId); failure(payload, response); }
export async function previewPlanningTaskDelegation(taskId: string, expectedRevision: number, profileId: string, boardId: string, workspace: "scratch" | "worktree", instructions: string, contextPackId: string): Promise<PublicPlanningTaskDelegationPreview> { if (!TASK.test(taskId) || !positive(expectedRevision) || !identifier(profileId, 80) || !identifier(boardId, 64) || !["scratch", "worktree"].includes(workspace) || !input(instructions, 8_000) || !(contextPackId === "" || PACK.test(contextPackId))) throw new PublicPlanningError("invalid"); const { response, payload } = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/delegation/preview`, { body: JSON.stringify({ expected_revision: expectedRevision, profile_id: profileId, board_id: boardId, workspace, instructions, context_pack_id: contextPackId }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS); if (response.status === 200) return parsePlanningTaskDelegationPreview(payload, taskId); failure(payload, response); }
export async function confirmPlanningTaskDelegation(taskId: string, expectedRevision: number, profileId: string, boardId: string, workspace: "scratch" | "worktree", instructions: string, contextPackId: string, confirmationId: string, idempotencyKey: string): Promise<PublicPlanningTaskDelegationMutation> { if (!TASK.test(taskId) || !positive(expectedRevision) || !identifier(profileId, 80) || !identifier(boardId, 64) || !["scratch", "worktree"].includes(workspace) || !input(instructions, 8_000) || !(contextPackId === "" || PACK.test(contextPackId)) || !DELEGATE_CONFIRMATION.test(confirmationId) || !idempotency(idempotencyKey)) throw new PublicPlanningError("invalid"); const { response, payload } = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/delegation/delegate`, { body: JSON.stringify({ expected_revision: expectedRevision, profile_id: profileId, board_id: boardId, workspace, instructions, context_pack_id: contextPackId, confirmation_id: confirmationId, idempotency_key: idempotencyKey }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS); if (response.status === 200 || response.status === 201) return parsePlanningTaskDelegationMutation(payload, taskId); failure(payload, response); }
export async function previewPlanningTaskDelegationAction(taskId: string, expectedRevision: number, action: Exclude<DelegationAction, "delegate">, note: string | null): Promise<PublicPlanningTaskDelegationPreview> { if (!TASK.test(taskId) || !positive(expectedRevision) || !ACTIONS.includes(action) || NOTE_ACTIONS.includes(action as typeof NOTE_ACTIONS[number]) !== (note !== null) || note !== null && (!input(note, 8_000) || !note.trim())) throw new PublicPlanningError("invalid"); const body = note === null ? { expected_revision: expectedRevision, action } : { expected_revision: expectedRevision, action, note }; const { response, payload } = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/delegation/action/preview`, { body: JSON.stringify(body), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS); if (response.status === 200) return parsePlanningTaskDelegationPreview(payload, taskId); failure(payload, response); }
export async function confirmPlanningTaskDelegationAction(taskId: string, expectedRevision: number, action: Exclude<DelegationAction, "delegate">, note: string | null, confirmationId: string, idempotencyKey: string): Promise<PublicPlanningTaskDelegationMutation> { if (!TASK.test(taskId) || !positive(expectedRevision) || !ACTIONS.includes(action) || NOTE_ACTIONS.includes(action as typeof NOTE_ACTIONS[number]) !== (note !== null) || note !== null && (!input(note, 8_000) || !note.trim()) || !ACTION_CONFIRMATION.test(confirmationId) || !idempotency(idempotencyKey)) throw new PublicPlanningError("invalid"); const body = note === null ? { expected_revision: expectedRevision, action, confirmation_id: confirmationId, idempotency_key: idempotencyKey } : { expected_revision: expectedRevision, action, note, confirmation_id: confirmationId, idempotency_key: idempotencyKey }; const { response, payload } = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/delegation/action`, { body: JSON.stringify(body), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS); if (response.status === 200) return parsePlanningTaskDelegationMutation(payload, taskId); failure(payload, response); }
export async function refreshPlanningTaskDelegation(taskId: string, expectedRevision: number): Promise<PublicPlanningTaskDelegationRefresh> { if (!TASK.test(taskId) || !positive(expectedRevision)) throw new PublicPlanningError("invalid"); const { response, payload } = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/delegation/refresh`, { body: JSON.stringify({ expected_revision: expectedRevision }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS); if (response.status === 200) return parsePlanningTaskDelegationRefresh(payload, taskId); failure(payload, response); }
export async function recoverPlanningTaskDelegation(taskId: string, confirmationId: string, idempotencyKey: string): Promise<PublicPlanningTaskDelegationRecovery> { if (!TASK.test(taskId) || !/^(?:task_delegate|delegation_action)_[0-9a-f]{24}$/u.test(confirmationId) || !idempotency(idempotencyKey)) throw new PublicPlanningError("invalid"); const { response, payload } = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/delegation/recover`, { body: JSON.stringify({ confirmation_id: confirmationId, idempotency_key: idempotencyKey }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS); if (response.status === 200) return parsePlanningTaskDelegationRecovery(payload, taskId); failure(payload, response); }
