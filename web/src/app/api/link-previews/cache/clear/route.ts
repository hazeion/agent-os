import { createLinkPreviewCacheClearHandler } from "@/lib/link-preview-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const POST = createLinkPreviewCacheClearHandler();
