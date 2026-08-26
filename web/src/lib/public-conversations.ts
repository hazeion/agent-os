import type {
  PublicActivityPayload,
  PublicConversation,
  PublicConversationAgent,
  PublicConversationDetail,
  PublicConversationList,
} from "./bridge-conversations";

const MAXIMUM_RESPONSE_BYTES = 3_000_000;
const MAXIMUM_MESSAGES = 100;
const MAXIMUM_CONVERSATIONS = 50;
const MAXIMUM_AGENTS = 128;

export class PublicConversationError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.code = code;
    this.name = "PublicConversationError";
  }
}

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
    && (value.title_source === "default" || value.title_source === "first_prompt")
    && (value.state === "active" || value.state === "archived")
    && Number.isInteger(value.revision) && (value.revision as number) >= 1
    && timestamp(value.created_at) && timestamp(value.updated_at)
    && (value.archived_at === null || timestamp(value.archived_at))
    && (value.state === "active" ? value.archived_at === null : value.archived_at !== null);
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
  if (!record(value) || !keys(value, "id,partial,status,updated_at")) return false;
  return id(value.id, RUN_ID)
    && typeof value.status === "string"
    && ["reserved", "queued", "submitting", "starting", "running", "cancelling", "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown", "completed", "failed", "cancelled", "stopped", "interrupted"].includes(value.status)
    && typeof value.partial === "boolean"
    && timestamp(value.updated_at);
}

function validActivityItem(value: unknown): boolean {
  if (!record(value) || !keys(value, "agent,attention,conversations,state,summary,updated_at")) return false;
  const conversations = value.conversations;
  return validAgent(value.agent)
    && ["working", "waiting", "failed", "stopped", "interrupted", "idle"].includes(value.state as string)
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
        && ["reserved", "queued", "submitting", "starting", "running", "cancelling", "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown", "completed", "failed", "cancelled", "stopped", "interrupted"].includes(conversation.run_status)
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
  if (!record(value) || !keys(value, "agent,conversation,current_run,messages,next_message_cursor,runtime,schema_version,service,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready") throw new PublicConversationError("response_invalid");
  const conversation = value.conversation;
  const agent = value.agent;
  const messages = value.messages;
  if (!validConversation(conversation) || !validAgent(agent) || conversation.agent_id !== agent.id || !Array.isArray(messages) || messages.length > MAXIMUM_MESSAGES || !messages.every(validMessage) || value.next_message_cursor !== null && (typeof value.next_message_cursor !== "string" || !/^[1-9][0-9]{0,9}$/u.test(value.next_message_cursor)) || !validCurrentRun(value.current_run)) throw new PublicConversationError("response_invalid");
  const publicConversation = conversation as PublicConversation;
  const publicMessages = messages as Array<Record<string, unknown>>;
  if (publicMessages.some((item) => item.conversation_id !== publicConversation.id) || publicMessages.some((item, index, all) => index > 0 && Number(all[index - 1].sequence) >= Number(item.sequence))) throw new PublicConversationError("response_invalid");
  return value as PublicConversationDetail;
}

function parseActivity(value: unknown): PublicActivityPayload {
  if (!record(value) || !keys(value, "activity,direct_agent_id,runtime,schema_version,service,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || !Array.isArray(value.activity) || value.activity.length > MAXIMUM_AGENTS || !value.activity.every(validActivityItem) || new Set(value.activity.map((item) => (item as PublicActivityPayload["activity"][number]).agent.id)).size !== value.activity.length || (value.direct_agent_id !== null && (!id(value.direct_agent_id, OPAQUE_ID) || !value.activity.some((item) => { const agent = (item as PublicActivityPayload["activity"][number]).agent; return agent.id === value.direct_agent_id && agent.system_role === "direct"; })))) throw new PublicConversationError("response_invalid");
  return value as PublicActivityPayload;
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

async function request(path: string, init: RequestInit = {}): Promise<{ response: Response; payload: unknown }> {
  try {
    const response = await fetch(path, { ...init, cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json", ...init.headers }, redirect: "error", signal: AbortSignal.timeout(1500) });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new PublicConversationError("response_invalid");
    return { response, payload: await boundedJson(response) };
  } catch (error) {
    if (error instanceof PublicConversationError) throw error;
    throw new PublicConversationError("unavailable");
  }
}

function fixed(response: Response, payload: unknown): never {
  const status = record(payload) ? payload.status : undefined;
  if (response.status === 501 && status === "unsupported") throw new PublicConversationError("unsupported");
  if (response.status === 503 && status === "unavailable") throw new PublicConversationError("unavailable");
  if (response.status === 404 && status === "not_found") throw new PublicConversationError("not_found");
  throw new PublicConversationError("response_invalid");
}

export async function fetchConversations(cursor: string | null = null): Promise<PublicConversationList> {
  if (cursor !== null && !/^[A-Za-z0-9_-]{1,256}$/u.test(cursor)) throw new PublicConversationError("cursor_invalid");
  const { response, payload } = await request(`${"/api/conversations"}${cursor === null ? "" : `?cursor=${encodeURIComponent(cursor)}`}`);
  if (response.status === 200) return parseList(payload);
  fixed(response, payload);
}

export async function fetchConversation(id: string, before: string | null = null): Promise<PublicConversationDetail> {
  if (!CONVERSATION_ID.test(id) || before !== null && !/^[1-9][0-9]{0,9}$/u.test(before)) throw new PublicConversationError("request_invalid");
  const { response, payload } = await request(`/api/conversations/${encodeURIComponent(id)}${before === null ? "" : `?before=${before}`}`);
  if (response.status === 200) return parseDetail(payload);
  fixed(response, payload);
}

export async function createConversation(agentId: string | null): Promise<PublicConversationDetail> {
  if (agentId !== null && !OPAQUE_ID.test(agentId)) throw new PublicConversationError("agent_id_invalid");
  const { response, payload } = await request("/api/conversations", { body: JSON.stringify(agentId === null ? {} : { agent_id: agentId }), headers: { "Content-Type": "application/json" }, method: "POST" });
  if (response.status === 201) return parseDetail(payload);
  fixed(response, payload);
}

export async function fetchActivity(): Promise<PublicActivityPayload> {
  const { response, payload } = await request("/api/agent-activity");
  if (response.status === 200) return parseActivity(payload);
  fixed(response, payload);
}
