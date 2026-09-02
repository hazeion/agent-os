import { createPlanningTaskRunOnceConfirmHandler } from "@/lib/planning-task-execution-route";

export const runtime = "nodejs";
export const POST = createPlanningTaskRunOnceConfirmHandler();
