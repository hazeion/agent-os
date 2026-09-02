import { fetchBridgePlanningSearch } from "./bridge-planning-search.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, planningRequestAllowed } from "./planning-overview-route.ts";
import type { PublicPlanningSearch } from "./public-planning-search.ts";

type Search = (query: string, signal?: AbortSignal) => Promise<PublicPlanningSearch>;
const QUERY = /^[^\p{C}]{1,160}$/u;

export function createPlanningSearchHandler({ search = (query, signal) => fetchBridgePlanningSearch(query, fetch, process.env, signal), gatewayPort = process.env.PORT }: Readonly<{ search?: Search; gatewayPort?: string }> = {}) {
  return async function getPlanningSearch(request: Request) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    const entries = [...new URL(request.url).searchParams.entries()];
    if (entries.length !== 1 || entries[0]![0] !== "q" || !QUERY.test(entries[0]![1]) || entries[0]![1].trim() !== entries[0]![1]) return planningFixed("invalid", 400);
    try { return Response.json(await search(entries[0]![1], request.signal), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
  };
}
