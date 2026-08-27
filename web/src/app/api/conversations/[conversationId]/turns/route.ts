import { createConversationTurnPostHandler } from "@/lib/conversation-turn-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const POST = createConversationTurnPostHandler();
