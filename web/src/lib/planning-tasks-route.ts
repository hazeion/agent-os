import { fetchBridgePlanningTasks } from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, planningRequestAllowed } from "./planning-overview-route.ts";
import type { PublicPlanningTaskPage } from "./public-planning.ts";

type ReadTasks = (projectId: string, cursor: string | null) => Promise<PublicPlanningTaskPage>;
export function createPlanningTasksHandler({ fetchTasks = fetchBridgePlanningTasks, gatewayPort = process.env.PORT }: Readonly<{ fetchTasks?: ReadTasks; gatewayPort?: string }> = {}) {
  return async function getPlanningTasks(request: Request) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    const entries = [...new URL(request.url).searchParams.entries()];
    if (new Set(entries.map(([key]) => key)).size !== entries.length || entries.some(([key]) => key !== "project_id" && key !== "cursor")) return planningFixed("invalid", 400);
    const parameters = new URLSearchParams(entries); const projectId = parameters.get("project_id"); const cursor = parameters.get("cursor");
    if (!projectId || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u.test(projectId) || cursor !== null && !/^[A-Za-z0-9_-]{1,512}$/u.test(cursor)) return planningFixed("invalid", 400);
    try { return Response.json(await fetchTasks(projectId, cursor), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
  };
}
