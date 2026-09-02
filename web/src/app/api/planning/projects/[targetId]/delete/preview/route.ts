import { createPlanningDeletionPreviewHandler } from "@/lib/planning-deletion-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const POST = createPlanningDeletionPreviewHandler("project");
