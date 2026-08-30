import { fetchBridgePlanningTask } from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, planningRequestAllowed } from "./planning-overview-route.ts";
import type { PublicPlanningTaskResult } from "./public-planning.ts";

type ReadTask = (taskId: string) => Promise<PublicPlanningTaskResult>;

export function createPlanningTaskHandler({ fetchTask = fetchBridgePlanningTask, gatewayPort = process.env.PORT }: Readonly<{ fetchTask?: ReadTask; gatewayPort?: string }> = {}) {
  return async function getPlanningTask(request: Request) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    const entries = [...new URL(request.url).searchParams.entries()];
    if (entries.length !== 1 || entries[0]![0] !== "task_id" || !/^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u.test(entries[0]![1])) return planningFixed("invalid", 400);
    try { return Response.json(await fetchTask(entries[0]![1]), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
  };
}
