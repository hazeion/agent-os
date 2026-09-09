import { createCodexReadinessGetHandler } from "@/lib/codex-readiness-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const get = createCodexReadinessGetHandler();
export async function GET(request: Request) { return get(request); }
