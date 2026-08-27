import { createConversationQueueActionHandler } from "@/lib/conversation-queue-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const POST = createConversationQueueActionHandler("edit");
