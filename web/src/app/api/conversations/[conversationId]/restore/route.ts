import { createConversationArchiveHandler } from "@/lib/conversation-archive-route";

export const dynamic = "force-dynamic";
export const POST = createConversationArchiveHandler(false);
