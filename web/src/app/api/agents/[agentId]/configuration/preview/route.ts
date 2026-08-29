import { createAgentConfigurationHandlers } from "@/lib/agent-configuration-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const POST = createAgentConfigurationHandlers().preview;
