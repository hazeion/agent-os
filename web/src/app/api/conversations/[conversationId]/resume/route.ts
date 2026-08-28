import { createConversationResumeHandler } from "@/lib/conversation-retry-route";

export const dynamic = "force-dynamic";
export const POST = createConversationResumeHandler();
