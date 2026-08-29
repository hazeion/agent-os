import { createAttachmentUploadReceiptHandler } from "@/lib/conversation-media-route";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const GET = createAttachmentUploadReceiptHandler();
