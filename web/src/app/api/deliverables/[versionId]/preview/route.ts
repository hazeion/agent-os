import { createProjectDeliverableHandler } from "@/lib/project-deliverable-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const GET = createProjectDeliverableHandler("preview");
