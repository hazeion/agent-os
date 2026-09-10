import { fetchBridgePlanningTasks } from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";
import type { PublicPlanningTaskPage } from "./public-planning.ts";

type ReadTasks = (projectId: string, cursor: string | null) => Promise<PublicPlanningTaskPage>;
export function createPlanningTasksHandler({ fetchTasks = fetchBridgePlanningTasks, gatewayPort = process.env.PORT }: Readonly<{ fetchTasks?: ReadTasks; gatewayPort?: string }> = {}) {
  return withPlanningGatewayRoute<readonly [string, string | null] | null>("GET", "/api/agent-console/planning-tasks", gatewayPort, {
    validator: { validate(request) {
    const entries = [...new URL(request.url).searchParams.entries()];
    if (new Set(entries.map(([key]) => key)).size !== entries.length || entries.some(([key]) => key !== "project_id" && key !== "cursor")) return null;
    const parameters = new URLSearchParams(entries); const projectId = parameters.get("project_id"); const cursor = parameters.get("cursor");
    return projectId && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u.test(projectId) && (cursor === null || /^[A-Za-z0-9_-]{1,512}$/u.test(cursor)) ? [projectId, cursor] as const : null;
    } },
    handler: async ({ value }) => { if (!value) return planningFixed("invalid", 400); try { return Response.json(await fetchTasks(...value), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); } },
  });
}
