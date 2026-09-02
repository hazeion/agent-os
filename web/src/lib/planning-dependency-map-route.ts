import { fetchBridgePlanningDependencyMap } from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, planningRequestAllowed } from "./planning-overview-route.ts";
import type { PublicPlanningDependencyMap } from "./public-planning.ts";

type SavedView = "all" | "today" | "waiting" | "review" | "someday" | "completed";
type ReadDependencyMap = (projectId: string, query: string, savedView: SavedView) => Promise<PublicPlanningDependencyMap>;

export function createPlanningDependencyMapHandler({ fetchDependencyMap = fetchBridgePlanningDependencyMap, gatewayPort = process.env.PORT }: Readonly<{ fetchDependencyMap?: ReadDependencyMap; gatewayPort?: string }> = {}) {
  return async function getPlanningDependencyMap(request: Request) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    const entries = [...new URL(request.url).searchParams.entries()];
    if (new Set(entries.map(([key]) => key)).size !== entries.length || entries.some(([key]) => key !== "project_id" && key !== "q" && key !== "view")) return planningFixed("invalid", 400);
    const parameters = new URLSearchParams(entries); const projectId = parameters.get("project_id"); const query = parameters.get("q"); const view = parameters.get("view");
    if (!projectId || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u.test(projectId) || query !== null && (!query || [...query].length > 160 || query.trim() !== query || /\p{C}/u.test(query)) || view !== null && !(["today", "waiting", "review", "someday", "completed"] as const).includes(view as Exclude<SavedView, "all">)) return planningFixed("invalid", 400);
    try { return Response.json(await fetchDependencyMap(projectId, query ?? "", (view ?? "all") as SavedView), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
  };
}
