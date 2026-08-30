import { createProjectHandler } from "@/lib/project-creation-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const POST = createProjectHandler();
