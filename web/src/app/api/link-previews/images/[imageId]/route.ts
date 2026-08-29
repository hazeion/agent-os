import { createLinkPreviewImageHandler } from "@/lib/link-preview-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const GET = createLinkPreviewImageHandler();
