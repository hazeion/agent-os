import { fetchBridgePlanningTask } from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";
import type { PublicPlanningTaskResult } from "./public-planning.ts";

type ReadTask = (taskId: string) => Promise<PublicPlanningTaskResult>;

export function createPlanningTaskHandler({ fetchTask = fetchBridgePlanningTask, gatewayPort = process.env.PORT }: Readonly<{ fetchTask?: ReadTask; gatewayPort?: string }> = {}) {
  return withPlanningGatewayRoute<string | null>("GET", "/api/agent-console/planning-task", gatewayPort, {
    validator: { validate(request) {
    const entries = [...new URL(request.url).searchParams.entries()];
    return entries.length === 1 && entries[0]![0] === "task_id" && /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u.test(entries[0]![1]) ? entries[0]![1] : null;
    } },
    handler: async ({ value }) => { if (!value) return planningFixed("invalid", 400); try { return Response.json(await fetchTask(value), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); } },
  });
}
