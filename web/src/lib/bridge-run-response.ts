import { validRunId } from "./bridge-run-events.ts";

const PATH = "/bridge/v1/runs/";
const MAX_BYTES = 24_576;
const RESPONSE_TEXT_LIMIT = 2_000;

type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
type Choice = { id: string; label: string };
type ApprovalRequest = { kind: "approval"; title: string; summary: string; choices: Choice[] };
type ClarificationRequest = { kind: "clarification"; prompt_type: "choice" | "text"; question: string; choices: Choice[] };
export type PendingRunRequest = ApprovalRequest | ClarificationRequest;
export type RunActionResponse = { kind: "approval"; choice: "once" | "deny" } | { kind: "clarification"; choice: string } | { kind: "clarification"; text: string };
export type RunResponseRequest = { schema_version: 1; service: "mentat-local-bridge"; runtime: "python"; status: "ready"; action: "respond"; run_id: string; request: PendingRunRequest; requires_confirmation: false };
export type RunResponsePreview = Omit<RunResponseRequest, "requires_confirmation"> & { requires_confirmation: true; confirmation_id: string };
export type RunResponseResult = { schema_version: 1; service: "mentat-local-bridge"; runtime: "python"; status: "ready"; action: "respond"; run_id: string; disposition: "accepted" };

export class BridgeRunResponseError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.code = code; this.name = "BridgeRunResponseError"; }
}

function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let url: URL;
  try { url = new URL(environment.MENTAT_BRIDGE_ORIGIN ?? ""); }
  catch { throw new BridgeRunResponseError("bridge_configuration_invalid"); }
  const host = url.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (url.protocol !== "http:" || !new Set(["127.0.0.1", "::1"]).has(host) || !url.port || url.username || url.password || url.pathname !== "/" || url.search || url.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new BridgeRunResponseError("bridge_configuration_invalid");
  return { origin: url.origin, token };
}

function validChoice(value: unknown, allowed: Set<string> | null = null): value is Choice {
  return !!value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join(",") === "id,label"
    && typeof (value as Record<string, unknown>).id === "string"
    && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test((value as Record<string, unknown>).id as string)
    && (allowed === null || allowed.has((value as Record<string, unknown>).id as string))
    && typeof (value as Record<string, unknown>).label === "string"
    && (value as Record<string, unknown>).label !== ""
    && ((value as Record<string, unknown>).label as string).length <= 240;
}

function validPendingRequest(value: unknown): value is PendingRunRequest {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  if (item.kind === "approval") {
    return Object.keys(item).sort().join(",") === "choices,kind,summary,title"
      && typeof item.title === "string" && item.title.length <= 240
      && typeof item.summary === "string" && item.summary.length <= 2_000
      && Array.isArray(item.choices) && item.choices.length > 0 && item.choices.length <= 16
      && item.choices.every((choice) => validChoice(choice, new Set(["once", "deny"])))
      && new Set(item.choices.map((choice) => (choice as Choice).id)).size === item.choices.length;
  }
  return item.kind === "clarification"
    && Object.keys(item).sort().join(",") === "choices,kind,prompt_type,question"
    && (item.prompt_type === "choice" || item.prompt_type === "text")
    && typeof item.question === "string" && item.question.length > 0 && item.question.length <= 2_000
    && Array.isArray(item.choices) && item.choices.length <= 16
    && item.choices.every((choice) => validChoice(choice))
    && new Set(item.choices.map((choice) => (choice as Choice).id)).size === item.choices.length
    && ((item.prompt_type === "choice" && item.choices.length > 0) || (item.prompt_type === "text" && item.choices.length === 0));
}

export function validRunActionResponse(value: unknown): value is RunActionResponse {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  if (Object.keys(item).sort().join(",") === "choice,kind") {
    return (item.kind === "approval" && (item.choice === "once" || item.choice === "deny"))
      || (item.kind === "clarification" && typeof item.choice === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(item.choice));
  }
  return Object.keys(item).sort().join(",") === "kind,text"
    && item.kind === "clarification" && typeof item.text === "string"
    && !!item.text.trim() && !item.text.includes("\0")
    && Array.from(item.text).length <= RESPONSE_TEXT_LIMIT;
}

async function bounded(response: Response): Promise<unknown> {
  const length = response.headers.get("content-length");
  if (length && (!/^\d{1,10}$/u.test(length) || Number(length) > MAX_BYTES)) throw new BridgeRunResponseError("bridge_response_invalid");
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > MAX_BYTES) throw new BridgeRunResponseError("bridge_response_invalid");
  try { return JSON.parse(text); } catch { throw new BridgeRunResponseError("bridge_response_invalid"); }
}

function failure(response: Response, payload: unknown): never {
  const fixed = (state: string) => !!payload && typeof payload === "object" && !Array.isArray(payload)
    && Object.keys(payload as object).sort().join(",") === "runtime,schema_version,service,status"
    && (payload as Record<string, unknown>).schema_version === 1
    && (payload as Record<string, unknown>).service === "mentat-local-bridge"
    && (payload as Record<string, unknown>).runtime === "python"
    && (payload as Record<string, unknown>).status === state;
  if (response.status === 404 && fixed("not_found")) throw new BridgeRunResponseError("run_not_found");
  if (response.status === 409 && fixed("conflict")) throw new BridgeRunResponseError("action_conflict");
  if (response.status === 501 && fixed("unsupported")) throw new BridgeRunResponseError("action_unsupported");
  if (response.status === 503 && fixed("unavailable")) throw new BridgeRunResponseError("bridge_unavailable");
  if (response.status === 400 && fixed("invalid")) throw new BridgeRunResponseError("request_invalid");
  if (response.status === 500 && fixed("partial")) throw new BridgeRunResponseError("action_partial");
  if (response.status === 500 && fixed("error")) throw new BridgeRunResponseError("action_failed");
  throw new BridgeRunResponseError("bridge_response_invalid");
}

async function request(runId: string, suffix: string, body: object, fetcher: FetchLike, environment: Environment) {
  if (!validRunId(runId)) throw new BridgeRunResponseError("request_invalid");
  const bridge = configuration(environment);
  let response: Response;
  try {
    response = await fetcher(new URL(`${PATH}${encodeURIComponent(runId)}/response${suffix}`, bridge.origin), {
      method: "POST", cache: "no-store", redirect: "error",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-Mentat-Bridge-Token": bridge.token },
      body: JSON.stringify(body), signal: AbortSignal.timeout(1_500),
    });
  } catch { throw new BridgeRunResponseError("bridge_unavailable"); }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new BridgeRunResponseError("bridge_response_invalid");
  return { response, payload: await bounded(response) };
}

function validEnvelope(value: unknown, runId: string, requiresConfirmation: boolean): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  const expected = requiresConfirmation
    ? "action,confirmation_id,request,requires_confirmation,run_id,runtime,schema_version,service,status"
    : "action,request,requires_confirmation,run_id,runtime,schema_version,service,status";
  return Object.keys(item).sort().join(",") === expected && item.schema_version === 1
    && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === "ready"
    && item.action === "respond" && item.run_id === runId && item.requires_confirmation === requiresConfirmation
    && validPendingRequest(item.request)
    && (!requiresConfirmation || (typeof item.confirmation_id === "string" && /^[0-9a-f]{64}$/u.test(item.confirmation_id)));
}

export async function fetchBridgeRunResponseRequest(runId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<RunResponseRequest> {
  const { response, payload } = await request(runId, "", {}, fetcher, environment);
  if (response.status === 200 && validEnvelope(payload, runId, false)) return payload as RunResponseRequest;
  return failure(response, payload);
}

export async function previewBridgeRunResponse(runId: string, action: RunActionResponse, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<RunResponsePreview> {
  if (!validRunActionResponse(action)) throw new BridgeRunResponseError("request_invalid");
  const { response, payload } = await request(runId, "/preview", { response: action }, fetcher, environment);
  if (response.status === 200 && validEnvelope(payload, runId, true)) return payload as RunResponsePreview;
  return failure(response, payload);
}

export async function confirmBridgeRunResponse(runId: string, action: RunActionResponse, confirmationId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<RunResponseResult> {
  if (!validRunActionResponse(action) || !/^[0-9a-f]{64}$/u.test(confirmationId)) throw new BridgeRunResponseError("request_invalid");
  const { response, payload } = await request(runId, "", { response: action, confirmation_id: confirmationId }, fetcher, environment);
  if (response.status === 202 && payload && typeof payload === "object" && !Array.isArray(payload)) {
    const item = payload as Record<string, unknown>;
    if (Object.keys(item).sort().join(",") === "action,disposition,run_id,runtime,schema_version,service,status" && item.schema_version === 1 && item.service === "mentat-local-bridge" && item.runtime === "python" && item.status === "ready" && item.action === "respond" && item.run_id === runId && item.disposition === "accepted") return item as RunResponseResult;
  }
  return failure(response, payload);
}
