import { failure, PublicPlanningError, request } from "./public-planning.ts";
import {
  parsePlanningTaskDelegationCurrent,
  type PublicPlanningTaskDelegationCurrent,
} from "./public-planning-task-delegation-actions.ts";

const TASK_ID = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;

/** Safe current delegation state retained for callers that only need a read. */
export type PublicPlanningTaskDelegation = PublicPlanningTaskDelegationCurrent;
export const parsePlanningTaskDelegation = parsePlanningTaskDelegationCurrent;

export async function readPlanningTaskDelegation(
  taskId: string,
): Promise<PublicPlanningTaskDelegation> {
  if (!TASK_ID.test(taskId)) throw new PublicPlanningError("invalid");
  const { response, payload } = await request(
    `/api/agent-console/planning-task-delegation?${new URLSearchParams({ task_id: taskId }).toString()}`,
  );
  if (response.status === 200) {
    return parsePlanningTaskDelegationCurrent(payload, taskId);
  }
  failure(payload, response);
}
