import { createAttachmentUploadHandler } from "@/lib/conversation-media-route";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const POST = createAttachmentUploadHandler();
