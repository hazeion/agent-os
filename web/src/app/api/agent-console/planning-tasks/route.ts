import { createPlanningTasksHandler } from "@/lib/planning-tasks-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const GET = createPlanningTasksHandler();
