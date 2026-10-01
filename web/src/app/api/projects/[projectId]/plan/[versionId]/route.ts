import { createProjectPlanHandler } from "@/lib/project-plan-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const GET = createProjectPlanHandler("version");
