import { createPlanningTaskIntegrationHandler } from "@/lib/planning-task-integrations-route";

export const runtime = "nodejs";
export const POST = createPlanningTaskIntegrationHandler("notes/attach");
