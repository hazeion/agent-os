import { createPlanningMutationHandler } from "@/lib/planning-mutation-route";

export const runtime = "nodejs";
export const POST = createPlanningMutationHandler();
