import { fetchBridgePlanningDependencyPicker } from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";
import type { PublicPlanningDependencyPickerPage } from "./public-planning.ts";

type ReadPicker = (taskId: string, query: string, cursor: string | null) => Promise<PublicPlanningDependencyPickerPage>;

export function createPlanningDependencyPickerHandler({ fetchPicker = fetchBridgePlanningDependencyPicker, gatewayPort = process.env.PORT }: Readonly<{ fetchPicker?: ReadPicker; gatewayPort?: string }> = {}) {
  return withPlanningGatewayRoute<readonly [string, string, string | null] | null>("GET", "/api/agent-console/planning-dependency-picker", gatewayPort, {
    validator: { validate(request) {
    const entries = [...new URL(request.url).searchParams.entries()];
    if (!entries.length || new Set(entries.map(([key]) => key)).size !== entries.length || entries.some(([key]) => !["task_id", "q", "cursor"].includes(key))) return null;
    const parameters = new URLSearchParams(entries); const taskId = parameters.get("task_id"); const query = parameters.get("q") ?? ""; const cursor = parameters.get("cursor");
    if (!taskId || !/^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u.test(taskId) || [...query].length > 160 || query.trim() !== query || /\p{C}/u.test(query) || cursor !== null && !/^[A-Za-z0-9_-]{1,512}$/u.test(cursor)) return null;
    return [taskId, query, cursor] as const;
    } },
    handler: async ({ value }) => { if (!value) return planningFixed("invalid", 400); try { return Response.json(await fetchPicker(...value), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); } },
  });
}
