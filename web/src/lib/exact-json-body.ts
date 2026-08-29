const BODY_READ_TIMEOUT_MILLISECONDS = 2_000;
const CONVERSATION_TURN_BODY_BYTES = 96 * 1024;

async function readBoundedBytes(
  request: Request,
  maximumBytes: number,
  timeoutMilliseconds = BODY_READ_TIMEOUT_MILLISECONDS,
): Promise<Uint8Array | null> {
  if (
    request.headers.get("content-type")?.toLowerCase() !== "application/json"
    || !request.body
    || !Number.isInteger(timeoutMilliseconds)
    || timeoutMilliseconds < 1
  ) return null;
  const reader = request.body.getReader();
  const parts: Uint8Array[] = [];
  let size = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error("body_read_timeout")), timeoutMilliseconds);
  });
  try {
    for (;;) {
      const next = await Promise.race([reader.read(), deadline]);
      if (next.done) break;
      size += next.value.byteLength;
      if (size > maximumBytes) {
        void reader.cancel().catch(() => undefined);
        return null;
      }
      parts.push(next.value);
    }
  } catch {
    void reader.cancel().catch(() => undefined);
    return null;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
  const value = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) { value.set(part, offset); offset += part.byteLength; }
  return value;
}

function strictUtf8(value: Uint8Array): string | null {
  try { return new TextDecoder("utf-8", { fatal: true }).decode(value); } catch { return null; }
}

/** Read at most two bytes and accept only the fixed preview body. */
export async function hasExactEmptyJsonBody(request: Request): Promise<boolean> {
  const value = await readBoundedBytes(request, 2);
  return value !== null && strictUtf8(value) === "{}";
}

/** Return one fixed confirmation value without buffering an arbitrary body. */
export async function readConfirmationId(request: Request): Promise<string | null> {
  const value = await readBoundedBytes(request, 128);
  if (value === null) return null;
  const decoded = strictUtf8(value);
  if (decoded === null) return null;
  let body: unknown;
  try { body = JSON.parse(decoded); } catch { return null; }
  if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).join(",") !== "confirmation_id") return null;
  const confirmationId = (body as Record<string, unknown>).confirmation_id;
  return typeof confirmationId === "string" && /^[0-9a-f]{64}$/u.test(confirmationId) ? confirmationId : null;
}

async function readBoundedJson(
  request: Request,
  maximumBytes: number,
  timeoutMilliseconds = BODY_READ_TIMEOUT_MILLISECONDS,
): Promise<unknown | null> {
  const value = await readBoundedBytes(request, maximumBytes, timeoutMilliseconds);
  if (value === null) return null;
  const decoded = strictUtf8(value);
  if (decoded === null) return null;
  try { return JSON.parse(decoded); } catch { return null; }
}

const CONVERSATION_AGENT_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u;

export async function readConversationCreateBody(
  request: Request,
): Promise<{ agentId: string | null } | null> {
  const body = await readBoundedJson(request, 512);
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const keys = Object.keys(body);
  if (keys.length === 0) return { agentId: null };
  if (keys.length !== 1 || keys[0] !== "agent_id") return null;
  const agentId = (body as Record<string, unknown>).agent_id;
  return agentId === null || typeof agentId === "string" && CONVERSATION_AGENT_ID.test(agentId)
    ? { agentId }
    : null;
}

export async function readExpectedRevisionBody(
  request: Request,
): Promise<{ expectedRevision: number } | null> {
  const body = await readBoundedJson(request, 512);
  if (
    !body
    || typeof body !== "object"
    || Array.isArray(body)
    || Object.keys(body).join(",") !== "expected_revision"
  ) return null;
  const revision = (body as Record<string, unknown>).expected_revision;
  return Number.isSafeInteger(revision) && (revision as number) >= 1
    ? { expectedRevision: revision as number }
    : null;
}

export async function readAgentConfigurationBody(
  request: Request,
  preview: boolean,
): Promise<{ confirmationId: string | null; provider: string; model: string } | null> {
  const body = await readBoundedJson(request, 768);
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const expected = preview ? "model,provider" : "confirmation_id,model,provider";
  if (Object.keys(body).sort().join(",") !== expected) return null;
  const value = body as Record<string, unknown>;
  if (
    typeof value.provider !== "string" || !value.provider
    || value.provider.trim() !== value.provider || value.provider.length > 120
    || value.provider.includes("\0")
    || typeof value.model !== "string" || !value.model
    || value.model.trim() !== value.model || value.model.length > 160
    || value.model.includes("\0")
    || !preview && (
      typeof value.confirmation_id !== "string"
      || !/^provider_switch_[0-9a-f]{24}$/u.test(value.confirmation_id)
    )
  ) return null;
  return {
    confirmationId: preview ? null : value.confirmation_id as string,
    provider: value.provider,
    model: value.model,
  };
}

export async function readConversationTurnBody(
  request: Request,
  timeoutMilliseconds = BODY_READ_TIMEOUT_MILLISECONDS,
): Promise<{ idempotencyKey: string; text: string } | null> {
  const body = await readBoundedJson(
    request,
    CONVERSATION_TURN_BODY_BYTES,
    timeoutMilliseconds,
  );
  if (
    !body
    || typeof body !== "object"
    || Array.isArray(body)
    || Object.keys(body).sort().join(",") !== "idempotency_key,text"
  ) return null;
  const value = body as Record<string, unknown>;
  const text = value.text;
  const idempotencyKey = value.idempotency_key;
  if (
    typeof text !== "string"
    || !text.trim()
    || text.trim() !== text
    || Array.from(text).length > 6_000
    || text.includes("\0")
    || typeof idempotencyKey !== "string"
    || idempotencyKey.includes("\0")
  ) return null;
  const keyBytes = new TextEncoder().encode(idempotencyKey).byteLength;
  return 16 <= keyBytes && keyBytes <= 256 ? { idempotencyKey, text } : null;
}

export async function readConversationRunAttemptBody(
  request: Request,
): Promise<{ idempotencyKey: string; sourceRunId: string } | null> {
  const body = await readBoundedJson(request, CONVERSATION_TURN_BODY_BYTES);
  if (
    !body
    || typeof body !== "object"
    || Array.isArray(body)
    || Object.keys(body).sort().join(",") !== "idempotency_key,source_run_id"
  ) return null;
  const value = body as Record<string, unknown>;
  if (
    typeof value.idempotency_key !== "string"
    || value.idempotency_key.includes("\0")
    || typeof value.source_run_id !== "string"
    || !/^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/u.test(value.source_run_id)
  ) return null;
  const keyBytes = new TextEncoder().encode(value.idempotency_key).byteLength;
  return 16 <= keyBytes && keyBytes <= 256
    ? { idempotencyKey: value.idempotency_key, sourceRunId: value.source_run_id }
    : null;
}

export async function readConversationQueueActionBody(
  request: Request,
  action: "edit" | "cancel" | "continue",
): Promise<{
  expectedRevision: number;
  expectedMessageRevision: number;
  text: string | null;
} | null> {
  const body = await readBoundedJson(request, CONVERSATION_TURN_BODY_BYTES);
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const expectedKeys = action === "edit"
    ? "expected_message_revision,expected_revision,text"
    : "expected_message_revision,expected_revision";
  if (Object.keys(body).sort().join(",") !== expectedKeys) return null;
  const value = body as Record<string, unknown>;
  if (
    !Number.isInteger(value.expected_revision)
    || (value.expected_revision as number) < 1
    || !Number.isInteger(value.expected_message_revision)
    || (value.expected_message_revision as number) < 1
  ) return null;
  if (action === "edit") {
    if (
      typeof value.text !== "string"
      || !value.text
      || value.text.trim() !== value.text
      || Array.from(value.text).length > 6_000
      || value.text.includes("\0")
    ) return null;
  }
  return {
    expectedMessageRevision: value.expected_message_revision as number,
    expectedRevision: value.expected_revision as number,
    text: action === "edit" ? value.text as string : null,
  };
}

export async function readConversationSteerBody(
  request: Request,
): Promise<{ runId: string; text: string } | null> {
  const body = await readBoundedJson(request, CONVERSATION_TURN_BODY_BYTES);
  if (
    !body
    || typeof body !== "object"
    || Array.isArray(body)
    || Object.keys(body).sort().join(",") !== "run_id,text"
  ) return null;
  const value = body as Record<string, unknown>;
  return typeof value.run_id === "string"
    && /^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/u.test(value.run_id)
    && typeof value.text === "string"
    && !!value.text
    && value.text.trim() === value.text
    && Array.from(value.text).length <= 6_000
    && !value.text.includes("\0")
    ? { runId: value.run_id, text: value.text }
    : null;
}

const RUN_MESSAGE_TEXT_LIMIT = 6_000;
const withinRunMessageTextLimit = (text: string) => Array.from(text).length <= RUN_MESSAGE_TEXT_LIMIT;
const RUN_RESPONSE_TEXT_LIMIT = 2_000;

export async function readMessagePreview(request: Request): Promise<string | null> {
  const body = await readBoundedJson(request, 24_576);
  if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).join(",") !== "text") return null;
  const text = (body as Record<string, unknown>).text;
  return typeof text === "string" && text.trim() && withinRunMessageTextLimit(text) && !text.includes("\0") ? text : null;
}

export async function readMessageConfirmation(request: Request): Promise<{ text: string; confirmationId: string } | null> {
  const body = await readBoundedJson(request, 24_576);
  if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).sort().join(",") !== "confirmation_id,text") return null;
  const text = (body as Record<string, unknown>).text;
  const confirmationId = (body as Record<string, unknown>).confirmation_id;
  return typeof text === "string" && text.trim() && withinRunMessageTextLimit(text) && !text.includes("\0") && typeof confirmationId === "string" && /^[0-9a-f]{64}$/u.test(confirmationId) ? { text, confirmationId } : null;
}

type RunResponse =
  | { kind: "approval"; choice: "once" | "deny" }
  | { kind: "clarification"; choice: string }
  | { kind: "clarification"; text: string };

function readRunResponse(value: unknown): RunResponse | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (Object.keys(item).sort().join(",") === "choice,kind") {
    if (item.kind === "approval" && (item.choice === "once" || item.choice === "deny")) return { kind: "approval", choice: item.choice };
    if (item.kind === "clarification" && typeof item.choice === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(item.choice)) return { kind: "clarification", choice: item.choice };
    return null;
  }
  return Object.keys(item).sort().join(",") === "kind,text" && item.kind === "clarification"
    && typeof item.text === "string" && !!item.text.trim() && !item.text.includes("\0")
    && Array.from(item.text).length <= RUN_RESPONSE_TEXT_LIMIT
    ? { kind: "clarification", text: item.text }
    : null;
}

export async function readRunResponseRequest(request: Request): Promise<boolean> {
  return hasExactEmptyJsonBody(request);
}

export async function readRunResponsePreview(request: Request): Promise<RunResponse | null> {
  const body = await readBoundedJson(request, 24_576);
  if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).join(",") !== "response") return null;
  return readRunResponse((body as Record<string, unknown>).response);
}

export async function readRunResponseConfirmation(request: Request): Promise<{ response: RunResponse; confirmationId: string } | null> {
  const body = await readBoundedJson(request, 24_576);
  if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).sort().join(",") !== "confirmation_id,response") return null;
  const confirmationId = (body as Record<string, unknown>).confirmation_id;
  const response = readRunResponse((body as Record<string, unknown>).response);
  return response && typeof confirmationId === "string" && /^[0-9a-f]{64}$/u.test(confirmationId) ? { response, confirmationId } : null;
}

/** Read the two fixed response-route bodies without consuming a Request twice. */
export async function readRunResponseRouteBody(request: Request): Promise<"request" | { response: RunResponse; confirmationId: string } | null> {
  const body = await readBoundedJson(request, 24_576);
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  if (Object.keys(body).length === 0) return "request";
  if (Object.keys(body).sort().join(",") !== "confirmation_id,response") return null;
  const confirmationId = (body as Record<string, unknown>).confirmation_id;
  const response = readRunResponse((body as Record<string, unknown>).response);
  return response && typeof confirmationId === "string" && /^[0-9a-f]{64}$/u.test(confirmationId)
    ? { response, confirmationId }
    : null;
}
