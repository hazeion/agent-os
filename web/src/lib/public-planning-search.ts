export type PublicPlanningSearchResult = Readonly<{
  id: string;
  title: string;
  type: "project" | "task";
}>;

export type PublicPlanningSearch = Readonly<{
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  query: string;
  projects: PublicPlanningSearchResult[];
  project_count: number;
  tasks: PublicPlanningSearchResult[];
  task_count: number;
  truncated: boolean;
}>;

export class PublicPlanningSearchError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.code = code; this.name = "PublicPlanningSearchError"; }
}

const PROJECT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const MAXIMUM_RESPONSE_BYTES = 64 * 1024;
const TIMEOUT_MILLISECONDS = 3_500;
const SEARCH_KEYS = "project_count,projects,query,runtime,schema_version,service,status,task_count,tasks,truncated";

function boundedSignal(signal: AbortSignal | undefined): AbortSignal {
  const timeout = AbortSignal.timeout(TIMEOUT_MILLISECONDS);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function keys(value: Record<string, unknown>, expected: string): boolean { return Object.keys(value).sort().join(",") === expected; }
function query(value: unknown): value is string { return typeof value === "string" && !!value && value.trim() === value && [...value].length <= 160 && !/\p{C}/u.test(value); }
function result(value: unknown, type: "project" | "task"): value is PublicPlanningSearchResult {
  return record(value) && keys(value, "id,title,type") && value.type === type && typeof value.id === "string"
    && (type === "project" ? PROJECT.test(value.id) : TASK.test(value.id))
    && typeof value.title === "string" && !!value.title && value.title.trim() === value.title
    && [...value.title].length <= (type === "project" ? 120 : 160) && !/\p{C}/u.test(value.title);
}

export function parsePlanningSearch(value: unknown, expectedQuery?: string): PublicPlanningSearch {
  if (!record(value) || !keys(value, SEARCH_KEYS) || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || !query(value.query) || expectedQuery !== undefined && value.query !== expectedQuery) throw new PublicPlanningSearchError("response_invalid");
  if (!Array.isArray(value.projects) || value.projects.length > 25 || !value.projects.every((item) => result(item, "project")) || value.project_count !== value.projects.length
    || !Array.isArray(value.tasks) || value.tasks.length > 25 || !value.tasks.every((item) => result(item, "task")) || value.task_count !== value.tasks.length
    || typeof value.truncated !== "boolean"
    || new Set(value.projects.map((item) => item.id)).size !== value.projects.length
    || new Set(value.tasks.map((item) => item.id)).size !== value.tasks.length) throw new PublicPlanningSearchError("response_invalid");
  return structuredClone(value) as PublicPlanningSearch;
}

async function responseJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_RESPONSE_BYTES) || !response.body) throw new PublicPlanningSearchError("response_invalid");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > MAXIMUM_RESPONSE_BYTES) { await reader.cancel(); throw new PublicPlanningSearchError("response_invalid"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new PublicPlanningSearchError("response_invalid"); }
}

function failure(response: Response, payload: unknown): never {
  if (!record(payload) || !keys(payload, "schema_version,status") || payload.schema_version !== 1 || typeof payload.status !== "string") throw new PublicPlanningSearchError("response_invalid");
  const mapped: Record<string, string> = { "400:invalid": "invalid", "503:unavailable": "unavailable" };
  throw new PublicPlanningSearchError(mapped[`${response.status}:${payload.status}`] ?? "response_invalid");
}

export async function readPlanningSearch(searchQuery: string, signal?: AbortSignal): Promise<PublicPlanningSearch> {
  if (!query(searchQuery)) throw new PublicPlanningSearchError("invalid");
  try {
    const response = await fetch(`/api/agent-console/planning-search?${new URLSearchParams({ q: searchQuery }).toString()}`, { cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json" }, redirect: "error", signal: boundedSignal(signal) });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new PublicPlanningSearchError("response_invalid");
    const payload = await responseJson(response);
    if (response.status === 200) return parsePlanningSearch(payload, searchQuery);
    failure(response, payload);
  } catch (error) { if (error instanceof PublicPlanningSearchError) throw error; throw new PublicPlanningSearchError("unavailable"); }
}
