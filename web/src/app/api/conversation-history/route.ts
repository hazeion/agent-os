import { createConversationHistoryHandler } from "@/lib/conversation-history-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const GET = createConversationHistoryHandler();
