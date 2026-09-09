import { fetchBridgePlanningTaskDelegation } from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";
import type { PublicPlanningTaskDelegation } from "./public-planning-task-delegation.ts";

const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;

export function createPlanningTaskDelegationGetHandler({ readDelegation = fetchBridgePlanningTaskDelegation, gatewayPort = process.env.PORT }: Readonly<{ readDelegation?: (taskId: string) => Promise<PublicPlanningTaskDelegation>; gatewayPort?: string }> = {}) {
  return withPlanningGatewayRoute<string | null>("GET", "/api/agent-console/planning-task-delegation", gatewayPort, {
    validator: { validate(request) {
    const entries = [...new URL(request.url).searchParams.entries()];
    return entries.length === 1 && entries[0]![0] === "task_id" && TASK.test(entries[0]![1]) ? entries[0]![1] : null;
    } },
    handler: async ({ value }) => { if (!value) return planningFixed("invalid", 400); try { return Response.json(await readDelegation(value), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); } },
  });
}
