import type {
  PublicActivityPayload,
  PublicConversation,
  PublicConversationAgent,
  PublicConversationArchiveResult,
  PublicConversationRunAttemptResult,
  PublicConversationDetail,
  PublicConversationList,
  PublicConversationHistory,
  PublicConversationRenameResult,
  PublicConversationQueueMutation,
  PublicConversationSteerResult,
  PublicQueuedConversationTurn,
  PublicConversationTurn,
  PublicConversationTurnSubmission,
  PublicCodexReadiness,
  PublicCurrentRun,
} from "./bridge-conversations";

const MAXIMUM_RESPONSE_BYTES = 3_000_000;
const MAXIMUM_MESSAGES = 100;
const MAXIMUM_CONVERSATIONS = 50;
const MAXIMUM_AGENTS = 128;
const MAXIMUM_QUEUED_TURNS = 8;
const READ_TIMEOUT_MILLISECONDS = 5_000;

export class PublicConversationError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.code = code;
    this.name = "PublicConversationError";
  }
}

export const CONVERSATION_TURN_PUBLIC_TIMEOUT_MILLISECONDS = 40_000;
export const CODEX_READINESS_PUBLIC_TIMEOUT_MILLISECONDS = 10_000;

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function keys(value: Record<string, unknown>, expected: string): boolean {
  return Object.keys(value).sort().join(",") === expected;
}

function boundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string"
    && value.length > 0
    && [...value].length <= maximum
    && value.trim() === value
    && !value.includes("\0");
}

function id(value: unknown, pattern: RegExp): value is string {
  return typeof value === "string" && pattern.test(value);
}

const CONVERSATION_ID = /^conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u;
const MESSAGE_ID = /^msg_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u;
const RUN_ID = /^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/u;
const TURN_ID = /^turn_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u;
const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u;

function timestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 && TIMESTAMP.test(value) && !Number.isNaN(Date.parse(value));
}

function validAgent(value: unknown): value is PublicConversationAgent {
  if (!record(value) || !keys(value, "capabilities,id,name,runtime_type,system_role")) return false;
  return id(value.id, OPAQUE_ID)
    && boundedText(value.name, 120)
    && typeof value.runtime_type === "string"
    && /^[a-z][a-z0-9_-]{0,31}$/u.test(value.runtime_type)
    && (value.system_role === null || value.system_role === "direct")
    && Array.isArray(value.capabilities)
    && value.capabilities.length <= 64
    && value.capabilities.every((item) => typeof item === "string" && /^[a-z][a-z0-9_.-]{0,63}$/u.test(item))
    && value.capabilities.every((item, index, all) => index === 0 || all[index - 1] < item);
}

function validConversation(value: unknown): value is PublicConversation {
  if (!record(value) || !keys(value, "agent_id,archived_at,created_at,id,revision,state,title,title_source,updated_at")) return false;
  return id(value.id, CONVERSATION_ID)
    && id(value.agent_id, OPAQUE_ID)
    && boundedText(value.title, 160)
    && ["default", "first_prompt", "manual"].includes(String(value.title_source))
    && (value.state === "active" || value.state === "archived")
    && Number.isInteger(value.revision) && (value.revision as number) >= 1
    && timestamp(value.created_at) && timestamp(value.updated_at)
    && (value.archived_at === null || timestamp(value.archived_at))
    && (value.state === "active" ? value.archived_at === null : value.archived_at !== null);
}

function parseHistory(value: unknown): PublicConversationHistory {
  if (!record(value) || !keys(value, "conversations,count,next_cursor,runtime,schema_version,service,status")) throw new PublicConversationError("response_invalid");
  const conversations = value.conversations;
  if (
    value.schema_version !== 1
    || value.service !== "mentat-local-bridge"
    || value.runtime !== "python"
    || value.status !== "ready"
    || !Array.isArray(conversations)
    || conversations.length > MAXIMUM_CONVERSATIONS
    || !conversations.every(validConversation)
    || new Set(conversations.map((conversation) => (conversation as PublicConversation).id)).size !== conversations.length
    || !Number.isInteger(value.count)
    || value.count !== conversations.length
    || value.next_cursor !== null && (typeof value.next_cursor !== "string" || !/^[A-Za-z0-9_-]{1,512}$/u.test(value.next_cursor))
  ) throw new PublicConversationError("response_invalid");
  return structuredClone(value) as PublicConversationHistory;
}

function historyMatchesStateAndOrder(
  history: PublicConversationHistory,
  state: "all" | "active" | "archived",
): boolean {
  if (history.conversations.some((conversation) => (
    state !== "all" && conversation.state !== state
  ))) return false;
  return history.conversations.every((conversation, index, rows) => {
    if (index === 0) return true;
    const previous = rows[index - 1]!;
    const previousRank = previous.state === "active" ? 0 : 1;
    const rank = conversation.state === "active" ? 0 : 1;
    return previousRank < rank
      || previousRank === rank
      && (previous.updated_at > conversation.updated_at
        || previous.updated_at === conversation.updated_at && previous.id > conversation.id);
  });
}

function parseRenameResult(value: unknown): PublicConversationRenameResult {
  if (
    !record(value)
    || !keys(value, "action,conversation,runtime,schema_version,service,status")
    || value.schema_version !== 1
    || value.service !== "mentat-local-bridge"
    || value.runtime !== "python"
    || value.status !== "ready"
    || value.action !== "rename"
    || !validConversation(value.conversation)
    || value.conversation.title_source !== "manual"
  ) throw new PublicConversationError("response_invalid");
  return structuredClone(value) as PublicConversationRenameResult;
}

function validMessage(value: unknown): boolean {
  if (!record(value) || !keys(value, "content,conversation_id,created_at,id,revision,role,run_id,sequence,state,updated_at")) return false;
  const content = value.content;
  if (!record(content) || !keys(content, "parts,schema_version") || content.schema_version !== 1 || !Array.isArray(content.parts) || content.parts.length !== 1 || !record(content.parts[0])) return false;
  const part = content.parts[0];
  return id(value.id, MESSAGE_ID)
    && id(value.conversation_id, CONVERSATION_ID)
    && Number.isInteger(value.sequence) && (value.sequence as number) >= 1
    && (value.role === "user" || value.role === "assistant")
    && (value.state === "accepted" || value.state === "cancelled")
    && keys(part, "text,type") && part.type === "text"
    && boundedText(part.text, value.role === "user" ? 6_000 : 20_000)
    && (value.run_id === null || id(value.run_id, RUN_ID))
    && Number.isInteger(value.revision) && (value.revision as number) >= 1
    && timestamp(value.created_at) && timestamp(value.updated_at);
}

function validCurrentRun(value: unknown): boolean {
  if (value === null) return true;
  if (!record(value) || !["id,partial,status,updated_at", "configuration,id,partial,status,updated_at"].includes(Object.keys(value).sort().join(","))) return false;
  const configuration = value.configuration;
  return id(value.id, RUN_ID)
    && typeof value.status === "string"
    && ["reserved", "queued", "submitting", "starting", "running", "cancelling", "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown", "finalizing", "completed", "failed", "cancelled", "stopped", "interrupted"].includes(value.status)
    && typeof value.partial === "boolean"
    && timestamp(value.updated_at)
    && (configuration === undefined || configuration === null || record(configuration)
      && keys(configuration, "effort,model,provider")
      && boundedText(configuration.provider, 160)
      && boundedText(configuration.model, 160)
      && boundedText(configuration.effort, 64));
}

function validTurn(value: unknown): value is PublicConversationTurn {
  if (!record(value) || !keys(value, "attempt_count,blocked_reason,conversation_id,created_at,id,latest_run_id,queue_ordinal,revision,state,updated_at,user_message_id")) return false;
  return id(value.id, TURN_ID)
    && id(value.conversation_id, CONVERSATION_ID)
    && id(value.user_message_id, MESSAGE_ID)
    && Number.isInteger(value.queue_ordinal) && (value.queue_ordinal as number) >= 1
    && ["pending", "dispatching", "consumed", "blocked", "cancelled"].includes(String(value.state))
    && ((value.state === "blocked") === (value.blocked_reason !== null))
    && (value.blocked_reason === null || ["capacity", "failed", "stopped", "interrupted", "unknown", "partial"].includes(String(value.blocked_reason)))
    && (value.latest_run_id === null || id(value.latest_run_id, RUN_ID))
    && Number.isInteger(value.revision) && (value.revision as number) >= 1
    && Number.isInteger(value.attempt_count)
    && (value.attempt_count as number) >= 0
    && (value.attempt_count as number) <= 8
    && timestamp(value.created_at) && timestamp(value.updated_at);
}

function validQueuedTurn(value: unknown): value is PublicQueuedConversationTurn {
  if (!record(value) || !keys(value, "blocked_reason,conversation_id,created_at,id,message_revision,queue_ordinal,revision,state,text,updated_at,user_message_id")) return false;
  return id(value.id, TURN_ID)
    && id(value.conversation_id, CONVERSATION_ID)
    && id(value.user_message_id, MESSAGE_ID)
    && Number.isInteger(value.queue_ordinal) && (value.queue_ordinal as number) >= 1
    && (value.state === "pending" || value.state === "blocked")
    && ((value.state === "blocked") === (value.blocked_reason !== null))
    && (value.blocked_reason === null || ["capacity", "failed", "stopped", "interrupted", "unknown", "partial"].includes(String(value.blocked_reason)))
    && Number.isInteger(value.revision) && (value.revision as number) >= 1
    && Number.isInteger(value.message_revision) && (value.message_revision as number) >= 1
    && boundedText(value.text, 6_000)
    && timestamp(value.created_at) && timestamp(value.updated_at);
}

function validActivityItem(value: unknown): boolean {
  if (!record(value) || !keys(value, "agent,attention,conversations,state,summary,updated_at")) return false;
  const conversations = value.conversations;
  return validAgent(value.agent)
    && ["checking", "working", "waiting", "failed", "stopped", "interrupted", "idle"].includes(value.state as string)
    && boundedText(value.summary, 160)
    && typeof value.attention === "boolean"
    && (value.updated_at === null || timestamp(value.updated_at))
    && Array.isArray(conversations)
    && conversations.length <= 8
    && conversations.every((conversation) => {
      if (!record(conversation) || !keys(conversation, "attention,id,run_id,run_status,title,updated_at")) return false;
      return id(conversation.id, CONVERSATION_ID)
        && boundedText(conversation.title, 160)
        && id(conversation.run_id, RUN_ID)
        && typeof conversation.run_status === "string"
        && ["reserved", "queued", "submitting", "starting", "running", "cancelling", "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown", "finalizing", "reconciling", "completed", "failed", "cancelled", "stopped", "interrupted"].includes(conversation.run_status)
        && typeof conversation.attention === "boolean"
        && timestamp(conversation.updated_at);
    });
}

function parseList(value: unknown): PublicConversationList {
  if (!record(value) || !keys(value, "agents,conversations,count,direct_agent_id,next_cursor,runtime,schema_version,service,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || !Array.isArray(value.agents) || value.agents.length > MAXIMUM_AGENTS || !Array.isArray(value.conversations) || value.conversations.length > MAXIMUM_CONVERSATIONS || value.count !== value.conversations.length || (value.next_cursor !== null && (typeof value.next_cursor !== "string" || !/^[A-Za-z0-9_-]{1,256}$/u.test(value.next_cursor)))) throw new PublicConversationError("response_invalid");
  if (!value.agents.every(validAgent) || !value.conversations.every(validConversation)) throw new PublicConversationError("response_invalid");
  const agentIds = new Set(value.agents.map((item) => (item as PublicConversationAgent).id));
  if (agentIds.size !== value.agents.length || new Set(value.conversations.map((item) => (item as PublicConversation).id)).size !== value.conversations.length || value.conversations.some((item) => !agentIds.has((item as PublicConversation).agent_id)) || (value.direct_agent_id !== null && (!id(value.direct_agent_id, OPAQUE_ID) || !value.agents.some((item) => (item as PublicConversationAgent).id === value.direct_agent_id && (item as PublicConversationAgent).system_role === "direct")))) throw new PublicConversationError("response_invalid");
  return value as PublicConversationList;
}

function parseDetail(value: unknown): PublicConversationDetail {
  if (!record(value) || !keys(value, "agent,conversation,current_run,messages,next_message_cursor,queued_turns,runtime,schema_version,service,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready") throw new PublicConversationError("response_invalid");
  const conversation = value.conversation;
  const agent = value.agent;
  const messages = value.messages;
  const queuedTurns = value.queued_turns;
  if (!validConversation(conversation) || !validAgent(agent) || conversation.agent_id !== agent.id || !Array.isArray(messages) || messages.length > MAXIMUM_MESSAGES || !messages.every(validMessage) || !Array.isArray(queuedTurns) || queuedTurns.length > MAXIMUM_QUEUED_TURNS || !queuedTurns.every(validQueuedTurn) || value.next_message_cursor !== null && (typeof value.next_message_cursor !== "string" || !/^[1-9][0-9]{0,9}$/u.test(value.next_message_cursor)) || !validCurrentRun(value.current_run)) throw new PublicConversationError("response_invalid");
  const publicConversation = conversation as PublicConversation;
  const publicMessages = messages as Array<Record<string, unknown>>;
  if (publicMessages.some((item) => item.conversation_id !== publicConversation.id) || publicMessages.some((item, index, all) => index > 0 && Number(all[index - 1].sequence) >= Number(item.sequence))) throw new PublicConversationError("response_invalid");
  const publicQueuedTurns = queuedTurns as Array<Record<string, unknown>>;
  if (publicQueuedTurns.some((item) => item.conversation_id !== publicConversation.id) || publicQueuedTurns.some((item, index, all) => index > 0 && Number(all[index - 1].queue_ordinal) >= Number(item.queue_ordinal)) || new Set(publicQueuedTurns.map((item) => item.id)).size !== publicQueuedTurns.length || new Set(publicQueuedTurns.map((item) => item.user_message_id)).size !== publicQueuedTurns.length) throw new PublicConversationError("response_invalid");
  return value as PublicConversationDetail;
}

function parseActivity(value: unknown): PublicActivityPayload {
  if (!record(value) || !keys(value, "activity,direct_agent_id,runtime,schema_version,service,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || !Array.isArray(value.activity) || value.activity.length > MAXIMUM_AGENTS || !value.activity.every(validActivityItem) || new Set(value.activity.map((item) => (item as PublicActivityPayload["activity"][number]).agent.id)).size !== value.activity.length || (value.direct_agent_id !== null && (!id(value.direct_agent_id, OPAQUE_ID) || !value.activity.some((item) => { const agent = (item as PublicActivityPayload["activity"][number]).agent; return agent.id === value.direct_agent_id && agent.system_role === "direct"; })))) throw new PublicConversationError("response_invalid");
  return value as PublicActivityPayload;
}

function parseTurnSubmission(value: unknown): PublicConversationTurnSubmission {
  if (!record(value) || !keys(value, "conversation,disposition,duplicate,message,run,runtime,schema_version,service,status,turn") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || typeof value.duplicate !== "boolean" || !["pending", "blocked", "reserved", "submitting", "accepted", "rejected", "unknown"].includes(String(value.disposition))) throw new PublicConversationError("response_invalid");
  if (!validConversation(value.conversation) || !validMessage(value.message) || !validTurn(value.turn) || !validCurrentRun(value.run)) throw new PublicConversationError("response_invalid");
  const conversation = value.conversation as PublicConversation;
  const message = value.message as Record<string, unknown>;
  const turn = value.turn as PublicConversationTurn;
  const run = value.run as Record<string, unknown> | null;
  if (message.conversation_id !== conversation.id || turn.conversation_id !== conversation.id || turn.user_message_id !== message.id || message.run_id !== turn.latest_run_id || run !== null && run.id !== turn.latest_run_id) throw new PublicConversationError("response_invalid");
  return value as PublicConversationTurnSubmission;
}

function parseQueueMutation(value: unknown): PublicConversationQueueMutation {
  if (!record(value) || !keys(value, "conversation,disposition,message,runtime,schema_version,service,status,turn") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || !["edited", "cancelled"].includes(String(value.disposition)) || !validConversation(value.conversation) || !validMessage(value.message) || !validTurn(value.turn)) throw new PublicConversationError("response_invalid");
  const conversation = value.conversation as PublicConversation;
  const message = value.message as Record<string, unknown>;
  const turn = value.turn as PublicConversationTurn;
  if (message.conversation_id !== conversation.id || turn.conversation_id !== conversation.id || turn.user_message_id !== message.id || message.run_id !== turn.latest_run_id || value.disposition === "edited" && (!(turn.state === "pending" || turn.state === "blocked") || message.state !== "accepted") || value.disposition === "cancelled" && (turn.state !== "cancelled" || message.state !== "cancelled")) throw new PublicConversationError("response_invalid");
  return value as PublicConversationQueueMutation;
}

function parseArchiveResult(value: unknown): PublicConversationArchiveResult {
  if (!record(value) || !keys(value, "action,conversation,runtime,schema_version,service,status")) throw new PublicConversationError("response_invalid");
  if (
    (value.action !== "archive" && value.action !== "restore")
    || !validConversation(value.conversation)
    || value.runtime !== "python"
    || value.schema_version !== 1
    || value.service !== "mentat-local-bridge"
    || value.status !== "ready"
  ) throw new PublicConversationError("response_invalid");
  const conversation = value.conversation as PublicConversation;
  if (
    value.action === "archive" && conversation.state !== "archived"
    || value.action === "restore" && conversation.state !== "active"
  ) throw new PublicConversationError("response_invalid");
  return structuredClone(value) as PublicConversationArchiveResult;
}

function parseRunAttemptResult(value: unknown): PublicConversationRunAttemptResult {
  if (!record(value) || !keys(value, "action,conversation_id,duplicate,run,runtime,schema_version,service,source_run_id,status")) throw new PublicConversationError("response_invalid");
  if (
    value.schema_version !== 1
    || value.service !== "mentat-local-bridge"
    || value.runtime !== "python"
    || value.status !== "ready"
    || (value.action !== "retry" && value.action !== "resume")
    || !CONVERSATION_ID.test(String(value.conversation_id))
    || !RUN_ID.test(String(value.source_run_id))
    || typeof value.duplicate !== "boolean"
    || !validCurrentRun(value.run)
    || (value.run as PublicCurrentRun).id === value.source_run_id
  ) throw new PublicConversationError("response_invalid");
  return structuredClone(value) as PublicConversationRunAttemptResult;
}

function parseSteer(value: unknown): PublicConversationSteerResult {
  if (!record(value) || !keys(value, "action,conversation_id,disposition,run_id,runtime,schema_version,service,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || value.action !== "steer" || !id(value.conversation_id, CONVERSATION_ID) || !id(value.run_id, RUN_ID) || value.disposition !== "accepted") throw new PublicConversationError("response_invalid");
  return value as PublicConversationSteerResult;
}

function parseCodexReadiness(value: unknown): PublicCodexReadiness {
  if (!record(value) || !keys(value, "runtime,schema_version,service,setup_command,state,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || !["cli_missing", "sign_in_required", "ready", "unavailable"].includes(String(value.state)) || value.setup_command !== null && value.setup_command !== "codex login" || (value.state === "sign_in_required") !== (value.setup_command === "codex login")) throw new PublicConversationError("response_invalid");
  return value as PublicCodexReadiness;
}

async function boundedJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_RESPONSE_BYTES)) throw new PublicConversationError("response_invalid");
  if (!response.body) throw new PublicConversationError("response_invalid");
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
        throw new PublicConversationError("response_invalid");
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
    throw new PublicConversationError("response_invalid");
  }
}

async function request(path: string, init: RequestInit = {}, timeoutMilliseconds = READ_TIMEOUT_MILLISECONDS): Promise<{ response: Response; payload: unknown }> {
  try {
    const response = await fetch(path, { ...init, cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json", ...init.headers }, redirect: "error", signal: AbortSignal.timeout(timeoutMilliseconds) });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new PublicConversationError("response_invalid");
    return { response, payload: await boundedJson(response) };
  } catch (error) {
    if (error instanceof PublicConversationError) throw error;
    throw new PublicConversationError("unavailable");
  }
}

function fixed(response: Response, payload: unknown): never {
  const status = record(payload) ? payload.status : undefined;
  if (response.status === 400 && status === "invalid") throw new PublicConversationError("invalid");
  if (response.status === 501 && status === "unsupported") throw new PublicConversationError("unsupported");
  if (response.status === 503 && status === "unavailable") throw new PublicConversationError("unavailable");
  if (response.status === 404 && status === "not_found") throw new PublicConversationError("not_found");
  if (response.status === 409 && status === "active_run") throw new PublicConversationError("active_run");
  if (response.status === 409 && status === "capacity_unavailable") throw new PublicConversationError("capacity_unavailable");
  if (response.status === 409 && status === "idempotency_conflict") throw new PublicConversationError("idempotency_conflict");
  if (response.status === 409 && status === "conflict") throw new PublicConversationError("conflict");
  if (response.status === 409 && status === "cli_missing") throw new PublicConversationError("cli_missing");
  if (response.status === 409 && status === "sign_in_required") throw new PublicConversationError("sign_in_required");
  if (response.status === 500 && status === "partial") throw new PublicConversationError("partial");
  throw new PublicConversationError("response_invalid");
}

export async function fetchConversations(cursor: string | null = null): Promise<PublicConversationList> {
  if (cursor !== null && !/^[A-Za-z0-9_-]{1,256}$/u.test(cursor)) throw new PublicConversationError("cursor_invalid");
  const { response, payload } = await request(`${"/api/conversations"}${cursor === null ? "" : `?cursor=${encodeURIComponent(cursor)}`}`);
  if (response.status === 200) return parseList(payload);
  fixed(response, payload);
}

export async function fetchConversationHistory(
  state: "all" | "active" | "archived",
  query: string | null = null,
  cursor: string | null = null,
): Promise<PublicConversationHistory> {
  if (
    !["all", "active", "archived"].includes(state)
    || query !== null && (!boundedText(query, 160) || /\p{C}/u.test(query))
    || cursor !== null && !/^[A-Za-z0-9_-]{1,512}$/u.test(cursor)
  ) throw new PublicConversationError("invalid");
  const parameters = new URLSearchParams({ state });
  if (query !== null) parameters.set("q", query);
  if (cursor !== null) parameters.set("cursor", cursor);
  const { response, payload } = await request(`/api/conversation-history?${parameters.toString()}`);
  if (response.status === 200) {
    const history = parseHistory(payload);
    if (!historyMatchesStateAndOrder(history, state)) {
      throw new PublicConversationError("response_invalid");
    }
    return history;
  }
  fixed(response, payload);
}

export async function fetchConversation(id: string, before: string | null = null): Promise<PublicConversationDetail> {
  if (!CONVERSATION_ID.test(id) || before !== null && !/^[1-9][0-9]{0,9}$/u.test(before)) throw new PublicConversationError("request_invalid");
  const { response, payload } = await request(`/api/conversations/${encodeURIComponent(id)}${before === null ? "" : `?before=${before}`}`);
  if (response.status === 200) {
    const parsed = parseDetail(payload);
    if (parsed.conversation.id !== id) throw new PublicConversationError("response_invalid");
    return parsed;
  }
  fixed(response, payload);
}

export async function createConversation(agentId: string | null): Promise<PublicConversationDetail> {
  if (agentId !== null && !OPAQUE_ID.test(agentId)) throw new PublicConversationError("agent_id_invalid");
  const { response, payload } = await request("/api/conversations", { body: JSON.stringify(agentId === null ? {} : { agent_id: agentId }), headers: { "Content-Type": "application/json" }, method: "POST" });
  if (response.status === 201) {
    const parsed = parseDetail(payload);
    if (agentId !== null && parsed.agent.id !== agentId) throw new PublicConversationError("response_invalid");
    return parsed;
  }
  fixed(response, payload);
}

export async function archiveConversation(
  conversationId: string,
  expectedRevision: number,
  archived: boolean,
): Promise<PublicConversationArchiveResult> {
  if (!CONVERSATION_ID.test(conversationId) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1) throw new PublicConversationError("invalid");
  const action = archived ? "archive" : "restore";
  const { response, payload } = await request(
    `/api/conversations/${encodeURIComponent(conversationId)}/${action}`,
    {
      body: JSON.stringify({ expected_revision: expectedRevision }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
  );
  if (response.status === 200) {
    const parsed = parseArchiveResult(payload);
    if (parsed.conversation.id !== conversationId || parsed.action !== action) throw new PublicConversationError("response_invalid");
    return parsed;
  }
  fixed(response, payload);
}

export async function renameConversation(
  conversationId: string,
  expectedRevision: number,
  title: string,
): Promise<PublicConversationRenameResult> {
  if (
    !CONVERSATION_ID.test(conversationId)
    || !Number.isSafeInteger(expectedRevision)
    || expectedRevision < 1
    || !boundedText(title, 160)
    || /\p{C}/u.test(title)
  ) throw new PublicConversationError("invalid");
  const { response, payload } = await request(
    `/api/conversations/${encodeURIComponent(conversationId)}/rename`,
    {
      body: JSON.stringify({ expected_revision: expectedRevision, title }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
  );
  if (response.status === 200) {
    const parsed = parseRenameResult(payload);
    if (parsed.conversation.id !== conversationId || parsed.conversation.title !== title) {
      throw new PublicConversationError("response_invalid");
    }
    return parsed;
  }
  fixed(response, payload);
}

async function conversationRunAttempt(
  action: "retry" | "resume",
  conversationId: string,
  sourceRunId: string,
  idempotencyKey: string,
): Promise<PublicConversationRunAttemptResult> {
  const keyBytes = new TextEncoder().encode(idempotencyKey).byteLength;
  if (!CONVERSATION_ID.test(conversationId) || !RUN_ID.test(sourceRunId) || keyBytes < 16 || keyBytes > 256 || idempotencyKey.includes("\0")) throw new PublicConversationError("invalid");
  const { response, payload } = await request(
    `/api/conversations/${encodeURIComponent(conversationId)}/${action}`,
    {
      body: JSON.stringify({ idempotency_key: idempotencyKey, source_run_id: sourceRunId }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    CONVERSATION_TURN_PUBLIC_TIMEOUT_MILLISECONDS,
  );
  if (response.status === 200 || response.status === 202) {
    const parsed = parseRunAttemptResult(payload);
    if (parsed.conversation_id !== conversationId || parsed.source_run_id !== sourceRunId || parsed.action !== action) throw new PublicConversationError("response_invalid");
    return parsed;
  }
  fixed(response, payload);
}

export function retryConversationRun(
  conversationId: string,
  sourceRunId: string,
  idempotencyKey: string,
): Promise<PublicConversationRunAttemptResult> {
  return conversationRunAttempt("retry", conversationId, sourceRunId, idempotencyKey);
}

export function resumeConversationRun(
  conversationId: string,
  sourceRunId: string,
  idempotencyKey: string,
): Promise<PublicConversationRunAttemptResult> {
  return conversationRunAttempt("resume", conversationId, sourceRunId, idempotencyKey);
}

export async function submitConversationTurn(
  conversationId: string,
  text: string,
  idempotencyKey: string,
): Promise<PublicConversationTurnSubmission> {
  const keyBytes = new TextEncoder().encode(idempotencyKey).byteLength;
  if (!CONVERSATION_ID.test(conversationId) || !text.trim() || text.trim() !== text || Array.from(text).length > 6_000 || text.includes("\0") || keyBytes < 16 || keyBytes > 256 || idempotencyKey.includes("\0")) throw new PublicConversationError("invalid");
  const { response, payload } = await request(`/api/conversations/${encodeURIComponent(conversationId)}/turns`, {
    body: JSON.stringify({ idempotency_key: idempotencyKey, text }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  }, CONVERSATION_TURN_PUBLIC_TIMEOUT_MILLISECONDS);
  if (response.status === 200 || response.status === 202) {
    const parsed = parseTurnSubmission(payload);
    if (parsed.conversation.id !== conversationId || parsed.message.content.parts[0].text !== text) throw new PublicConversationError("response_invalid");
    return parsed;
  }
  fixed(response, payload);
}

async function mutateConversationTurn(
  conversationId: string,
  turnId: string,
  action: "edit" | "cancel" | "continue",
  expectedRevision: number,
  expectedMessageRevision: number,
  text: string | null,
): Promise<PublicConversationQueueMutation | PublicConversationTurnSubmission> {
  if (!CONVERSATION_ID.test(conversationId) || !TURN_ID.test(turnId) || !Number.isInteger(expectedRevision) || expectedRevision < 1 || !Number.isInteger(expectedMessageRevision) || expectedMessageRevision < 1 || action === "edit" && (text === null || !boundedText(text, 6_000)) || action !== "edit" && text !== null) throw new PublicConversationError("invalid");
  const body = action === "edit"
    ? { expected_message_revision: expectedMessageRevision, expected_revision: expectedRevision, text }
    : { expected_message_revision: expectedMessageRevision, expected_revision: expectedRevision };
  const { response, payload } = await request(`/api/conversations/${encodeURIComponent(conversationId)}/turns/${encodeURIComponent(turnId)}/${action}`, {
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  }, action === "continue" ? CONVERSATION_TURN_PUBLIC_TIMEOUT_MILLISECONDS : READ_TIMEOUT_MILLISECONDS);
  if (action === "continue" && (response.status === 200 || response.status === 202)) {
    const parsed = parseTurnSubmission(payload);
    if (parsed.conversation.id !== conversationId || parsed.turn.id !== turnId) throw new PublicConversationError("response_invalid");
    return parsed;
  }
  if (action !== "continue" && response.status === 200) {
    const parsed = parseQueueMutation(payload);
    if (parsed.conversation.id !== conversationId || parsed.turn.id !== turnId || action === "edit" && parsed.message.content.parts[0].text !== text) throw new PublicConversationError("response_invalid");
    return parsed;
  }
  fixed(response, payload);
}

export function editConversationTurn(conversationId: string, turnId: string, expectedRevision: number, expectedMessageRevision: number, text: string): Promise<PublicConversationQueueMutation> {
  return mutateConversationTurn(conversationId, turnId, "edit", expectedRevision, expectedMessageRevision, text) as Promise<PublicConversationQueueMutation>;
}

export function cancelConversationTurn(conversationId: string, turnId: string, expectedRevision: number, expectedMessageRevision: number): Promise<PublicConversationQueueMutation> {
  return mutateConversationTurn(conversationId, turnId, "cancel", expectedRevision, expectedMessageRevision, null) as Promise<PublicConversationQueueMutation>;
}

export function continueConversationTurn(conversationId: string, turnId: string, expectedRevision: number, expectedMessageRevision: number): Promise<PublicConversationTurnSubmission> {
  return mutateConversationTurn(conversationId, turnId, "continue", expectedRevision, expectedMessageRevision, null) as Promise<PublicConversationTurnSubmission>;
}

export async function steerConversation(conversationId: string, runId: string, text: string): Promise<PublicConversationSteerResult> {
  if (!CONVERSATION_ID.test(conversationId) || !RUN_ID.test(runId) || !boundedText(text, 6_000)) throw new PublicConversationError("invalid");
  const { response, payload } = await request(`/api/conversations/${encodeURIComponent(conversationId)}/steer`, {
    body: JSON.stringify({ run_id: runId, text }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  }, CONVERSATION_TURN_PUBLIC_TIMEOUT_MILLISECONDS);
  if (response.status === 200) {
    const parsed = parseSteer(payload);
    if (parsed.conversation_id !== conversationId || parsed.run_id !== runId) throw new PublicConversationError("response_invalid");
    return parsed;
  }
  fixed(response, payload);
}

export async function fetchCodexReadiness(): Promise<PublicCodexReadiness> {
  const { response, payload } = await request(
    "/api/codex-readiness",
    {},
    CODEX_READINESS_PUBLIC_TIMEOUT_MILLISECONDS,
  );
  if (response.status === 200) return parseCodexReadiness(payload);
  fixed(response, payload);
}

export async function fetchActivity(): Promise<PublicActivityPayload> {
  const { response, payload } = await request("/api/agent-activity");
  if (response.status === 200) return parseActivity(payload);
  fixed(response, payload);
}
