import { createConversationRenameHandler } from "@/lib/conversation-rename-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const POST = createConversationRenameHandler();
