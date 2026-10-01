import { createProjectContextHandler } from "@/lib/project-context-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const GET = createProjectContextHandler("staged-file");
export const DELETE = createProjectContextHandler("discard");
