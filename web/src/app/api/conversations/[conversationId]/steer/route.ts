import { createConversationSteerHandler } from "@/lib/conversation-steer-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const POST = createConversationSteerHandler();
