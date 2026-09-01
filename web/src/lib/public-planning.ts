import type { PublicConversation } from "./bridge-conversations.ts";

const MAXIMUM_RESPONSE_BYTES = 768 * 1024;
const READ_TIMEOUT_MILLISECONDS = 5_000;
export const PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS = 12_000;
const PROJECT_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const TASK_ID = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const CONVERSATION_ID = /^conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u;
const CURSOR = /^[A-Za-z0-9_-]{1,512}$/u;
const ATTENTION_REASONS = ["overdue", "due_today", "review", "needs_attention", "planned_today", "due_soon"] as const;
const PLANNING_STATES = ["inbox", "planned", "in_progress", "waiting", "review", "someday", "blocked", "done"] as const;
const WORKFLOW_STAGES = ["inbox", "planned", "in_progress", "waiting", "review", "done"] as const;

type ServiceEnvelope = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
};

export type PublicPlanningProject = {
  id: string;
  name: string;
  status: "active" | "paused" | "archived";
  revision: number;
};

export type PublicPlanningTask = {
  id: string;
  title: string;
  project_id: string;
  project_name: string;
  status: "todo" | "in progress" | "waiting" | "needs attention" | "completed";
  priority: "high" | "medium" | "low";
  due_date: string | null;
  planned_for_today: boolean;
  planning_state: typeof PLANNING_STATES[number] | null;
  needs_attention: boolean;
  review_required: boolean;
  attention_reasons: Array<typeof ATTENTION_REASONS[number]>;
  updated_at: string;
  workflow_stage: typeof WORKFLOW_STAGES[number];
  deferred: boolean;
  blocked: boolean;
  revision: number;
};

export type PublicPlanningOverview = ServiceEnvelope & {
  today: string;
  projects: PublicPlanningProject[];
  project_count: number;
  attention: PublicPlanningTask[];
  attention_count: number;
  truncated: boolean;
};

export type PublicPlanningTaskPage = ServiceEnvelope & {
  project: PublicPlanningProject;
  tasks: PublicPlanningTask[];
  count: number;
  next_cursor: string | null;
};

export type PublicPlanningTaskResult = ServiceEnvelope & {
  project: PublicPlanningProject;
  task: PublicPlanningTask;
};

export type PublicPlanningAssociation = { project_id: string; task_id: string | null };

export type PublicConversationPlanningContext = ServiceEnvelope & {
  conversation_id: string;
  conversation_revision: number;
  association: PublicPlanningAssociation | null;
  project: PublicPlanningProject | null;
  task: PublicPlanningTask | null;
  state: "empty" | "ready" | "project_unavailable" | "task_unavailable" | "project_mismatch";
};

export type PublicConversationPlanningMutation = PublicConversationPlanningContext & {
  action: "set" | "clear";
  conversation: PublicConversation;
};

export type PublicPlanningProjectCreation = ServiceEnvelope & { action: "create"; project: PublicPlanningProject };
export type PublicPlanningTaskCreation = ServiceEnvelope & { action: "create"; project: PublicPlanningProject; task: PublicPlanningTask };
export type PublicPlanningProjectMutation = ServiceEnvelope & { action: "rename" | "archive" | "restore"; project: PublicPlanningProject };
export type PublicPlanningTaskMutation = ServiceEnvelope & { action: "edit" | "move"; project: PublicPlanningProject; task: PublicPlanningTask };

export class PublicPlanningError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.code = code; this.name = "PublicPlanningError"; }
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function keys(value: Record<string, unknown>, expected: string): boolean {
  return Object.keys(value).sort().join(",") === expected;
}

function text(value: unknown, maximum: number): value is string {
  return typeof value === "string" && !!value && value.trim() === value && [...value].length <= maximum && !/\p{C}/u.test(value);
}

function date(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number); const leap = year! % 4 === 0 && (year! % 100 !== 0 || year! % 400 === 0); const days = [0, 31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year! >= 1 && month! >= 1 && month! <= 12 && day! >= 1 && day! <= days[month!]!;
}

function timestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u.test(value) && !Number.isNaN(Date.parse(value));
}

function validProject(value: unknown): value is PublicPlanningProject {
  return record(value) && keys(value, "id,name,revision,status") && typeof value.id === "string" && PROJECT_ID.test(value.id)
    && text(value.name, 120) && ["active", "paused", "archived"].includes(String(value.status)) && Number.isSafeInteger(value.revision) && (value.revision as number) >= 1;
}

function validTask(value: unknown): value is PublicPlanningTask {
  if (!record(value) || !keys(value, "attention_reasons,blocked,deferred,due_date,id,needs_attention,planned_for_today,planning_state,priority,project_id,project_name,review_required,revision,status,title,updated_at,workflow_stage")) return false;
  if (!Array.isArray(value.attention_reasons) || value.attention_reasons.length > ATTENTION_REASONS.length) return false;
  const indexes = value.attention_reasons.map((reason) => ATTENTION_REASONS.indexOf(reason as typeof ATTENTION_REASONS[number]));
  return typeof value.id === "string" && TASK_ID.test(value.id)
    && text(value.title, 160)
    && typeof value.project_id === "string" && PROJECT_ID.test(value.project_id)
    && text(value.project_name, 120)
    && ["todo", "in progress", "waiting", "needs attention", "completed"].includes(String(value.status))
    && ["high", "medium", "low"].includes(String(value.priority))
    && (value.due_date === null || date(value.due_date))
    && typeof value.planned_for_today === "boolean"
    && (value.planning_state === null || PLANNING_STATES.includes(value.planning_state as typeof PLANNING_STATES[number]))
    && WORKFLOW_STAGES.includes(value.workflow_stage as typeof WORKFLOW_STAGES[number])
    && typeof value.deferred === "boolean" && typeof value.blocked === "boolean"
    && Number.isSafeInteger(value.revision) && (value.revision as number) >= 1
    && typeof value.needs_attention === "boolean" && typeof value.review_required === "boolean"
    && indexes.every((index) => index >= 0) && indexes.every((index, position) => position === 0 || indexes[position - 1]! < index)
    && timestamp(value.updated_at);
}

function validEnvelope(value: Record<string, unknown>): boolean {
  return value.schema_version === 1 && value.service === "mentat-local-bridge" && value.runtime === "python" && value.status === "ready";
}

function validConversation(value: unknown): value is PublicConversation {
  return record(value) && keys(value, "agent_id,archived_at,created_at,id,revision,state,title,title_source,updated_at")
    && typeof value.id === "string" && CONVERSATION_ID.test(value.id)
    && typeof value.agent_id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(value.agent_id)
    && text(value.title, 160) && ["default", "first_prompt", "manual"].includes(String(value.title_source))
    && ["active", "archived"].includes(String(value.state)) && Number.isSafeInteger(value.revision) && (value.revision as number) >= 1
    && timestamp(value.created_at) && timestamp(value.updated_at)
    && (value.archived_at === null || timestamp(value.archived_at))
    && ((value.state === "active") === (value.archived_at === null));
}

export function parsePlanningOverview(value: unknown): PublicPlanningOverview {
  if (!record(value) || !keys(value, "attention,attention_count,project_count,projects,runtime,schema_version,service,status,today,truncated") || !validEnvelope(value)) throw new PublicPlanningError("response_invalid");
  if (!date(value.today) || !Array.isArray(value.projects) || value.projects.length > 256 || !value.projects.every(validProject) || new Set(value.projects.map((project) => project.id)).size !== value.projects.length || value.project_count !== value.projects.length) throw new PublicPlanningError("response_invalid");
  if (!Array.isArray(value.attention) || value.attention.length > 50 || !value.attention.every(validTask) || new Set(value.attention.map((task) => task.id)).size !== value.attention.length || !Number.isSafeInteger(value.attention_count) || (value.attention_count as number) < value.attention.length || typeof value.truncated !== "boolean" || value.truncated !== ((value.attention_count as number) > value.attention.length)) throw new PublicPlanningError("response_invalid");
  const projectIds = new Set(value.projects.map((project) => project.id));
  const projectNames = new Map(value.projects.map((project) => [project.id, project.name]));
  if (value.attention.some((task) => !projectIds.has(task.project_id) || projectNames.get(task.project_id) !== task.project_name)) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningOverview;
}

export function parsePlanningTaskPage(value: unknown, projectId?: string): PublicPlanningTaskPage {
  if (!record(value) || !keys(value, "count,next_cursor,project,runtime,schema_version,service,status,tasks") || !validEnvelope(value) || !validProject(value.project)) throw new PublicPlanningError("response_invalid");
  const project = value.project;
  if (projectId !== undefined && project.id !== projectId) throw new PublicPlanningError("response_invalid");
  if (!Array.isArray(value.tasks) || value.tasks.length > 50 || !value.tasks.every(validTask) || value.tasks.some((task) => task.project_id !== project.id || task.project_name !== project.name) || new Set(value.tasks.map((task) => task.id)).size !== value.tasks.length || value.count !== value.tasks.length || value.next_cursor !== null && (typeof value.next_cursor !== "string" || !CURSOR.test(value.next_cursor))) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskPage;
}

export function parsePlanningTaskResult(value: unknown, taskId?: string): PublicPlanningTaskResult {
  if (!record(value) || !keys(value, "project,runtime,schema_version,service,status,task") || !validEnvelope(value) || !validProject(value.project) || !validTask(value.task)) throw new PublicPlanningError("response_invalid");
  if (taskId !== undefined && value.task.id !== taskId || value.task.project_id !== value.project.id || value.task.project_name !== value.project.name) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskResult;
}

export function parseConversationPlanningContext(value: unknown, conversationId?: string): PublicConversationPlanningContext {
  if (!record(value) || !keys(value, "association,conversation_id,conversation_revision,project,runtime,schema_version,service,state,status,task") || !validEnvelope(value)) throw new PublicPlanningError("response_invalid");
  if (typeof value.conversation_id !== "string" || !CONVERSATION_ID.test(value.conversation_id) || conversationId !== undefined && value.conversation_id !== conversationId || !Number.isSafeInteger(value.conversation_revision) || (value.conversation_revision as number) < 1) throw new PublicPlanningError("response_invalid");
  const association = value.association;
  if (association !== null && (!record(association) || !keys(association, "project_id,task_id") || typeof association.project_id !== "string" || !PROJECT_ID.test(association.project_id) || association.task_id !== null && (typeof association.task_id !== "string" || !TASK_ID.test(association.task_id)))) throw new PublicPlanningError("response_invalid");
  if (value.project !== null && !validProject(value.project) || value.task !== null && !validTask(value.task) || !["empty", "ready", "project_unavailable", "task_unavailable", "project_mismatch"].includes(String(value.state))) throw new PublicPlanningError("response_invalid");
  const project = value.project as PublicPlanningProject | null;
  const task = value.task as PublicPlanningTask | null;
  if (value.state === "empty" && (association !== null || project !== null || task !== null)) throw new PublicPlanningError("response_invalid");
  if (association === null && value.state !== "empty") throw new PublicPlanningError("response_invalid");
  if (association !== null) {
    if (project !== null && project.id !== association.project_id) throw new PublicPlanningError("response_invalid");
    if (task !== null && task.id !== association.task_id) throw new PublicPlanningError("response_invalid");
    if (value.state === "ready" && (project === null || association.task_id !== null && (task === null || task.project_id !== project.id || task.project_name !== project.name))) throw new PublicPlanningError("response_invalid");
    if (value.state === "project_unavailable" && (project !== null || task !== null) || value.state === "task_unavailable" && (project === null || association.task_id === null || task !== null) || value.state === "project_mismatch" && (project === null || association.task_id === null || task !== null)) throw new PublicPlanningError("response_invalid");
  }
  return structuredClone(value) as PublicConversationPlanningContext;
}

export function parseConversationPlanningMutation(value: unknown, conversationId?: string): PublicConversationPlanningMutation {
  if (!record(value) || !keys(value, "action,association,conversation,conversation_id,conversation_revision,project,runtime,schema_version,service,state,status,task") || !validConversation(value.conversation) || value.conversation.id !== value.conversation_id || value.conversation.revision !== value.conversation_revision || !["set", "clear"].includes(String(value.action))) throw new PublicPlanningError("response_invalid");
  const context = { ...value }; delete context.action; delete context.conversation;
  const parsed = parseConversationPlanningContext(context, conversationId);
  if (value.action === "clear" && (parsed.state !== "empty" || parsed.association !== null) || value.action === "set" && parsed.association === null) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicConversationPlanningMutation;
}

export function parsePlanningProjectCreation(value: unknown): PublicPlanningProjectCreation {
  if (!record(value) || !keys(value, "action,project,runtime,schema_version,service,status") || !validEnvelope(value) || value.action !== "create" || !validProject(value.project)) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningProjectCreation;
}

export function parsePlanningTaskCreation(value: unknown, projectId?: string): PublicPlanningTaskCreation {
  if (!record(value) || !keys(value, "action,project,runtime,schema_version,service,status,task") || !validEnvelope(value) || value.action !== "create" || !validProject(value.project) || !validTask(value.task) || value.task.project_id !== value.project.id || value.task.project_name !== value.project.name || projectId !== undefined && value.project.id !== projectId) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskCreation;
}

export function parsePlanningProjectMutation(value: unknown, projectId?: string): PublicPlanningProjectMutation {
  if (!record(value) || !keys(value, "action,project,runtime,schema_version,service,status") || !validEnvelope(value) || !validProject(value.project) || !["rename", "archive", "restore"].includes(String(value.action)) || projectId !== undefined && value.project.id !== projectId) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningProjectMutation;
}

export function parsePlanningTaskMutation(value: unknown, taskId?: string): PublicPlanningTaskMutation {
  if (!record(value) || !keys(value, "action,project,runtime,schema_version,service,status,task") || !validEnvelope(value) || !validProject(value.project) || !validTask(value.task) || !["edit", "move"].includes(String(value.action)) || value.task.project_id !== value.project.id || value.task.project_name !== value.project.name || taskId !== undefined && value.task.id !== taskId) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskMutation;
}

async function boundedJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_RESPONSE_BYTES) || !response.body) throw new PublicPlanningError("response_invalid");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > MAXIMUM_RESPONSE_BYTES) { await reader.cancel(); throw new PublicPlanningError("response_invalid"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new PublicPlanningError("response_invalid"); }
}

function failure(payload: unknown, response: Response): never {
  if (!record(payload) || !keys(payload, "schema_version,status") || payload.schema_version !== 1) throw new PublicPlanningError("response_invalid");
  const mapped: Record<string, string> = { "400:invalid": "invalid", "404:not_found": "not_found", "409:conflict": "conflict", "409:active_run": "active_run", "409:queue_active": "queue_active", "501:unsupported": "unsupported", "503:unavailable": "unavailable" };
  throw new PublicPlanningError(mapped[`${response.status}:${payload.status}`] ?? "response_invalid");
}

async function request(path: string, init: RequestInit = {}, timeout = READ_TIMEOUT_MILLISECONDS): Promise<{ payload: unknown; response: Response }> {
  try {
    const response = await fetch(path, { ...init, cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json", ...init.headers }, redirect: "error", signal: AbortSignal.timeout(timeout) });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new PublicPlanningError("response_invalid");
    return { response, payload: await boundedJson(response) };
  } catch (error) { if (error instanceof PublicPlanningError) throw error; throw new PublicPlanningError("unavailable"); }
}

export async function readPlanningOverview(): Promise<PublicPlanningOverview> {
  const { response, payload } = await request("/api/agent-console/planning-overview");
  if (response.status === 200) return parsePlanningOverview(payload);
  failure(payload, response);
}

export async function readPlanningTasks(projectId: string, cursor: string | null = null): Promise<PublicPlanningTaskPage> {
  if (!PROJECT_ID.test(projectId) || cursor !== null && !CURSOR.test(cursor)) throw new PublicPlanningError("invalid");
  const parameters = new URLSearchParams({ project_id: projectId }); if (cursor !== null) parameters.set("cursor", cursor);
  const { response, payload } = await request(`/api/agent-console/planning-tasks?${parameters.toString()}`);
  if (response.status === 200) return parsePlanningTaskPage(payload, projectId);
  failure(payload, response);
}

export async function readPlanningTask(taskId: string): Promise<PublicPlanningTaskResult> {
  if (!TASK_ID.test(taskId)) throw new PublicPlanningError("invalid");
  const parameters = new URLSearchParams({ task_id: taskId });
  const { response, payload } = await request(`/api/agent-console/planning-task?${parameters.toString()}`);
  if (response.status === 200) return parsePlanningTaskResult(payload, taskId);
  failure(payload, response);
}

export async function readConversationPlanningContext(id: string): Promise<PublicConversationPlanningContext> {
  if (!CONVERSATION_ID.test(id)) throw new PublicPlanningError("invalid");
  const { response, payload } = await request(`/api/conversations/${encodeURIComponent(id)}/planning-context`);
  if (response.status === 200) return parseConversationPlanningContext(payload, id);
  failure(payload, response);
}

export async function updateConversationPlanningContext(id: string, expectedRevision: number, projectId: string | null, taskId: string | null): Promise<PublicConversationPlanningMutation> {
  if (!CONVERSATION_ID.test(id) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || projectId !== null && !PROJECT_ID.test(projectId) || taskId !== null && (!TASK_ID.test(taskId) || projectId === null)) throw new PublicPlanningError("invalid");
  const { response, payload } = await request(`/api/conversations/${encodeURIComponent(id)}/planning-context`, { body: JSON.stringify({ expected_revision: expectedRevision, project_id: projectId, task_id: taskId }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS);
  if (response.status === 200) {
    const result = parseConversationPlanningMutation(payload, id);
    if (result.conversation_revision !== expectedRevision + 1) throw new PublicPlanningError("response_invalid");
    return result;
  }
  failure(payload, response);
}

export async function createProject(name: string): Promise<PublicPlanningProject> {
  if (!text(name, 120) || /\p{C}/u.test(name)) throw new PublicPlanningError("invalid");
  const { response, payload } = await request("/api/projects", { body: JSON.stringify({ name }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS);
  if (response.status === 201) {
    const project = parsePlanningProjectCreation(payload).project;
    if (project.name !== name || project.status !== "active") throw new PublicPlanningError("response_invalid");
    return { ...project };
  }
  failure(payload, response);
}

export async function createProjectTask(projectId: string, title: string, assignedAgentId: string | null, dueDate: string | null): Promise<PublicPlanningTask> {
  if (!PROJECT_ID.test(projectId) || !text(title, 160) || /\p{C}/u.test(title) || assignedAgentId !== null && !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(assignedAgentId) || dueDate !== null && !date(dueDate)) throw new PublicPlanningError("invalid");
  const { response, payload } = await request(`/api/projects/${encodeURIComponent(projectId)}/tasks`, { body: JSON.stringify({ assigned_agent_id: assignedAgentId, due_date: dueDate, title }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS);
  if (response.status === 201) {
    const result = parsePlanningTaskCreation(payload, projectId);
    if (result.task.title !== title || result.task.due_date !== dueDate || result.task.status !== "todo" || result.task.priority !== "medium") throw new PublicPlanningError("response_invalid");
    return { ...result.task, attention_reasons: [...result.task.attention_reasons] };
  }
  failure(payload, response);
}
