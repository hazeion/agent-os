import { createContextPacksHandler } from "@/lib/conversation-media-route";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const GET = createContextPacksHandler();
