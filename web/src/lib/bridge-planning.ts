import {
  parseConversationPlanningContext,
  parseConversationPlanningMutation,
  parsePlanningOverview,
  parsePlanningProjectCreation,
  parsePlanningTaskPage,
  parsePlanningTaskDetailResult,
  parsePlanningTaskDependencies,
  parsePlanningDependencyPickerPage,
  parsePlanningTaskResult,
  parsePlanningTaskCreation,
  parsePlanningProjectMutation,
  parsePlanningTaskMutation,
  PublicPlanningError,
  type PublicConversationPlanningContext,
  type PublicConversationPlanningMutation,
  type PublicPlanningOverview,
  type PublicPlanningProjectCreation,
  type PublicPlanningTaskPage,
  type PublicPlanningTaskDetailResult,
  type PublicPlanningTaskResult,
  type PublicPlanningTaskCreation,
  type PublicPlanningTaskDependencies,
  type PublicPlanningProjectMutation,
  type PublicPlanningTaskMutation,
  type PublicPlanningDependencyPickerPage,
} from "./public-planning.ts";

const PRIVATE_OVERVIEW_PATH = "/bridge/v1/agent-console/planning-overview";
const PRIVATE_TASKS_PATH = "/bridge/v1/agent-console/planning-tasks";
const PRIVATE_TASK_PATH = "/bridge/v1/agent-console/planning-task";
const PRIVATE_TASK_DETAIL_PATH = "/bridge/v1/agent-console/planning-task-detail";
const PRIVATE_TASK_DEPENDENCIES_PATH = "/bridge/v1/agent-console/planning-task-dependencies";
const PRIVATE_DEPENDENCY_PICKER_PATH = "/bridge/v1/agent-console/planning-dependency-picker";
const PRIVATE_CONVERSATIONS_PATH = "/bridge/v1/conversations";
const PRIVATE_PROJECTS_PATH = "/bridge/v1/projects";
const PRIVATE_PLANNING_PATH = "/bridge/v1/planning";
const MAXIMUM_RESPONSE_BYTES = 768 * 1024;
const READ_TIMEOUT_MILLISECONDS = 3_500;
export const PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS = 8_000;
const PROJECT_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const TASK_ID = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const CONVERSATION_ID = /^conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u;
const CURSOR = /^[A-Za-z0-9_-]{1,512}$/u;
function exactDate(value: string) { if (!/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false; const [year, month, day] = value.split("-").map(Number); const leap = year! % 4 === 0 && (year! % 100 !== 0 || year! % 400 === 0); const days = [0, 31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]; return year! >= 1 && month! >= 1 && month! <= 12 && day! >= 1 && day! <= days[month!]!; }

type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export class BridgePlanningError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.code = code; this.name = "BridgePlanningError"; }
}

function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? ""); } catch { throw new BridgePlanningError("bridge_configuration_invalid"); }
  const hostname = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (origin.protocol !== "http:" || !new Set(["127.0.0.1", "::1"]).has(hostname) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new BridgePlanningError("bridge_configuration_invalid");
  return { origin: origin.origin, token };
}

async function boundedJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_RESPONSE_BYTES) || !response.body) throw new BridgePlanningError("bridge_response_invalid");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > MAXIMUM_RESPONSE_BYTES) { await reader.cancel(); throw new BridgePlanningError("bridge_response_invalid"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new BridgePlanningError("bridge_response_invalid"); }
}

function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function validFailure(value: unknown): value is Record<string, unknown> {
  return record(value) && Object.keys(value).sort().join(",") === "runtime,schema_version,service,status" && value.schema_version === 1 && value.service === "mentat-local-bridge" && value.runtime === "python";
}

function fixedFailure(response: Response, payload: unknown): never {
  if (!validFailure(payload)) throw new BridgePlanningError("bridge_response_invalid");
  const mapped: Record<string, string> = { "400:invalid": "planning_request_invalid", "404:not_found": "planning_not_found", "409:conflict": "planning_conflict", "409:active_run": "planning_active_run", "409:queue_active": "planning_queue_active", "501:unsupported": "bridge_unsupported", "503:unavailable": "bridge_unavailable" };
  throw new BridgePlanningError(mapped[`${response.status}:${payload.status}`] ?? "bridge_response_invalid");
}

async function request(path: string, fetcher: FetchLike, environment: Environment, init: RequestInit = {}, timeout = READ_TIMEOUT_MILLISECONDS) {
  const bridge = configuration(environment);
  try {
    const response = await fetcher(new URL(path, bridge.origin), { ...init, cache: "no-store", headers: { Accept: "application/json", "X-Mentat-Bridge-Token": bridge.token, ...init.headers }, redirect: "error", signal: AbortSignal.timeout(timeout) });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new BridgePlanningError("bridge_response_invalid");
    return { response, payload: await boundedJson(response) };
  } catch (error) { if (error instanceof BridgePlanningError) throw error; throw new BridgePlanningError("bridge_unavailable"); }
}

function parse<T>(operation: () => T): T {
  try { return operation(); } catch (error) { if (error instanceof PublicPlanningError) throw new BridgePlanningError("bridge_response_invalid"); throw error; }
}

export async function fetchBridgePlanningOverview(fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningOverview> {
  const { response, payload } = await request(PRIVATE_OVERVIEW_PATH, fetcher, environment);
  if (response.status === 200) return parse(() => parsePlanningOverview(payload));
  fixedFailure(response, payload);
}

export async function fetchBridgePlanningTasks(projectId: string, cursor: string | null = null, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningTaskPage> {
  if (!PROJECT_ID.test(projectId) || cursor !== null && !CURSOR.test(cursor)) throw new BridgePlanningError("planning_request_invalid");
  const parameters = new URLSearchParams({ project_id: projectId }); if (cursor !== null) parameters.set("cursor", cursor);
  const { response, payload } = await request(`${PRIVATE_TASKS_PATH}?${parameters.toString()}`, fetcher, environment);
  if (response.status === 200) return parse(() => parsePlanningTaskPage(payload, projectId));
  fixedFailure(response, payload);
}

export async function fetchBridgePlanningTask(taskId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningTaskResult> {
  if (!TASK_ID.test(taskId)) throw new BridgePlanningError("planning_request_invalid");
  const parameters = new URLSearchParams({ task_id: taskId });
  const { response, payload } = await request(`${PRIVATE_TASK_PATH}?${parameters.toString()}`, fetcher, environment);
  if (response.status === 200) return parse(() => parsePlanningTaskResult(payload, taskId));
  fixedFailure(response, payload);
}

export async function fetchBridgeConversationPlanningContext(id: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicConversationPlanningContext> {
  if (!CONVERSATION_ID.test(id)) throw new BridgePlanningError("planning_request_invalid");
  const { response, payload } = await request(`${PRIVATE_CONVERSATIONS_PATH}/${encodeURIComponent(id)}/planning-context`, fetcher, environment);
  if (response.status === 200) return parse(() => parseConversationPlanningContext(payload, id));
  fixedFailure(response, payload);
}

export async function updateBridgeConversationPlanningContext(id: string, expectedRevision: number, projectId: string | null, taskId: string | null, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicConversationPlanningMutation> {
  if (!CONVERSATION_ID.test(id) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || projectId !== null && !PROJECT_ID.test(projectId) || taskId !== null && (!TASK_ID.test(taskId) || projectId === null)) throw new BridgePlanningError("planning_request_invalid");
  const { response, payload } = await request(`${PRIVATE_CONVERSATIONS_PATH}/${encodeURIComponent(id)}/planning-context`, fetcher, environment, { body: JSON.stringify({ expected_revision: expectedRevision, project_id: projectId, task_id: taskId }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS);
  if (response.status === 200) {
    const result = parse(() => parseConversationPlanningMutation(payload, id));
    const associationMatches = projectId === null
      ? result.association === null
      : result.association?.project_id === projectId && result.association.task_id === taskId;
    if (result.conversation.revision !== expectedRevision + 1 || result.action !== (projectId === null ? "clear" : "set") || !associationMatches) throw new BridgePlanningError("bridge_response_invalid");
    return result;
  }
  fixedFailure(response, payload);
}

export async function createBridgeProject(name: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningProjectCreation> {
  if (typeof name !== "string" || !name || name.trim() !== name || [...name].length > 120 || /\p{C}/u.test(name)) throw new BridgePlanningError("planning_request_invalid");
  const { response, payload } = await request(PRIVATE_PROJECTS_PATH, fetcher, environment, { body: JSON.stringify({ name }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS);
  if (response.status === 201) {
    const result = parse(() => parsePlanningProjectCreation(payload));
    if (result.project.name !== name || result.project.status !== "active") throw new BridgePlanningError("bridge_response_invalid");
    return result;
  }
  fixedFailure(response, payload);
}

export async function createBridgeProjectTask(projectId: string, title: string, assignedAgentId: string | null, dueDate: string | null, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningTaskCreation> {
  if (!PROJECT_ID.test(projectId) || typeof title !== "string" || !title || title.trim() !== title || [...title].length > 160 || /\p{C}/u.test(title) || assignedAgentId !== null && !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(assignedAgentId) || dueDate !== null && !exactDate(dueDate)) throw new BridgePlanningError("planning_request_invalid");
  const { response, payload } = await request(`${PRIVATE_PROJECTS_PATH}/${encodeURIComponent(projectId)}/tasks`, fetcher, environment, { body: JSON.stringify({ assigned_agent_id: assignedAgentId, due_date: dueDate, title }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS);
  if (response.status === 201) {
    const result = parse(() => parsePlanningTaskCreation(payload, projectId));
    if (result.task.title !== title || result.task.due_date !== dueDate || result.task.status !== "todo" || result.task.priority !== "medium") throw new BridgePlanningError("bridge_response_invalid");
    return result;
  }
  fixedFailure(response, payload);
}

export async function fetchBridgePlanningTaskDetail(taskId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningTaskDetailResult> {
  if (!TASK_ID.test(taskId)) throw new BridgePlanningError("planning_request_invalid");
  const parameters = new URLSearchParams({ task_id: taskId });
  const { response, payload } = await request(`${PRIVATE_TASK_DETAIL_PATH}?${parameters.toString()}`, fetcher, environment);
  if (response.status === 200) return parse(() => parsePlanningTaskDetailResult(payload, taskId));
  fixedFailure(response, payload);
}

export async function fetchBridgePlanningTaskDependencies(taskId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningTaskDependencies> {
  if (!TASK_ID.test(taskId)) throw new BridgePlanningError("planning_request_invalid");
  const parameters = new URLSearchParams({ task_id: taskId });
  const { response, payload } = await request(`${PRIVATE_TASK_DEPENDENCIES_PATH}?${parameters.toString()}`, fetcher, environment);
  if (response.status === 200) return parse(() => parsePlanningTaskDependencies(payload, taskId));
  fixedFailure(response, payload);
}

export async function fetchBridgePlanningDependencyPicker(taskId: string, query: string, cursor: string | null = null, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningDependencyPickerPage> {
  if (!TASK_ID.test(taskId) || typeof query !== "string" || [...query].length > 160 || query.trim() !== query || /\p{C}/u.test(query) || cursor !== null && !CURSOR.test(cursor)) throw new BridgePlanningError("planning_request_invalid");
  const parameters = new URLSearchParams({ task_id: taskId }); if (query) parameters.set("q", query); if (cursor !== null) parameters.set("cursor", cursor);
  const { response, payload } = await request(`${PRIVATE_DEPENDENCY_PICKER_PATH}?${parameters.toString()}`, fetcher, environment);
  if (response.status === 200) return parse(() => parsePlanningDependencyPickerPage(payload, taskId, query));
  fixedFailure(response, payload);
}

export async function updateBridgePlanningProject(projectId: string, expectedRevision: number, action: "rename" | "archive" | "restore", name: string | null, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningProjectMutation> {
  if (!PROJECT_ID.test(projectId) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || !["rename", "archive", "restore"].includes(action) || action === "rename" && (typeof name !== "string" || !name || name.trim() !== name || [...name].length > 120 || /\p{C}/u.test(name)) || action !== "rename" && name !== null) throw new BridgePlanningError("planning_request_invalid");
  const { response, payload } = await request(`${PRIVATE_PLANNING_PATH}/projects/${encodeURIComponent(projectId)}`, fetcher, environment, { body: JSON.stringify({ expected_revision: expectedRevision, action, name }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS);
  if (response.status === 200) return parse(() => parsePlanningProjectMutation(payload, projectId));
  fixedFailure(response, payload);
}

export async function updateBridgePlanningTask(taskId: string, expectedRevision: number, changes: Record<string, unknown>, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningTaskMutation> {
  if (!TASK_ID.test(taskId) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || !record(changes)) throw new BridgePlanningError("planning_request_invalid");
  const { response, payload } = await request(`${PRIVATE_PLANNING_PATH}/tasks/${encodeURIComponent(taskId)}/edit`, fetcher, environment, { body: JSON.stringify({ expected_revision: expectedRevision, changes }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS);
  if (response.status === 200) return parse(() => parsePlanningTaskMutation(payload, taskId));
  fixedFailure(response, payload);
}

export async function moveBridgePlanningTask(taskId: string, expectedTaskRevision: number, projectId: string, expectedProjectRevision: number, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<PublicPlanningTaskMutation> {
  if (!TASK_ID.test(taskId) || !PROJECT_ID.test(projectId) || !Number.isSafeInteger(expectedTaskRevision) || expectedTaskRevision < 1 || !Number.isSafeInteger(expectedProjectRevision) || expectedProjectRevision < 1) throw new BridgePlanningError("planning_request_invalid");
  const { response, payload } = await request(`${PRIVATE_PLANNING_PATH}/tasks/${encodeURIComponent(taskId)}/move`, fetcher, environment, { body: JSON.stringify({ expected_task_revision: expectedTaskRevision, project_id: projectId, expected_project_revision: expectedProjectRevision }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS);
  if (response.status === 200) return parse(() => parsePlanningTaskMutation(payload, taskId));
  fixedFailure(response, payload);
}
