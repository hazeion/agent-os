import { createProjectInputHandler } from "@/lib/project-planning-input-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const GET = createProjectInputHandler("project");
export const POST = createProjectInputHandler("publish");
