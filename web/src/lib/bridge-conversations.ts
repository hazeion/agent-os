export const PUBLIC_CONVERSATIONS_PATH = "/api/conversations";
export const PUBLIC_ACTIVITY_PATH = "/api/agent-activity";
export const PUBLIC_CODEX_READINESS_PATH = "/api/codex-readiness";

const PRIVATE_CONVERSATIONS_PATH = "/bridge/v1/conversations";
const PRIVATE_ACTIVITY_PATH = "/bridge/v1/agent-activity";
const PRIVATE_CODEX_READINESS_PATH = "/bridge/v1/codex-readiness";
const MAXIMUM_RESPONSE_BYTES = 3_000_000;
const READ_TIMEOUT_MILLISECONDS = 3_500;
const MAXIMUM_CONVERSATIONS = 50;
const MAXIMUM_AGENTS = 128;
const MAXIMUM_MESSAGES = 100;
const MAXIMUM_QUEUED_TURNS = 8;
export const CONVERSATION_TURN_BRIDGE_TIMEOUT_MILLISECONDS = 32_000;
export const CODEX_READINESS_BRIDGE_TIMEOUT_MILLISECONDS = 8_000;

type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export type PublicConversationAgent = {
  id: string;
  name: string;
  runtime_type: string;
  system_role: "direct" | null;
  capabilities: string[];
};

export type PublicConversation = {
  id: string;
  agent_id: string;
  title: string;
  title_source: "default" | "first_prompt";
  state: "active" | "archived";
  revision: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
};

export type PublicConversationMessage = {
  id: string;
  conversation_id: string;
  sequence: number;
  role: "user" | "assistant";
  state: "accepted" | "cancelled";
  content: { schema_version: 1; parts: [{ type: "text"; text: string }] };
  run_id: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
};

export type PublicCurrentRun = {
  id: string;
  status: string;
  partial: boolean;
  updated_at: string;
};

export type PublicConversationTurn = {
  id: string;
  conversation_id: string;
  user_message_id: string;
  queue_ordinal: number;
  state: "pending" | "dispatching" | "consumed" | "blocked" | "cancelled";
  blocked_reason: "capacity" | "failed" | "stopped" | "interrupted" | "unknown" | "partial" | null;
  latest_run_id: string | null;
  revision: number;
  attempt_count: 0 | 1;
  created_at: string;
  updated_at: string;
};

export type PublicQueuedConversationTurn = {
  id: string;
  conversation_id: string;
  user_message_id: string;
  queue_ordinal: number;
  state: "pending" | "blocked";
  blocked_reason: "capacity" | "failed" | "stopped" | "interrupted" | "unknown" | "partial" | null;
  revision: number;
  message_revision: number;
  text: string;
  created_at: string;
  updated_at: string;
};

export type PublicConversationTurnSubmission = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  duplicate: boolean;
  disposition: "pending" | "blocked" | "reserved" | "submitting" | "accepted" | "rejected" | "unknown";
  conversation: PublicConversation;
  message: PublicConversationMessage;
  turn: PublicConversationTurn;
  run: PublicCurrentRun | null;
};

export type PublicConversationQueueMutation = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  disposition: "edited" | "cancelled";
  conversation: PublicConversation;
  message: PublicConversationMessage;
  turn: PublicConversationTurn;
};

export type PublicConversationSteerResult = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  action: "steer";
  conversation_id: string;
  run_id: string;
  disposition: "accepted";
};

export type PublicCodexReadiness = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  state: "cli_missing" | "sign_in_required" | "ready" | "unavailable";
  setup_command: "codex login" | null;
};

export type PublicConversationList = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  conversations: PublicConversation[];
  agents: PublicConversationAgent[];
  direct_agent_id: string | null;
  count: number;
  next_cursor: string | null;
};

export type PublicConversationDetail = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  conversation: PublicConversation;
  agent: PublicConversationAgent;
  messages: PublicConversationMessage[];
  next_message_cursor: string | null;
  current_run: PublicCurrentRun | null;
  queued_turns: PublicQueuedConversationTurn[];
};

export type PublicAgentActivity = {
  agent: PublicConversationAgent;
  state: "working" | "waiting" | "failed" | "stopped" | "interrupted" | "idle";
  summary: string;
  attention: boolean;
  updated_at: string | null;
  conversations: Array<{
    id: string;
    title: string;
    run_id: string;
    run_status: string;
    attention: boolean;
    updated_at: string;
  }>;
};

export type PublicActivityPayload = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  activity: PublicAgentActivity[];
  direct_agent_id: string | null;
};

export class BridgeConversationsError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.code = code;
    this.name = "BridgeConversationsError";
  }
}

function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try {
    origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? "");
  } catch {
    throw new BridgeConversationsError("bridge_configuration_invalid");
  }
  const hostname = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (
    origin.protocol !== "http:"
    || !new Set(["127.0.0.1", "::1"]).has(hostname)
    || !origin.port
    || origin.username
    || origin.password
    || origin.pathname !== "/"
    || origin.search
    || origin.hash
    || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)
  ) throw new BridgeConversationsError("bridge_configuration_invalid");
  return { origin: origin.origin, token };
}

function opaqueId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(value);
}

function conversationId(value: unknown): value is string {
  return typeof value === "string" && /^conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u.test(value);
}

function messageId(value: unknown): value is string {
  return typeof value === "string" && /^msg_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u.test(value);
}

function runId(value: unknown): value is string {
  return typeof value === "string" && /^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/u.test(value);
}

function turnId(value: unknown): value is string {
  return typeof value === "string" && /^turn_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u.test(value);
}

function timestamp(value: unknown): value is string {
  return typeof value === "string"
    && value.length <= 40
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u.test(value)
    && !Number.isNaN(Date.parse(value));
}

function text(value: unknown, maximum: number): value is string {
  return typeof value === "string"
    && value.length > 0
    && [...value].length <= maximum
    && value.trim() === value
    && !value.includes("\0");
}

function validAgent(value: unknown): value is PublicConversationAgent {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const agent = value as Record<string, unknown>;
  return Object.keys(agent).sort().join(",") === "capabilities,id,name,runtime_type,system_role"
    && opaqueId(agent.id)
    && text(agent.name, 120)
    && typeof agent.runtime_type === "string"
    && /^[a-z][a-z0-9_-]{0,31}$/u.test(agent.runtime_type)
    && (agent.system_role === null || agent.system_role === "direct")
    && Array.isArray(agent.capabilities)
    && agent.capabilities.length <= 64
    && agent.capabilities.every((capability) => (
      typeof capability === "string" && /^[a-z][a-z0-9_.-]{0,63}$/u.test(capability)
    ))
    && agent.capabilities.every((capability, index, capabilities) => (
      index === 0 || capabilities[index - 1] < capability
    ));
}

function validConversation(value: unknown): value is PublicConversation {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const conversation = value as Record<string, unknown>;
  return Object.keys(conversation).sort().join(",") === "agent_id,archived_at,created_at,id,revision,state,title,title_source,updated_at"
    && conversationId(conversation.id)
    && opaqueId(conversation.agent_id)
    && text(conversation.title, 160)
    && (conversation.title_source === "default" || conversation.title_source === "first_prompt")
    && (conversation.state === "active" || conversation.state === "archived")
    && Number.isInteger(conversation.revision)
    && (conversation.revision as number) >= 1
    && timestamp(conversation.created_at)
    && timestamp(conversation.updated_at)
    && (conversation.archived_at === null || timestamp(conversation.archived_at))
    && (conversation.state === "active" ? conversation.archived_at === null : conversation.archived_at !== null);
}

function validContent(value: unknown, role: unknown): value is PublicConversationMessage["content"] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const content = value as Record<string, unknown>;
  const parts = content.parts;
  return Object.keys(content).sort().join(",") === "parts,schema_version"
    && content.schema_version === 1
    && Array.isArray(parts)
    && parts.length === 1
    && !!parts[0]
    && typeof parts[0] === "object"
    && !Array.isArray(parts[0])
    && Object.keys(parts[0] as object).sort().join(",") === "text,type"
    && (parts[0] as Record<string, unknown>).type === "text"
    && text((parts[0] as Record<string, unknown>).text, role === "user" ? 6_000 : 20_000);
}

function validMessage(value: unknown): value is PublicConversationMessage {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const message = value as Record<string, unknown>;
  return Object.keys(message).sort().join(",") === "content,conversation_id,created_at,id,revision,role,run_id,sequence,state,updated_at"
    && messageId(message.id)
    && conversationId(message.conversation_id)
    && Number.isInteger(message.sequence)
    && (message.sequence as number) >= 1
    && (message.role === "user" || message.role === "assistant")
    && (message.state === "accepted" || message.state === "cancelled")
    && validContent(message.content, message.role)
    && (message.run_id === null || runId(message.run_id))
    && Number.isInteger(message.revision)
    && (message.revision as number) >= 1
    && timestamp(message.created_at)
    && timestamp(message.updated_at);
}

function validCurrentRun(value: unknown): value is PublicCurrentRun | null {
  if (value === null) return true;
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const run = value as Record<string, unknown>;
  return Object.keys(run).sort().join(",") === "id,partial,status,updated_at"
    && runId(run.id)
    && typeof run.status === "string"
    && ["reserved", "queued", "submitting", "starting", "running", "cancelling", "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown", "completed", "failed", "cancelled", "stopped", "interrupted"].includes(run.status)
    && typeof run.partial === "boolean"
    && timestamp(run.updated_at);
}

function validTurn(value: unknown): value is PublicConversationTurn {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const turn = value as Record<string, unknown>;
  return Object.keys(turn).sort().join(",") === "attempt_count,blocked_reason,conversation_id,created_at,id,latest_run_id,queue_ordinal,revision,state,updated_at,user_message_id"
    && turnId(turn.id)
    && conversationId(turn.conversation_id)
    && messageId(turn.user_message_id)
    && Number.isInteger(turn.queue_ordinal)
    && (turn.queue_ordinal as number) >= 1
    && ["pending", "dispatching", "consumed", "blocked", "cancelled"].includes(String(turn.state))
    && ((turn.state === "blocked") === (turn.blocked_reason !== null))
    && (turn.blocked_reason === null || ["capacity", "failed", "stopped", "interrupted", "unknown", "partial"].includes(String(turn.blocked_reason)))
    && (turn.latest_run_id === null || runId(turn.latest_run_id))
    && Number.isInteger(turn.revision)
    && (turn.revision as number) >= 1
    && (turn.attempt_count === 0 || turn.attempt_count === 1)
    && timestamp(turn.created_at)
    && timestamp(turn.updated_at);
}

function validQueuedTurn(value: unknown): value is PublicQueuedConversationTurn {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const turn = value as Record<string, unknown>;
  return Object.keys(turn).sort().join(",") === "blocked_reason,conversation_id,created_at,id,message_revision,queue_ordinal,revision,state,text,updated_at,user_message_id"
    && turnId(turn.id)
    && conversationId(turn.conversation_id)
    && messageId(turn.user_message_id)
    && Number.isInteger(turn.queue_ordinal)
    && (turn.queue_ordinal as number) >= 1
    && (turn.state === "pending" || turn.state === "blocked")
    && ((turn.state === "blocked") === (turn.blocked_reason !== null))
    && (turn.blocked_reason === null || ["capacity", "failed", "stopped", "interrupted", "unknown", "partial"].includes(String(turn.blocked_reason)))
    && Number.isInteger(turn.revision)
    && (turn.revision as number) >= 1
    && Number.isInteger(turn.message_revision)
    && (turn.message_revision as number) >= 1
    && text(turn.text, 6_000)
    && timestamp(turn.created_at)
    && timestamp(turn.updated_at);
}

function validTurnSubmission(value: unknown): value is PublicConversationTurnSubmission {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  if (
    Object.keys(payload).sort().join(",") !== "conversation,disposition,duplicate,message,run,runtime,schema_version,service,status,turn"
    || payload.schema_version !== 1
    || payload.service !== "mentat-local-bridge"
    || payload.runtime !== "python"
    || payload.status !== "ready"
    || typeof payload.duplicate !== "boolean"
    || !["pending", "blocked", "reserved", "submitting", "accepted", "rejected", "unknown"].includes(String(payload.disposition))
    || !validConversation(payload.conversation)
    || !validMessage(payload.message)
    || !validTurn(payload.turn)
    || !validCurrentRun(payload.run)
  ) return false;
  const conversation = payload.conversation as PublicConversation;
  const message = payload.message as PublicConversationMessage;
  const turn = payload.turn as PublicConversationTurn;
  const run = payload.run as PublicCurrentRun | null;
  return message.conversation_id === conversation.id
    && turn.conversation_id === conversation.id
    && turn.user_message_id === message.id
    && message.run_id === turn.latest_run_id
    && (run === null || run.id === turn.latest_run_id);
}

function validQueueMutation(value: unknown): value is PublicConversationQueueMutation {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  if (
    Object.keys(payload).sort().join(",") !== "conversation,disposition,message,runtime,schema_version,service,status,turn"
    || payload.schema_version !== 1
    || payload.service !== "mentat-local-bridge"
    || payload.runtime !== "python"
    || payload.status !== "ready"
    || (payload.disposition !== "edited" && payload.disposition !== "cancelled")
    || !validConversation(payload.conversation)
    || !validMessage(payload.message)
    || !validTurn(payload.turn)
  ) return false;
  const conversation = payload.conversation as PublicConversation;
  const message = payload.message as PublicConversationMessage;
  const turn = payload.turn as PublicConversationTurn;
  return message.conversation_id === conversation.id
    && turn.conversation_id === conversation.id
    && turn.user_message_id === message.id
    && message.run_id === turn.latest_run_id
    && (payload.disposition === "edited"
      ? (turn.state === "pending" || turn.state === "blocked") && message.state === "accepted"
      : turn.state === "cancelled" && message.state === "cancelled");
}

function validSteer(value: unknown): value is PublicConversationSteerResult {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  return Object.keys(payload).sort().join(",") === "action,conversation_id,disposition,run_id,runtime,schema_version,service,status"
    && payload.schema_version === 1
    && payload.service === "mentat-local-bridge"
    && payload.runtime === "python"
    && payload.status === "ready"
    && payload.action === "steer"
    && conversationId(payload.conversation_id)
    && runId(payload.run_id)
    && payload.disposition === "accepted";
}

function validCodexReadiness(value: unknown): value is PublicCodexReadiness {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  return Object.keys(payload).sort().join(",") === "runtime,schema_version,service,setup_command,state,status"
    && payload.schema_version === 1
    && payload.service === "mentat-local-bridge"
    && payload.runtime === "python"
    && payload.status === "ready"
    && ["cli_missing", "sign_in_required", "ready", "unavailable"].includes(String(payload.state))
    && (payload.setup_command === null || payload.setup_command === "codex login")
    && ((payload.state === "sign_in_required") === (payload.setup_command === "codex login"));
}

function validList(value: unknown): value is PublicConversationList {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  const conversations = payload.conversations;
  const agents = payload.agents;
  const directAgentId = payload.direct_agent_id;
  if (
    Object.keys(payload).sort().join(",") !== "agents,conversations,count,direct_agent_id,next_cursor,runtime,schema_version,service,status"
    || payload.schema_version !== 1
    || payload.service !== "mentat-local-bridge"
    || payload.runtime !== "python"
    || payload.status !== "ready"
    || !Array.isArray(conversations)
    || conversations.length > MAXIMUM_CONVERSATIONS
    || !Array.isArray(agents)
    || agents.length > MAXIMUM_AGENTS
    || !Number.isInteger(payload.count)
    || payload.count !== conversations.length
    || (payload.next_cursor !== null && !/^[A-Za-z0-9_-]{1,256}$/u.test(String(payload.next_cursor)))
    || (directAgentId !== null && !opaqueId(directAgentId))
    || !agents.every(validAgent)
    || !conversations.every(validConversation)
  ) return false;
  const agentIds = new Set(agents.map((agent) => (agent as PublicConversationAgent).id));
  return new Set(conversations.map((conversation) => (conversation as PublicConversation).id)).size === conversations.length
    && agentIds.size === agents.length
    && conversations.every((conversation) => agentIds.has((conversation as PublicConversation).agent_id))
    && (directAgentId === null || agents.some((agent) => (
      (agent as PublicConversationAgent).id === directAgentId
      && (agent as PublicConversationAgent).system_role === "direct"
    )));
}

function validDetail(value: unknown): value is PublicConversationDetail {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  const messages = payload.messages;
  const queuedTurns = payload.queued_turns;
  return Object.keys(payload).sort().join(",") === "agent,conversation,current_run,messages,next_message_cursor,queued_turns,runtime,schema_version,service,status"
    && payload.schema_version === 1
    && payload.service === "mentat-local-bridge"
    && payload.runtime === "python"
    && payload.status === "ready"
    && validConversation(payload.conversation)
    && validAgent(payload.agent)
    && (payload.conversation as PublicConversation).agent_id === (payload.agent as PublicConversationAgent).id
    && Array.isArray(messages)
    && messages.length <= MAXIMUM_MESSAGES
    && messages.every(validMessage)
    && messages.every((message) => (message as PublicConversationMessage).conversation_id === (payload.conversation as PublicConversation).id)
    && messages.every((message, index) => index === 0 || (messages[index - 1] as PublicConversationMessage).sequence < (message as PublicConversationMessage).sequence)
    && Array.isArray(queuedTurns)
    && queuedTurns.length <= MAXIMUM_QUEUED_TURNS
    && queuedTurns.every(validQueuedTurn)
    && queuedTurns.every((turn) => (turn as PublicQueuedConversationTurn).conversation_id === (payload.conversation as PublicConversation).id)
    && queuedTurns.every((turn, index) => index === 0 || (queuedTurns[index - 1] as PublicQueuedConversationTurn).queue_ordinal < (turn as PublicQueuedConversationTurn).queue_ordinal)
    && new Set(queuedTurns.map((turn) => (turn as PublicQueuedConversationTurn).id)).size === queuedTurns.length
    && new Set(queuedTurns.map((turn) => (turn as PublicQueuedConversationTurn).user_message_id)).size === queuedTurns.length
    && (payload.next_message_cursor === null || /^[1-9][0-9]{0,9}$/u.test(String(payload.next_message_cursor)))
    && validCurrentRun(payload.current_run);
}

function validActivityItem(value: unknown): value is PublicAgentActivity {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  const conversations = item.conversations;
  return Object.keys(item).sort().join(",") === "agent,attention,conversations,state,summary,updated_at"
    && validAgent(item.agent)
    && ["working", "waiting", "failed", "stopped", "interrupted", "idle"].includes(item.state as string)
    && text(item.summary, 160)
    && typeof item.attention === "boolean"
    && (item.updated_at === null || timestamp(item.updated_at))
    && Array.isArray(conversations)
    && conversations.length <= 8
    && conversations.every((conversation) => {
      if (!conversation || typeof conversation !== "object" || Array.isArray(conversation)) return false;
      const value = conversation as Record<string, unknown>;
      return Object.keys(value).sort().join(",") === "attention,id,run_id,run_status,title,updated_at"
        && conversationId(value.id)
        && text(value.title, 160)
        && runId(value.run_id)
        && typeof value.run_status === "string"
        && ["reserved", "queued", "submitting", "starting", "running", "cancelling", "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown", "completed", "failed", "cancelled", "stopped", "interrupted"].includes(value.run_status)
        && typeof value.attention === "boolean"
        && timestamp(value.updated_at);
    });
}

function validActivity(value: unknown): value is PublicActivityPayload {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  const activity = payload.activity;
  return Object.keys(payload).sort().join(",") === "activity,direct_agent_id,runtime,schema_version,service,status"
    && payload.schema_version === 1
    && payload.service === "mentat-local-bridge"
    && payload.runtime === "python"
    && payload.status === "ready"
    && Array.isArray(activity)
    && activity.length <= MAXIMUM_AGENTS
    && activity.every(validActivityItem)
    && new Set(activity.map((item) => (item as PublicAgentActivity).agent.id)).size === activity.length
    && (payload.direct_agent_id === null || opaqueId(payload.direct_agent_id));
}

async function boundedJson(response: Response): Promise<unknown> {
  const declaredLength = response.headers.get("content-length");
  if (declaredLength && (!/^\d{1,10}$/u.test(declaredLength) || Number(declaredLength) > MAXIMUM_RESPONSE_BYTES)) {
    throw new BridgeConversationsError("bridge_response_invalid");
  }
  if (!response.body) throw new BridgeConversationsError("bridge_response_invalid");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      total += next.value.byteLength;
      if (total > MAXIMUM_RESPONSE_BYTES) {
        await reader.cancel();
        throw new BridgeConversationsError("bridge_response_invalid");
      }
      chunks.push(next.value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
  } catch {
    throw new BridgeConversationsError("bridge_response_invalid");
  }
}

async function requestBridge(
  path: string,
  fetcher: FetchLike,
  environment: Environment,
  init: RequestInit,
  timeoutMilliseconds = READ_TIMEOUT_MILLISECONDS,
): Promise<{ response: Response; payload: unknown }> {
  const bridge = configuration(environment);
  try {
    const response = await fetcher(new URL(path, bridge.origin), {
      ...init,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "X-Mentat-Bridge-Token": bridge.token,
        ...init.headers,
      },
      redirect: "error",
      signal: AbortSignal.timeout(timeoutMilliseconds),
    });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
      throw new BridgeConversationsError("bridge_response_invalid");
    }
    return { payload: await boundedJson(response), response };
  } catch (error) {
    if (error instanceof BridgeConversationsError) throw error;
    throw new BridgeConversationsError("bridge_unavailable");
  }
}

function handleFixedState(response: Response, payload: unknown): never {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new BridgeConversationsError("bridge_response_invalid");
  }
  const value = payload as Record<string, unknown>;
  if (Object.keys(value).sort().join(",") !== "runtime,schema_version,service,status" || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python") {
    throw new BridgeConversationsError("bridge_response_invalid");
  }
  if (response.status === 400 && value.status === "invalid") throw new BridgeConversationsError("conversation_request_invalid");
  if (response.status === 404 && value.status === "not_found") throw new BridgeConversationsError("conversation_not_found");
  if (response.status === 409 && value.status === "active_run") throw new BridgeConversationsError("conversation_active_run");
  if (response.status === 409 && value.status === "capacity_unavailable") throw new BridgeConversationsError("conversation_capacity_unavailable");
  if (response.status === 409 && value.status === "idempotency_conflict") throw new BridgeConversationsError("conversation_idempotency_conflict");
  if (response.status === 409 && value.status === "conflict") throw new BridgeConversationsError("conversation_conflict");
  if (response.status === 409 && value.status === "cli_missing") throw new BridgeConversationsError("codex_cli_missing");
  if (response.status === 409 && value.status === "sign_in_required") throw new BridgeConversationsError("codex_sign_in_required");
  if (response.status === 501 && value.status === "unsupported") throw new BridgeConversationsError("bridge_unsupported");
  if (response.status === 503 && value.status === "unavailable") throw new BridgeConversationsError("bridge_unavailable");
  if (response.status === 500 && value.status === "partial") throw new BridgeConversationsError("conversation_partial");
  throw new BridgeConversationsError("bridge_response_invalid");
}

export async function fetchBridgeConversations(
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
  cursor: string | null = null,
): Promise<PublicConversationList> {
  if (cursor !== null && !/^[A-Za-z0-9_-]{1,256}$/u.test(cursor)) {
    throw new BridgeConversationsError("conversation_cursor_invalid");
  }
  const path = `${PRIVATE_CONVERSATIONS_PATH}${cursor === null ? "" : `?cursor=${encodeURIComponent(cursor)}`}`;
  const { response, payload } = await requestBridge(path, fetcher, environment, { method: "GET" });
  if (response.status === 200 && validList(payload)) {
    return {
      ...payload,
      conversations: payload.conversations.map((conversation) => ({ ...conversation })),
      agents: payload.agents.map((agent) => ({ ...agent, capabilities: [...agent.capabilities] })),
    };
  }
  handleFixedState(response, payload);
}

export async function fetchBridgeConversation(
  id: string,
  before: string | null = null,
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
): Promise<PublicConversationDetail> {
  if (!conversationId(id) || (before !== null && !/^[1-9][0-9]{0,9}$/u.test(before))) {
    throw new BridgeConversationsError("conversation_id_invalid");
  }
  const path = `${PRIVATE_CONVERSATIONS_PATH}/${encodeURIComponent(id)}${before === null ? "" : `?before=${before}`}`;
  const { response, payload } = await requestBridge(path, fetcher, environment, { method: "GET" });
  if (response.status === 200 && validDetail(payload) && payload.conversation.id === id) {
    return {
      ...payload,
      conversation: { ...payload.conversation },
      agent: { ...payload.agent, capabilities: [...payload.agent.capabilities] },
      messages: payload.messages.map((message) => ({
        ...message,
        content: { schema_version: 1, parts: [{ type: "text", text: message.content.parts[0].text }] },
      })),
      queued_turns: payload.queued_turns.map((turn) => ({ ...turn })),
    };
  }
  if (response.status === 404 && payload && typeof payload === "object" && !Array.isArray(payload) && Object.keys(payload).sort().join(",") === "runtime,schema_version,service,status" && (payload as Record<string, unknown>).status === "not_found") {
    throw new BridgeConversationsError("conversation_not_found");
  }
  handleFixedState(response, payload);
}

export async function createBridgeConversation(
  agentId: string | null,
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
): Promise<PublicConversationDetail> {
  if (agentId !== null && !opaqueId(agentId)) throw new BridgeConversationsError("agent_id_invalid");
  const { response, payload } = await requestBridge(PRIVATE_CONVERSATIONS_PATH, fetcher, environment, {
    body: JSON.stringify(agentId === null ? {} : { agent_id: agentId }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  if (
    response.status === 201
    && validDetail(payload)
    && (agentId === null || payload.conversation.agent_id === agentId)
  ) return payload;
  if (response.status === 404 && payload && typeof payload === "object" && !Array.isArray(payload) && (payload as Record<string, unknown>).status === "not_found") {
    throw new BridgeConversationsError("conversation_not_found");
  }
  handleFixedState(response, payload);
}

export async function submitBridgeConversationTurn(
  id: string,
  text: string,
  idempotencyKey: string,
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
  timeoutMilliseconds = CONVERSATION_TURN_BRIDGE_TIMEOUT_MILLISECONDS,
): Promise<PublicConversationTurnSubmission> {
  const keyBytes = typeof idempotencyKey === "string"
    ? new TextEncoder().encode(idempotencyKey).byteLength
    : 0;
  if (
    !conversationId(id)
    || typeof text !== "string"
    || !text.trim()
    || text.trim() !== text
    || [...text].length > 6_000
    || text.includes("\0")
    || keyBytes < 16
    || keyBytes > 256
    || idempotencyKey.includes("\0")
  ) throw new BridgeConversationsError("conversation_request_invalid");
  const { response, payload } = await requestBridge(
    `${PRIVATE_CONVERSATIONS_PATH}/${encodeURIComponent(id)}/turns`,
    fetcher,
    environment,
    {
      body: JSON.stringify({ idempotency_key: idempotencyKey, text }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    timeoutMilliseconds,
  );
  if (
    (response.status === 200 || response.status === 202)
    && validTurnSubmission(payload)
    && payload.conversation.id === id
    && payload.message.content.parts[0].text === text
  ) {
    return {
      ...payload,
      conversation: { ...payload.conversation },
      message: {
        ...payload.message,
        content: {
          schema_version: 1,
          parts: [{ type: "text", text: payload.message.content.parts[0].text }],
        },
      },
      turn: { ...payload.turn },
      run: payload.run === null ? null : { ...payload.run },
    };
  }
  handleFixedState(response, payload);
}

async function mutateBridgeConversationTurn(
  conversation: string,
  turn: string,
  action: "edit" | "cancel" | "continue",
  expectedRevision: number,
  expectedMessageRevision: number,
  replacementText: string | null,
  fetcher: FetchLike,
  environment: Environment,
): Promise<PublicConversationQueueMutation | PublicConversationTurnSubmission> {
  if (
    !conversationId(conversation)
    || !turnId(turn)
    || !Number.isInteger(expectedRevision)
    || expectedRevision < 1
    || !Number.isInteger(expectedMessageRevision)
    || expectedMessageRevision < 1
    || (action === "edit" && (replacementText === null || !text(replacementText, 6_000)))
    || (action !== "edit" && replacementText !== null)
  ) throw new BridgeConversationsError("conversation_request_invalid");
  const body = action === "edit"
    ? {
        expected_message_revision: expectedMessageRevision,
        expected_revision: expectedRevision,
        text: replacementText,
      }
    : {
        expected_message_revision: expectedMessageRevision,
        expected_revision: expectedRevision,
      };
  const { response, payload } = await requestBridge(
    `${PRIVATE_CONVERSATIONS_PATH}/${encodeURIComponent(conversation)}/turns/${encodeURIComponent(turn)}/${action}`,
    fetcher,
    environment,
    {
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    action === "continue"
      ? CONVERSATION_TURN_BRIDGE_TIMEOUT_MILLISECONDS
      : READ_TIMEOUT_MILLISECONDS,
  );
  if (
    action === "continue"
    && (response.status === 200 || response.status === 202)
    && validTurnSubmission(payload)
    && payload.conversation.id === conversation
    && payload.turn.id === turn
  ) return payload;
  if (
    action !== "continue"
    && response.status === 200
    && validQueueMutation(payload)
    && payload.conversation.id === conversation
    && payload.turn.id === turn
    && (action !== "edit" || payload.message.content.parts[0].text === replacementText)
  ) return payload;
  handleFixedState(response, payload);
}

export function editBridgeConversationTurn(
  conversation: string,
  turn: string,
  expectedRevision: number,
  expectedMessageRevision: number,
  replacementText: string,
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
): Promise<PublicConversationQueueMutation> {
  return mutateBridgeConversationTurn(
    conversation,
    turn,
    "edit",
    expectedRevision,
    expectedMessageRevision,
    replacementText,
    fetcher,
    environment,
  ) as Promise<PublicConversationQueueMutation>;
}

export function cancelBridgeConversationTurn(
  conversation: string,
  turn: string,
  expectedRevision: number,
  expectedMessageRevision: number,
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
): Promise<PublicConversationQueueMutation> {
  return mutateBridgeConversationTurn(
    conversation,
    turn,
    "cancel",
    expectedRevision,
    expectedMessageRevision,
    null,
    fetcher,
    environment,
  ) as Promise<PublicConversationQueueMutation>;
}

export function continueBridgeConversationTurn(
  conversation: string,
  turn: string,
  expectedRevision: number,
  expectedMessageRevision: number,
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
): Promise<PublicConversationTurnSubmission> {
  return mutateBridgeConversationTurn(
    conversation,
    turn,
    "continue",
    expectedRevision,
    expectedMessageRevision,
    null,
    fetcher,
    environment,
  ) as Promise<PublicConversationTurnSubmission>;
}

export async function steerBridgeConversation(
  conversation: string,
  run: string,
  steerText: string,
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
): Promise<PublicConversationSteerResult> {
  if (!conversationId(conversation) || !runId(run) || !text(steerText, 6_000)) {
    throw new BridgeConversationsError("conversation_request_invalid");
  }
  const { response, payload } = await requestBridge(
    `${PRIVATE_CONVERSATIONS_PATH}/${encodeURIComponent(conversation)}/steer`,
    fetcher,
    environment,
    {
      body: JSON.stringify({ run_id: run, text: steerText }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    CONVERSATION_TURN_BRIDGE_TIMEOUT_MILLISECONDS,
  );
  if (
    response.status === 200
    && validSteer(payload)
    && payload.conversation_id === conversation
    && payload.run_id === run
  ) return payload;
  handleFixedState(response, payload);
}

export async function fetchBridgeCodexReadiness(
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
  timeoutMilliseconds = CODEX_READINESS_BRIDGE_TIMEOUT_MILLISECONDS,
): Promise<PublicCodexReadiness> {
  const { response, payload } = await requestBridge(
    PRIVATE_CODEX_READINESS_PATH,
    fetcher,
    environment,
    { method: "GET" },
    timeoutMilliseconds,
  );
  if (response.status === 200 && validCodexReadiness(payload)) return { ...payload };
  handleFixedState(response, payload);
}

export async function fetchBridgeActivity(
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
): Promise<PublicActivityPayload> {
  const { response, payload } = await requestBridge(PRIVATE_ACTIVITY_PATH, fetcher, environment, { method: "GET" });
  if (response.status === 200 && validActivity(payload)) {
    return {
      ...payload,
      activity: payload.activity.map((item) => ({
        ...item,
        agent: { ...item.agent, capabilities: [...item.agent.capabilities] },
        conversations: item.conversations.map((conversation) => ({ ...conversation })),
      })),
    };
  }
  handleFixedState(response, payload);
}
