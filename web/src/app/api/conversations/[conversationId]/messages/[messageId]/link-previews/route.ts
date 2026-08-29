import { createLinkPreviewMessageHandlers } from "@/lib/link-preview-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const handlers = createLinkPreviewMessageHandlers();
export const GET = handlers.GET;
export const POST = handlers.POST;
