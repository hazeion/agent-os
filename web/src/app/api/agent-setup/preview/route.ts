import { createAgentSetupHandler } from "@/lib/agent-setup-route";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const POST = createAgentSetupHandler("preview");
