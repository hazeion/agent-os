import { createCodexReadinessGetHandler } from "@/lib/codex-readiness-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const GET = createCodexReadinessGetHandler();
