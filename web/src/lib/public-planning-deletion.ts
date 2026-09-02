export type PlanningDeletionTargetKind = "task" | "project";

export type PublicPlanningDeletionCounts = Readonly<{
  projects: number;
  tasks: number;
  conversations: number;
  runs: number;
  artifacts: number;
}>;

export type PublicPlanningDeletionPreview = Readonly<{
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  target_kind: PlanningDeletionTargetKind;
  target_id: string;
  confirmation_id: string;
  affected: PublicPlanningDeletionCounts;
  has_active_runs: boolean;
}>;

export type PublicPlanningDeletionMutation = Readonly<{
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  action: "delete";
  target_kind: PlanningDeletionTargetKind;
  target_id: string;
  deletion: PublicPlanningDeletionCounts;
}>;

export class PublicPlanningDeletionError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.code = code; this.name = "PublicPlanningDeletionError"; }
}

const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const PROJECT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const CONFIRMATION = /^[0-9a-f]{64}$/u;
const COUNT_KEYS = "artifacts,conversations,projects,runs,tasks";
const PREVIEW_KEYS = "affected,confirmation_id,has_active_runs,runtime,schema_version,service,status,target_id,target_kind";
const MUTATION_KEYS = "action,deletion,runtime,schema_version,service,status,target_id,target_kind";
const MAXIMUM_RESPONSE_BYTES = 64 * 1024;
const TIMEOUT_MILLISECONDS = 8_000;

function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function keys(value: Record<string, unknown>, expected: string): boolean { return Object.keys(value).sort().join(",") === expected; }
function validTarget(kind: unknown, id: unknown): kind is PlanningDeletionTargetKind {
  return (kind === "task" && typeof id === "string" && TASK.test(id)) || (kind === "project" && typeof id === "string" && PROJECT.test(id));
}
function validCounts(value: unknown, targetKind?: PlanningDeletionTargetKind): value is PublicPlanningDeletionCounts {
  if (!record(value) || !keys(value, COUNT_KEYS)) return false;
  const limits = { artifacts: 10_000, conversations: 1_024, projects: 256, runs: 10_000, tasks: 2_048 };
  if (!Object.entries(limits).every(([key, maximum]) => Number.isSafeInteger(value[key]) && (value[key] as number) >= 0 && (value[key] as number) <= maximum)) return false;
  return targetKind === undefined || targetKind === "task" ? (value.tasks as number) >= 1 : (value.projects as number) >= 1;
}
function validEnvelope(value: Record<string, unknown>): boolean {
  return value.schema_version === 1 && value.service === "mentat-local-bridge" && value.runtime === "python" && value.status === "ready";
}

export function parsePlanningDeletionPreview(value: unknown, targetKind?: PlanningDeletionTargetKind, targetId?: string): PublicPlanningDeletionPreview {
  if (!record(value) || !keys(value, PREVIEW_KEYS) || !validEnvelope(value) || !validTarget(value.target_kind, value.target_id)
    || targetKind !== undefined && value.target_kind !== targetKind || targetId !== undefined && value.target_id !== targetId
    || typeof value.confirmation_id !== "string" || !CONFIRMATION.test(value.confirmation_id)
    || !validCounts(value.affected, value.target_kind) || typeof value.has_active_runs !== "boolean") throw new PublicPlanningDeletionError("response_invalid");
  return structuredClone(value) as PublicPlanningDeletionPreview;
}

export function parsePlanningDeletionMutation(value: unknown, targetKind?: PlanningDeletionTargetKind, targetId?: string): PublicPlanningDeletionMutation {
  if (!record(value) || !keys(value, MUTATION_KEYS) || !validEnvelope(value) || value.action !== "delete" || !validTarget(value.target_kind, value.target_id)
    || targetKind !== undefined && value.target_kind !== targetKind || targetId !== undefined && value.target_id !== targetId
    || !validCounts(value.deletion, value.target_kind)) throw new PublicPlanningDeletionError("response_invalid");
  return structuredClone(value) as PublicPlanningDeletionMutation;
}

async function json(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_RESPONSE_BYTES) || !response.body) throw new PublicPlanningDeletionError("response_invalid");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > MAXIMUM_RESPONSE_BYTES) { await reader.cancel(); throw new PublicPlanningDeletionError("response_invalid"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new PublicPlanningDeletionError("response_invalid"); }
}

function failure(response: Response, payload: unknown): never {
  if (!record(payload) || !keys(payload, "schema_version,status") || payload.schema_version !== 1 || typeof payload.status !== "string") throw new PublicPlanningDeletionError("response_invalid");
  const mapped: Record<string, string> = {
    "400:invalid": "invalid", "404:not_found": "not_found", "409:conflict": "conflict", "409:active_run": "active_run", "409:queue_active": "queue_active", "501:unsupported": "unsupported", "503:unavailable": "unavailable",
  };
  throw new PublicPlanningDeletionError(mapped[`${response.status}:${payload.status}`] ?? "response_invalid");
}

async function request(path: string, body: Record<string, unknown>): Promise<{ response: Response; payload: unknown }> {
  try {
    const response = await fetch(path, { body: JSON.stringify(body), cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json", "Content-Type": "application/json" }, method: "POST", redirect: "error", signal: AbortSignal.timeout(TIMEOUT_MILLISECONDS) });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new PublicPlanningDeletionError("response_invalid");
    return { response, payload: await json(response) };
  } catch (error) { if (error instanceof PublicPlanningDeletionError) throw error; throw new PublicPlanningDeletionError("unavailable"); }
}

function deletionPath(kind: PlanningDeletionTargetKind, id: string, action: "preview" | "confirm"): string {
  if (!validTarget(kind, id)) throw new PublicPlanningDeletionError("invalid");
  const collection = kind === "task" ? "tasks" : "projects";
  return `/api/planning/${collection}/${encodeURIComponent(id)}/delete${action === "preview" ? "/preview" : ""}`;
}

export async function previewPlanningDeletion(targetKind: PlanningDeletionTargetKind, targetId: string): Promise<PublicPlanningDeletionPreview> {
  const { response, payload } = await request(deletionPath(targetKind, targetId, "preview"), {});
  if (response.status === 200) return parsePlanningDeletionPreview(payload, targetKind, targetId);
  failure(response, payload);
}

export async function confirmPlanningDeletion(targetKind: PlanningDeletionTargetKind, targetId: string, confirmationId: string): Promise<PublicPlanningDeletionMutation> {
  if (typeof confirmationId !== "string" || !CONFIRMATION.test(confirmationId)) throw new PublicPlanningDeletionError("invalid");
  const { response, payload } = await request(deletionPath(targetKind, targetId, "confirm"), { confirmation_id: confirmationId, confirmed: true });
  if (response.status === 200) return parsePlanningDeletionMutation(payload, targetKind, targetId);
  failure(response, payload);
}
