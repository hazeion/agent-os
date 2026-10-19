import { createProjectLeadHandler } from "@/lib/project-lead-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const GET = createProjectLeadHandler("project");
export const POST = createProjectLeadHandler("select");
