import { createProjectTaskHandler } from "@/lib/project-creation-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const POST = createProjectTaskHandler();
