import { createPlanningTaskDependenciesHandler } from "@/lib/planning-task-dependencies-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const GET = createPlanningTaskDependenciesHandler();
