import { createPlanningCalendarHandler } from "@/lib/planning-task-integrations-route";

export const runtime = "nodejs";
export const GET = createPlanningCalendarHandler();
