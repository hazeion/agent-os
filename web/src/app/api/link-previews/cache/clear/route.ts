import { createLinkPreviewCacheClearHandler } from "@/lib/link-preview-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const post = createLinkPreviewCacheClearHandler();
export async function POST(request: Request) { return post(request); }
