import { createLinkPreviewPreferenceHandlers } from "@/lib/link-preview-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const handlers = createLinkPreviewPreferenceHandlers();
export const GET = handlers.GET;
export const POST = handlers.POST;
