import { createLinkPreviewPreferenceHandlers } from "@/lib/link-preview-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const handlers = createLinkPreviewPreferenceHandlers();
export async function GET(request: Request) { return handlers.GET(request); }
export async function POST(request: Request) { return handlers.POST(request); }
