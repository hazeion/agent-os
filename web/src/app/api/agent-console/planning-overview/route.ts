import { createPlanningOverviewHandler } from "@/lib/planning-overview-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const get = createPlanningOverviewHandler();
export async function GET(request: Request) { return get(request); }
