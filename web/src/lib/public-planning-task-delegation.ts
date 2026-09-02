import {
  failure,
  PublicPlanningError,
  keys,
  record,
  request,
  timestamp,
  type ServiceEnvelope,
} from "./public-planning.ts";

const TASK_ID = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const STATES = ["queued", "running", "needs_input", "blocked", "ready_for_review", "completed", "failed", "cancelled"] as const;
const SYNC_STATES = ["pending", "synced", "stale", "error"] as const;
const REVIEW_STATES = ["pending", "accepted", "revision_requested", "blocked"] as const;
const OUTCOMES = ["completed", "blocked", "failed", "cancelled", "timed_out", "reclaimed"] as const;

export type PublicPlanningTaskDelegation = ServiceEnvelope & {
  task_id: string;
  delegation:
    | { available: false; reason: "not_delegated" }
    | {
      available: true;
      state: typeof STATES[number];
      sync_state: typeof SYNC_STATES[number];
      review_state: typeof REVIEW_STATES[number];
      summary: string | null;
      latest_question: string | null;
      last_outcome: typeof OUTCOMES[number] | null;
      attempts: number;
      updated_at: string;
      last_synced_at: string | null;
    };
};

function text(value: unknown, maximum: number): value is string {
  return typeof value === "string" && !!value && value.trim() === value && [...value].length <= maximum && !/\p{C}/u.test(value);
}

function validDelegation(value: unknown): value is PublicPlanningTaskDelegation["delegation"] {
  if (!record(value) || typeof value.available !== "boolean") return false;
  if (value.available === false) return keys(value, "available,reason") && value.reason === "not_delegated";
  return keys(value, "attempts,available,last_outcome,last_synced_at,latest_question,review_state,state,summary,sync_state,updated_at")
    && STATES.includes(value.state as typeof STATES[number])
    && SYNC_STATES.includes(value.sync_state as typeof SYNC_STATES[number])
    && REVIEW_STATES.includes(value.review_state as typeof REVIEW_STATES[number])
    && (value.summary === null || text(value.summary, 4_000))
    && (value.latest_question === null || text(value.latest_question, 2_000))
    && (value.last_outcome === null || OUTCOMES.includes(value.last_outcome as typeof OUTCOMES[number]))
    && Number.isSafeInteger(value.attempts) && (value.attempts as number) >= 0 && (value.attempts as number) <= 1_000
    && timestamp(value.updated_at)
    && (value.last_synced_at === null || timestamp(value.last_synced_at));
}

export function parsePlanningTaskDelegation(value: unknown, taskId?: string): PublicPlanningTaskDelegation {
  if (!record(value) || !keys(value, "delegation,runtime,schema_version,service,status,task_id")
    || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready"
    || typeof value.task_id !== "string" || !TASK_ID.test(value.task_id) || taskId !== undefined && value.task_id !== taskId || !validDelegation(value.delegation)) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskDelegation;
}

export async function readPlanningTaskDelegation(taskId: string): Promise<PublicPlanningTaskDelegation> {
  if (!TASK_ID.test(taskId)) throw new PublicPlanningError("invalid");
  const { response, payload } = await request(`/api/agent-console/planning-task-delegation?${new URLSearchParams({ task_id: taskId }).toString()}`);
  if (response.status === 200) return parsePlanningTaskDelegation(payload, taskId);
  failure(payload, response);
}
