import { createAgentConfigurationHandlers } from "@/lib/agent-configuration-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const handlers = createAgentConfigurationHandlers();
export const GET = handlers.get;
export const POST = handlers.confirm;
