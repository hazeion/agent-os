import { createPlanningTaskExecutionRefreshHandler } from "@/lib/planning-task-execution-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const POST = createPlanningTaskExecutionRefreshHandler();
