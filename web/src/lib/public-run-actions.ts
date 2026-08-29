import type {
  PendingRunRequest,
  RunActionResponse,
} from "./bridge-run-response.ts";

const RUN_ID = /^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/u;
const CONFIRMATION_ID = /^[0-9a-f]{64}$/u;
const MAXIMUM_BYTES = 24_576;

export class PublicRunActionError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.code = code; this.name = "PublicRunActionError"; }
}

export type PublicRunActionPreview = {
  action: "respond";
  confirmation_id: string;
  request: PendingRunRequest;
  requires_confirmation: true;
  run_id: string;
  runtime: "python";
  schema_version: 1;
  service: "mentat-local-bridge";
  status: "ready";
};

export type PublicRunStopPreview = {
  action: "stop";
  confirmation_id: string;
  requires_confirmation: true;
  run_id: string;
  runtime: "python";
  schema_version: 1;
  service: "mentat-local-bridge";
  status: "ready";
};

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function validChoice(value: unknown): boolean {
  return record(value)
    && Object.keys(value).sort().join(",") === "id,label"
    && typeof value.id === "string"
    && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(value.id)
    && typeof value.label === "string"
    && value.label.length > 0
    && value.label.length <= 240;
}

function pendingRequest(value: unknown): value is PendingRunRequest {
  if (!record(value)) return false;
  if (value.kind === "approval") {
    return Object.keys(value).sort().join(",") === "choices,kind,summary,title"
      && typeof value.title === "string" && value.title.length <= 240
      && typeof value.summary === "string" && value.summary.length <= 2_000
      && Array.isArray(value.choices) && value.choices.length > 0 && value.choices.length <= 16
      && value.choices.every(validChoice)
      && value.choices.every((choice) => (choice as { id: string }).id === "once" || (choice as { id: string }).id === "deny");
  }
  return value.kind === "clarification"
    && Object.keys(value).sort().join(",") === "choices,kind,prompt_type,question"
    && (value.prompt_type === "choice" || value.prompt_type === "text")
    && typeof value.question === "string" && value.question.length > 0 && value.question.length <= 2_000
    && Array.isArray(value.choices) && value.choices.length <= 16 && value.choices.every(validChoice)
    && (value.prompt_type === "choice" ? value.choices.length > 0 : value.choices.length === 0);
}

async function boundedJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_BYTES)) throw new PublicRunActionError("response_invalid");
  if (!response.body) throw new PublicRunActionError("response_invalid");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const next = await reader.read();
    if (next.done) break;
    total += next.value.byteLength;
    if (total > MAXIMUM_BYTES) {
      void reader.cancel().catch(() => undefined);
      throw new PublicRunActionError("response_invalid");
    }
    chunks.push(next.value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let text: string;
  try { text = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
  catch { throw new PublicRunActionError("response_invalid"); }
  try { return JSON.parse(text) as unknown; } catch { throw new PublicRunActionError("response_invalid"); }
}

async function request(path: string, body: object): Promise<{ response: Response; payload: unknown }> {
  let response: Response;
  try {
    response = await fetch(path, {
      body: JSON.stringify(body),
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      method: "POST",
      signal: AbortSignal.timeout(10_000),
    });
  } catch { throw new PublicRunActionError("unavailable"); }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new PublicRunActionError("response_invalid");
  const payload = await boundedJson(response);
  if (!response.ok) {
    const state = record(payload) && payload.schema_version === 1 && typeof payload.status === "string" ? payload.status : "error";
    throw new PublicRunActionError(state);
  }
  return { response, payload };
}

function envelope(value: unknown, runId: string, action: "respond" | "stop"): value is Record<string, unknown> {
  return record(value)
    && value.schema_version === 1
    && value.service === "mentat-local-bridge"
    && value.runtime === "python"
    && value.status === "ready"
    && value.action === action
    && value.run_id === runId;
}

export async function fetchPendingRunRequest(runId: string): Promise<PendingRunRequest> {
  if (!RUN_ID.test(runId)) throw new PublicRunActionError("invalid");
  const { payload } = await request(`/api/runs/${encodeURIComponent(runId)}/response`, {});
  if (!envelope(payload, runId, "respond") || Object.keys(payload).sort().join(",") !== "action,request,requires_confirmation,run_id,runtime,schema_version,service,status" || payload.requires_confirmation !== false || !pendingRequest(payload.request)) throw new PublicRunActionError("response_invalid");
  return structuredClone(payload.request) as PendingRunRequest;
}

export async function previewRunResponse(runId: string, action: RunActionResponse): Promise<PublicRunActionPreview> {
  if (!RUN_ID.test(runId)) throw new PublicRunActionError("invalid");
  const { payload } = await request(`/api/runs/${encodeURIComponent(runId)}/response/preview`, { response: action });
  if (!envelope(payload, runId, "respond") || Object.keys(payload).sort().join(",") !== "action,confirmation_id,request,requires_confirmation,run_id,runtime,schema_version,service,status" || payload.requires_confirmation !== true || !CONFIRMATION_ID.test(String(payload.confirmation_id)) || !pendingRequest(payload.request)) throw new PublicRunActionError("response_invalid");
  return structuredClone(payload) as PublicRunActionPreview;
}

export async function confirmRunResponse(runId: string, action: RunActionResponse, confirmationId: string): Promise<void> {
  if (!RUN_ID.test(runId) || !CONFIRMATION_ID.test(confirmationId)) throw new PublicRunActionError("invalid");
  const { payload } = await request(`/api/runs/${encodeURIComponent(runId)}/response`, { confirmation_id: confirmationId, response: action });
  if (!envelope(payload, runId, "respond") || Object.keys(payload).sort().join(",") !== "action,disposition,run_id,runtime,schema_version,service,status" || payload.disposition !== "accepted") throw new PublicRunActionError("response_invalid");
}

export async function previewRunStop(runId: string): Promise<PublicRunStopPreview> {
  if (!RUN_ID.test(runId)) throw new PublicRunActionError("invalid");
  const { payload } = await request(`/api/runs/${encodeURIComponent(runId)}/stop/preview`, {});
  if (!envelope(payload, runId, "stop") || Object.keys(payload).sort().join(",") !== "action,confirmation_id,requires_confirmation,run_id,runtime,schema_version,service,status" || payload.requires_confirmation !== true || !CONFIRMATION_ID.test(String(payload.confirmation_id))) throw new PublicRunActionError("response_invalid");
  return structuredClone(payload) as PublicRunStopPreview;
}

export async function confirmRunStop(runId: string, confirmationId: string): Promise<void> {
  if (!RUN_ID.test(runId) || !CONFIRMATION_ID.test(confirmationId)) throw new PublicRunActionError("invalid");
  const { payload } = await request(`/api/runs/${encodeURIComponent(runId)}/stop`, { confirmation_id: confirmationId });
  if (!envelope(payload, runId, "stop") || Object.keys(payload).sort().join(",") !== "action,disposition,run_id,runtime,schema_version,service,status" || payload.disposition !== "requested") throw new PublicRunActionError("response_invalid");
}
