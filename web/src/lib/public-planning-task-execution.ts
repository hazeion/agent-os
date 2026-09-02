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
  validTask,
  type PublicPlanningExecutionAttempt,
  type PublicPlanningExecutionTask,
  type PublicPlanningRunOncePreview,
  type PublicPlanningTaskExecution,
  type PublicPlanningTaskExecutionMutation,
} from "./public-planning.ts";

const TASK_ID = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;

function safeIdentifier(value: unknown, maximum: number): value is string {
  return typeof value === "string" && new RegExp(`^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,${maximum - 1}}$`, "u").test(value);
}

function validExecutionTask(value: unknown): value is PublicPlanningExecutionTask {
  if (!record(value)) return false;
  const { assigned_agent_id: agentId, ...task } = value;
  return validTask(task) && (agentId === null || safeIdentifier(agentId, 128));
}

function validExecutionAttempt(value: unknown): value is PublicPlanningExecutionAttempt {
  return record(value) && keys(value, "agent_id,completed_at,completion_reason,created_at,dispatch_state,partial,review_action,review_note,review_task_revision,run_id,runtime_type,state,status,task_revision,terminal_finalized,updated_at")
    && typeof value.run_id === "string" && /^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/u.test(value.run_id)
    && Number.isSafeInteger(value.task_revision) && (value.task_revision as number) >= 1
    && safeIdentifier(value.agent_id, 128)
    && ["dispatched", "review_ready", "completion_blocked", "accepted", "changes_requested"].includes(String(value.state))
    && (value.review_task_revision === null || Number.isSafeInteger(value.review_task_revision) && (value.review_task_revision as number) >= 1)
    && (value.completion_reason === null || value.completion_reason === "task_changed")
    && typeof value.runtime_type === "string" && /^[a-z][a-z0-9_-]{0,31}$/u.test(value.runtime_type)
    && typeof value.status === "string" && ["reserved", "queued", "submitting", "starting", "running", "cancelling", "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown", "completed", "failed", "cancelled", "stopped", "interrupted"].includes(value.status)
    && typeof value.dispatch_state === "string" && ["legacy", "reserved", "submitting", "accepted", "rejected", "unknown"].includes(value.dispatch_state)
    && typeof value.partial === "boolean" && typeof value.terminal_finalized === "boolean" && timestamp(value.created_at) && timestamp(value.updated_at)
    && (value.completed_at === null || timestamp(value.completed_at))
    && (value.review_action === null || value.review_action === "accept" || value.review_action === "request_changes")
    && (value.review_note === null || text(value.review_note, 2_000));
}

function validTaskExecution(value: unknown): value is PublicPlanningTaskExecution["execution"] {
  if (!record(value) || !keys(value, "attempt_count,attempts,available,reason,review") || typeof value.available !== "boolean" || value.reason !== null && value.reason !== "unavailable" || !Array.isArray(value.attempts) || value.attempts.length > 8 || !value.attempts.every(validExecutionAttempt) || new Set(value.attempts.map((attempt) => attempt.run_id)).size !== value.attempts.length || !Number.isSafeInteger(value.attempt_count) || value.attempt_count !== value.attempts.length || !record(value.review) || !keys(value.review, "available,run_id")) return false;
  const review = value.review;
  return typeof review.available === "boolean"
    && (review.run_id === null || typeof review.run_id === "string" && /^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/u.test(review.run_id))
    && (review.available ? review.run_id !== null && value.attempts.some((attempt) => attempt.run_id === review.run_id && attempt.state === "review_ready") : review.run_id === null);
}

export function parsePlanningTaskExecution(value: unknown, taskId?: string): PublicPlanningTaskExecution {
  if (!record(value) || !keys(value, "execution,runtime,schema_version,service,status,task") || !validEnvelope(value) || !validExecutionTask(value.task) || !validTaskExecution(value.execution) || taskId !== undefined && value.task.id !== taskId) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskExecution;
}

export function parsePlanningRunOncePreview(value: unknown, taskId?: string, expectedRevision?: number): PublicPlanningRunOncePreview {
  if (!record(value) || !keys(value, "action,confirmation_id,requires_confirmation,runtime,schema_version,service,status,task") || !validEnvelope(value) || value.action !== "run_once" || !validExecutionTask(value.task) || taskId !== undefined && value.task.id !== taskId || expectedRevision !== undefined && value.task.revision !== expectedRevision || value.requires_confirmation !== true || typeof value.confirmation_id !== "string" || !/^[0-9a-f]{64}$/u.test(value.confirmation_id)) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningRunOncePreview;
}

export function parsePlanningTaskExecutionMutation(value: unknown, taskId?: string): PublicPlanningTaskExecutionMutation {
  if (!record(value) || !keys(value, "action,duplicate,execution,runtime,schema_version,service,status,task") || !validEnvelope(value) || !["run_once", "accept", "request_changes"].includes(String(value.action)) || typeof value.duplicate !== "boolean" || !validExecutionTask(value.task) || !validTaskExecution(value.execution) || taskId !== undefined && value.task.id !== taskId) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskExecutionMutation;
}

function validIdempotencyKey(value: unknown): value is string {
  if (typeof value !== "string" || value.includes("\x00")) return false;
  try {
    const bytes = new TextEncoder().encode(value);
    return bytes.length >= 16 && bytes.length <= 256
      && new TextDecoder("utf-8", { fatal: true }).decode(bytes) === value;
  } catch { return false; }
}

export async function readPlanningTaskExecution(taskId: string): Promise<PublicPlanningTaskExecution> {
  if (!TASK_ID.test(taskId)) throw new PublicPlanningError("invalid");
  const parameters = new URLSearchParams({ task_id: taskId });
  const { response, payload } = await request(`/api/agent-console/planning-task-execution?${parameters.toString()}`);
  if (response.status === 200) return parsePlanningTaskExecution(payload, taskId);
  failure(payload, response);
}

export async function previewPlanningTaskRunOnce(taskId: string, expectedRevision: number): Promise<PublicPlanningRunOncePreview> {
  if (!TASK_ID.test(taskId) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1) throw new PublicPlanningError("invalid");
  const { response, payload } = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/execution/run-once/preview`, { body: JSON.stringify({ expected_revision: expectedRevision }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS);
  if (response.status === 200) return parsePlanningRunOncePreview(payload, taskId, expectedRevision);
  failure(payload, response);
}

export async function confirmPlanningTaskRunOnce(taskId: string, expectedRevision: number, idempotencyKey: string, confirmationId: string): Promise<PublicPlanningTaskExecutionMutation> {
  if (!TASK_ID.test(taskId) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || !validIdempotencyKey(idempotencyKey) || !/^[0-9a-f]{64}$/u.test(confirmationId)) throw new PublicPlanningError("invalid");
  const { response, payload } = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/execution/run-once`, { body: JSON.stringify({ confirmation_id: confirmationId, expected_revision: expectedRevision, idempotency_key: idempotencyKey }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS);
  if (response.status === 200 || response.status === 202) return parsePlanningTaskExecutionMutation(payload, taskId);
  failure(payload, response);
}

export async function reviewPlanningTaskExecution(taskId: string, expectedRevision: number, action: "accept" | "request_changes", note: string | null, idempotencyKey: string): Promise<PublicPlanningTaskExecutionMutation> {
  if (!TASK_ID.test(taskId) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || !["accept", "request_changes"].includes(action) || !validIdempotencyKey(idempotencyKey) || action === "accept" && note !== null || action === "request_changes" && !text(note, 2_000)) throw new PublicPlanningError("invalid");
  const { response, payload } = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/execution/review`, { body: JSON.stringify(action === "accept" ? { action, expected_revision: expectedRevision, idempotency_key: idempotencyKey } : { action, expected_revision: expectedRevision, idempotency_key: idempotencyKey, note }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS);
  if (response.status === 200) return parsePlanningTaskExecutionMutation(payload, taskId);
  failure(payload, response);
}
