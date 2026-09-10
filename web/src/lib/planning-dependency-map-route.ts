import { fetchBridgePlanningDependencyMap } from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";
import type { PublicPlanningDependencyMap } from "./public-planning.ts";

type SavedView = "all" | "today" | "waiting" | "review" | "someday" | "completed";
type ReadDependencyMap = (projectId: string, query: string, savedView: SavedView) => Promise<PublicPlanningDependencyMap>;

export function createPlanningDependencyMapHandler({ fetchDependencyMap = fetchBridgePlanningDependencyMap, gatewayPort = process.env.PORT }: Readonly<{ fetchDependencyMap?: ReadDependencyMap; gatewayPort?: string }> = {}) {
  return withPlanningGatewayRoute<readonly [string, string, SavedView] | null>("GET", "/api/agent-console/planning-dependency-map", gatewayPort, {
    validator: { validate(request) {
    const entries = [...new URL(request.url).searchParams.entries()];
    if (new Set(entries.map(([key]) => key)).size !== entries.length || entries.some(([key]) => key !== "project_id" && key !== "q" && key !== "view")) return null;
    const parameters = new URLSearchParams(entries); const projectId = parameters.get("project_id"); const query = parameters.get("q"); const view = parameters.get("view");
    if (!projectId || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u.test(projectId) || query !== null && (!query || [...query].length > 160 || query.trim() !== query || /\p{C}/u.test(query)) || view !== null && !(["today", "waiting", "review", "someday", "completed"] as const).includes(view as Exclude<SavedView, "all">)) return null;
    return [projectId, query ?? "", (view ?? "all") as SavedView] as const;
    } },
    handler: async ({ value }) => { if (!value) return planningFixed("invalid", 400); try { return Response.json(await fetchDependencyMap(...value), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); } },
  });
}
