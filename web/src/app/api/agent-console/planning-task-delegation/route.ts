import { createPlanningTaskDelegationGetHandler } from "@/lib/planning-task-delegation-route";

export const dynamic = "force-dynamic";

export const GET = createPlanningTaskDelegationGetHandler();
