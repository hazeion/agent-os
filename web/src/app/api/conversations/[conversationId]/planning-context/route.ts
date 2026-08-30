import { createConversationPlanningContextGetHandler, createConversationPlanningContextPostHandler } from "@/lib/conversation-planning-context-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const GET = createConversationPlanningContextGetHandler();
export const POST = createConversationPlanningContextPostHandler();
