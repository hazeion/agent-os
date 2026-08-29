import { createAgentAttachmentsEnableStatusHandler, createEnableAgentAttachmentsHandler } from "@/lib/agent-attachments-route";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const POST = createEnableAgentAttachmentsHandler();
export const GET = createAgentAttachmentsEnableStatusHandler();
