import { createAgentTaskCreationStatusHandler, createEnableAgentTaskCreationHandler } from "@/lib/agent-task-creation-route";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const POST = createEnableAgentTaskCreationHandler();
export const GET = createAgentTaskCreationStatusHandler();
