import { createPlanningTaskRunOncePreviewHandler } from "@/lib/planning-task-execution-route";

export const runtime = "nodejs";
export const POST = createPlanningTaskRunOncePreviewHandler();
