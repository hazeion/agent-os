import type { PublicConversation } from "./bridge-conversations.ts";

const MAXIMUM_RESPONSE_BYTES = 768 * 1024;
const READ_TIMEOUT_MILLISECONDS = 5_000;
export const PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS = 12_000;
const PROJECT_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const TASK_ID = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const CONVERSATION_ID = /^conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/u;
const CURSOR = /^[A-Za-z0-9_-]{1,512}$/u;
const SAVED_VIEWS = ["all", "today", "waiting", "review", "someday", "completed"] as const;
const ATTENTION_REASONS = ["overdue", "due_today", "review", "needs_attention", "planned_today", "due_soon"] as const;
const PLANNING_STATES = ["inbox", "planned", "in_progress", "waiting", "review", "someday", "blocked", "done"] as const;
const WORKFLOW_STAGES = ["inbox", "planned", "in_progress", "waiting", "review", "done"] as const;

export type ServiceEnvelope = {
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

export type PublicPlanningTaskListItem = PublicPlanningTask & {
  description_preview: string;
};

export type PublicPlanningSubtask = { id: string; title: string; completed: boolean; rank: number };
export type PublicPlanningRecurrence = { frequency: "daily" | "weekly" | "monthly" | "yearly"; interval: number; weekdays?: Array<"mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun">; ends_on?: string; count?: number };
export type PublicPlanningScheduledBlock = { start: string; end: string; label?: string; timezone?: string };
export type PublicPlanningReminder = { id: string; at: string; channel: "browser"; enabled: boolean; notified_at?: string; timezone?: string };
export type PublicPlanningCalendarLink = { calendar_id: string; event_id: string; label?: string };
export type PublicPlanningNoteLink = { path: string; title?: string };
export type PublicPlanningDependencyReference = { id: string; title: string; project_id: string; project_name: string; workflow_stage: typeof WORKFLOW_STAGES[number]; blocked: boolean };
export type PublicPlanningTaskDetail = PublicPlanningTask & { description: string; tags: string[]; estimated_minutes: number | null; scheduled_block: PublicPlanningScheduledBlock | null; recurrence: PublicPlanningRecurrence | null; reminders: PublicPlanningReminder[]; subtasks: PublicPlanningSubtask[]; calendar_links: PublicPlanningCalendarLink[]; note_links: PublicPlanningNoteLink[]; assigned_agent_id: string | null };

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
  tasks: PublicPlanningTaskListItem[];
  count: number;
  next_cursor: string | null;
};

export type PublicPlanningTaskResult = ServiceEnvelope & {
  project: PublicPlanningProject;
  task: PublicPlanningTask;
};
export type PublicPlanningTaskDetailResult = ServiceEnvelope & { project: PublicPlanningProject; task: PublicPlanningTaskDetail };
export type PublicPlanningTaskDependencies = ServiceEnvelope & { task_id: string; task_revision: number; prerequisites: PublicPlanningDependencyReference[]; prerequisite_count: number; prerequisites_truncated: boolean; dependents: PublicPlanningDependencyReference[]; dependent_count: number; dependents_truncated: boolean };
export type PublicPlanningDependencyMapEdge = { from_task_id: string; to_task_id: string };
export type PublicPlanningDependencyMap = ServiceEnvelope & { project: PublicPlanningProject; nodes: PublicPlanningDependencyReference[]; node_count: number; node_total: number; nodes_truncated: boolean; external_stubs: PublicPlanningDependencyReference[]; external_stub_count: number; external_stub_total: number; external_stubs_truncated: boolean; edges: PublicPlanningDependencyMapEdge[]; edge_count: number; edge_total: number; edges_truncated: boolean };
export type PublicPlanningSavedView = typeof SAVED_VIEWS[number];
export type PublicPlanningDependencyPickerPage = ServiceEnvelope & { task_id: string; query: string; candidates: PublicPlanningDependencyReference[]; candidate_count: number; match_count: number; next_cursor: string | null; truncated: boolean };

/** A bounded, safe record of one Task-owned dispatch. It is not a runtime handle. */
export type PublicPlanningExecutionAttempt = {
  run_id: string;
  task_revision: number;
  agent_id: string;
  state: "dispatched" | "review_ready" | "completion_blocked" | "accepted" | "changes_requested";
  review_task_revision: number | null;
  completion_reason: "task_changed" | null;
  runtime_type: string;
  status: string;
  dispatch_state: string;
  partial: boolean;
  terminal_finalized: boolean;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  review_action: "accept" | "request_changes" | null;
  review_note: string | null;
};
export type PublicPlanningExecutionTask = PublicPlanningTask & { assigned_agent_id: string | null };
export type PublicPlanningTaskExecution = ServiceEnvelope & {
  task: PublicPlanningExecutionTask;
  execution: {
    available: boolean;
    reason: string | null;
    attempts: PublicPlanningExecutionAttempt[];
    attempt_count: number;
    review: { available: boolean; run_id: string | null };
  };
};
export type PublicPlanningRunOncePreview = ServiceEnvelope & { action: "run_once"; task: PublicPlanningExecutionTask; requires_confirmation: true; confirmation_id: string };
export type PublicPlanningTaskExecutionMutation = PublicPlanningTaskExecution & { action: "run_once" | "accept" | "request_changes"; duplicate: boolean };

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

export function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

export function keys(value: Record<string, unknown>, expected: string): boolean {
  return Object.keys(value).sort().join(",") === expected;
}

export function text(value: unknown, maximum: number): value is string {
  return typeof value === "string" && !!value && value.trim() === value && [...value].length <= maximum && !/\p{C}/u.test(value);
}

function date(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number); const leap = year! % 4 === 0 && (year! % 100 !== 0 || year! % 400 === 0); const days = [0, 31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year! >= 1 && month! >= 1 && month! <= 12 && day! >= 1 && day! <= days[month!]!;
}

export function timestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u.test(value) && !Number.isNaN(Date.parse(value));
}

function validProject(value: unknown): value is PublicPlanningProject {
  return record(value) && keys(value, "id,name,revision,status") && typeof value.id === "string" && PROJECT_ID.test(value.id)
    && text(value.name, 120) && ["active", "paused", "archived"].includes(String(value.status)) && Number.isSafeInteger(value.revision) && (value.revision as number) >= 1;
}

export function validTask(value: unknown): value is PublicPlanningTask {
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

function validTaskListItem(value: unknown): value is PublicPlanningTaskListItem {
  if (!record(value)) return false;
  const { description_preview: preview, ...task } = value;
  return typeof preview === "string" && preview.trim() === preview && [...preview].length <= 280
    && !/\p{C}/u.test(preview) && validTask(task);
}

function validRecurrence(value: unknown): value is PublicPlanningRecurrence {
  if (!record(value) || !["daily", "weekly", "monthly", "yearly"].includes(String(value.frequency)) || !Number.isSafeInteger(value.interval) || (value.interval as number) < 1 || (value.interval as number) > 365) return false;
  const allowed = new Set(["frequency", "interval", "weekdays", "ends_on", "count"]);
  if (Object.keys(value).some((key) => !allowed.has(key)) || value.weekdays !== undefined && (!Array.isArray(value.weekdays) || !value.weekdays.length || value.weekdays.length > 7 || !value.weekdays.every((day) => ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].includes(String(day))) || value.frequency !== "weekly") || value.ends_on !== undefined && !date(value.ends_on) || value.count !== undefined && (!Number.isSafeInteger(value.count) || (value.count as number) < 1 || (value.count as number) > 10000) || value.ends_on !== undefined && value.count !== undefined) return false;
  return true;
}

function validTimezone(value: unknown): value is string {
  return typeof value === "string" && value.length <= 64 && /^[A-Za-z_+-]+(?:\/[A-Za-z_+-]+)*$/u.test(value);
}

/** Python canonicalizes selected-detail planning times to this portable UTC form. */
function validPlanningDateTime(value: unknown): value is string { return timestamp(value); }

function validScheduledBlock(value: unknown): value is PublicPlanningScheduledBlock {
  if (!record(value) || Object.keys(value).some((key) => !new Set(["start", "end", "label", "timezone"]).has(key)) || !validPlanningDateTime(value.start) || !validPlanningDateTime(value.end) || Date.parse(value.end) <= Date.parse(value.start)) return false;
  return (value.label === undefined || text(value.label, 120)) && (value.timezone === undefined || validTimezone(value.timezone));
}

function validReminder(value: unknown): value is PublicPlanningReminder {
  if (!record(value) || Object.keys(value).some((key) => !new Set(["id", "at", "channel", "enabled", "notified_at", "timezone"]).has(key))) return false;
  return typeof value.id === "string" && TASK_ID.test(value.id) && validPlanningDateTime(value.at) && value.channel === "browser" && typeof value.enabled === "boolean"
    && (value.notified_at === undefined || validPlanningDateTime(value.notified_at)) && (value.timezone === undefined || validTimezone(value.timezone));
}

function validCalendarLink(value: unknown): value is PublicPlanningCalendarLink {
  if (!record(value) || Object.keys(value).some((key) => !new Set(["calendar_id", "event_id", "label"]).has(key))) return false;
  return typeof value.calendar_id === "string" && TASK_ID.test(value.calendar_id) && typeof value.event_id === "string" && TASK_ID.test(value.event_id) && (value.label === undefined || text(value.label, 160));
}

function validNoteLink(value: unknown): value is PublicPlanningNoteLink {
  if (!record(value) || Object.keys(value).some((key) => !new Set(["path", "title"]).has(key)) || typeof value.path !== "string" || !text(value.path, 500) || /\\/u.test(value.path) || /^(?:[~\\/]|[A-Za-z]:|file:|obsidian:)/iu.test(value.path)) return false;
  const parts = value.path.split("/");
  return parts.length > 0 && parts.every((part) => !!part && part !== "." && part !== "..") && (value.title === undefined || text(value.title, 240));
}

function validDependencyReference(value: unknown): value is PublicPlanningDependencyReference {
  return record(value) && keys(value, "blocked,id,project_id,project_name,title,workflow_stage")
    && typeof value.id === "string" && TASK_ID.test(value.id)
    && text(value.title, 160)
    && typeof value.project_id === "string" && PROJECT_ID.test(value.project_id)
    && text(value.project_name, 120)
    && WORKFLOW_STAGES.includes(value.workflow_stage as typeof WORKFLOW_STAGES[number])
    && typeof value.blocked === "boolean";
}

function validTaskDetail(value: unknown): value is PublicPlanningTaskDetail {
  if (!record(value) || !keys(value, "assigned_agent_id,attention_reasons,blocked,calendar_links,deferred,description,due_date,estimated_minutes,id,needs_attention,note_links,planned_for_today,planning_state,priority,project_id,project_name,recurrence,reminders,review_required,revision,scheduled_block,status,subtasks,tags,title,updated_at,workflow_stage")) return false;
  const { description, tags, estimated_minutes: estimate, scheduled_block: scheduledBlock, recurrence, reminders, subtasks, calendar_links: calendarLinks, note_links: noteLinks, assigned_agent_id: agentId, ...task } = value;
  return validTask(task) && typeof description === "string" && description.length <= 4000 && !/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/u.test(description)
    && Array.isArray(tags) && tags.length <= 12 && tags.every((tag) => text(tag, 48))
    && (estimate === null || Number.isSafeInteger(estimate) && (estimate as number) >= 1 && (estimate as number) <= 10080)
    && (scheduledBlock === null || validScheduledBlock(scheduledBlock))
    && (recurrence === null || validRecurrence(recurrence))
    && Array.isArray(reminders) && reminders.length <= 20 && reminders.every(validReminder)
    && Array.isArray(subtasks) && subtasks.length <= 200 && subtasks.every((item) => record(item) && keys(item, "completed,id,rank,title") && typeof item.id === "string" && TASK_ID.test(item.id) && text(item.title, 240) && typeof item.completed === "boolean" && Number.isSafeInteger(item.rank) && (item.rank as number) >= 0 && (item.rank as number) <= 1000000)
    && Array.isArray(calendarLinks) && calendarLinks.length <= 20 && calendarLinks.every(validCalendarLink)
    && Array.isArray(noteLinks) && noteLinks.length <= 50 && noteLinks.every(validNoteLink)
    && (agentId === null || typeof agentId === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(agentId));
}

export function validEnvelope(value: Record<string, unknown>): boolean {
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
  if (!Array.isArray(value.tasks) || value.tasks.length > 50 || !value.tasks.every(validTaskListItem) || value.tasks.some((task) => task.project_id !== project.id || task.project_name !== project.name) || new Set(value.tasks.map((task) => task.id)).size !== value.tasks.length || value.count !== value.tasks.length || value.next_cursor !== null && (typeof value.next_cursor !== "string" || !CURSOR.test(value.next_cursor))) throw new PublicPlanningError("response_invalid");
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

export function parsePlanningTaskDetailResult(value: unknown, taskId?: string): PublicPlanningTaskDetailResult {
  if (!record(value) || !keys(value, "project,runtime,schema_version,service,status,task") || !validEnvelope(value) || !validProject(value.project) || !validTaskDetail(value.task)) throw new PublicPlanningError("response_invalid");
  if (taskId !== undefined && value.task.id !== taskId || value.task.project_id !== value.project.id || value.task.project_name !== value.project.name) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskDetailResult;
}

export function parsePlanningTaskDependencies(value: unknown, taskId?: string): PublicPlanningTaskDependencies {
  if (!record(value) || !keys(value, "dependent_count,dependents,dependents_truncated,prerequisite_count,prerequisites,prerequisites_truncated,runtime,schema_version,service,status,task_id,task_revision") || !validEnvelope(value)
    || typeof value.task_id !== "string" || !TASK_ID.test(value.task_id) || taskId !== undefined && value.task_id !== taskId
    || !Number.isSafeInteger(value.task_revision) || (value.task_revision as number) < 1
    || !Array.isArray(value.prerequisites) || value.prerequisites.length > 100 || !value.prerequisites.every(validDependencyReference)
    || !Array.isArray(value.dependents) || value.dependents.length > 100 || !value.dependents.every(validDependencyReference)
    || !Number.isSafeInteger(value.prerequisite_count) || (value.prerequisite_count as number) < value.prerequisites.length || (value.prerequisite_count as number) > 100
    || !Number.isSafeInteger(value.dependent_count) || (value.dependent_count as number) < value.dependents.length || (value.dependent_count as number) > 2047
    || typeof value.prerequisites_truncated !== "boolean" || value.prerequisites_truncated !== ((value.prerequisite_count as number) > value.prerequisites.length)
    || typeof value.dependents_truncated !== "boolean" || value.dependents_truncated !== ((value.dependent_count as number) > value.dependents.length)) throw new PublicPlanningError("response_invalid");
  const identifiers = new Set<string>();
  if (![...value.prerequisites, ...value.dependents].every((item) => !identifiers.has(item.id) && (identifiers.add(item.id), true))) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningTaskDependencies;
}

export function parsePlanningDependencyMap(value: unknown, projectId?: string): PublicPlanningDependencyMap {
  if (!record(value) || !keys(value, "edge_count,edge_total,edges,edges_truncated,external_stub_count,external_stub_total,external_stubs,external_stubs_truncated,node_count,node_total,nodes,nodes_truncated,project,runtime,schema_version,service,status") || !validEnvelope(value) || !validProject(value.project)) throw new PublicPlanningError("response_invalid");
  const project = value.project;
  if (projectId !== undefined && project.id !== projectId
    || !Array.isArray(value.nodes) || value.nodes.length > 50 || !value.nodes.every(validDependencyReference)
    || !Array.isArray(value.external_stubs) || value.external_stubs.length > 50 || !value.external_stubs.every(validDependencyReference)
    || !Array.isArray(value.edges) || value.edges.length > 250
    || !Number.isSafeInteger(value.node_count) || value.node_count !== value.nodes.length || !Number.isSafeInteger(value.node_total) || (value.node_total as number) < value.node_count || (value.node_total as number) > 2048 || typeof value.nodes_truncated !== "boolean" || value.nodes_truncated !== ((value.node_total as number) > value.node_count)
    || !Number.isSafeInteger(value.external_stub_count) || value.external_stub_count !== value.external_stubs.length || !Number.isSafeInteger(value.external_stub_total) || (value.external_stub_total as number) < value.external_stub_count || (value.external_stub_total as number) > 2048 || typeof value.external_stubs_truncated !== "boolean" || value.external_stubs_truncated !== ((value.external_stub_total as number) > value.external_stub_count)
    || !Number.isSafeInteger(value.edge_count) || value.edge_count !== value.edges.length || !Number.isSafeInteger(value.edge_total) || (value.edge_total as number) < value.edge_count || (value.edge_total as number) > 204800 || typeof value.edges_truncated !== "boolean" || value.edges_truncated !== ((value.edge_total as number) > value.edge_count)) throw new PublicPlanningError("response_invalid");
  const nodes = value.nodes as PublicPlanningDependencyReference[];
  const stubs = value.external_stubs as PublicPlanningDependencyReference[];
  const nodeIds = new Set(nodes.map((item) => item.id));
  const stubIds = new Set(stubs.map((item) => item.id));
  if (nodeIds.size !== nodes.length || stubIds.size !== stubs.length || [...nodeIds].some((id) => stubIds.has(id))
    || nodes.some((item) => item.project_id !== project.id || item.project_name !== project.name)
    || stubs.some((item) => item.project_id === project.id)
    || (value.node_total as number) + (value.external_stub_total as number) > 2048) throw new PublicPlanningError("response_invalid");
  const visibleIds = new Set([...nodeIds, ...stubIds]);
  const edgePairs = new Set<string>();
  const edges = value.edges as unknown[];
  if (!edges.every((edge) => record(edge) && keys(edge, "from_task_id,to_task_id") && typeof edge.from_task_id === "string" && TASK_ID.test(edge.from_task_id) && typeof edge.to_task_id === "string" && TASK_ID.test(edge.to_task_id) && edge.from_task_id !== edge.to_task_id && visibleIds.has(edge.from_task_id) && visibleIds.has(edge.to_task_id) && (nodeIds.has(edge.from_task_id) || nodeIds.has(edge.to_task_id)) && !edgePairs.has(`${edge.from_task_id}\u0000${edge.to_task_id}`) && (edgePairs.add(`${edge.from_task_id}\u0000${edge.to_task_id}`), true))) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningDependencyMap;
}

export function parsePlanningDependencyPickerPage(value: unknown, taskId?: string, query?: string): PublicPlanningDependencyPickerPage {
  if (!record(value) || !keys(value, "candidate_count,candidates,match_count,next_cursor,query,runtime,schema_version,service,status,task_id,truncated") || !validEnvelope(value)
    || typeof value.task_id !== "string" || !TASK_ID.test(value.task_id) || taskId !== undefined && value.task_id !== taskId
    || typeof value.query !== "string" || [...value.query].length > 160 || value.query.trim() !== value.query || /\p{C}/u.test(value.query) || query !== undefined && value.query !== query
    || !Array.isArray(value.candidates) || value.candidates.length > 50 || !value.candidates.every(validDependencyReference)
    || !Number.isSafeInteger(value.candidate_count) || value.candidate_count !== value.candidates.length
    || !Number.isSafeInteger(value.match_count) || (value.match_count as number) < value.candidate_count || (value.match_count as number) > 2047
    || typeof value.truncated !== "boolean" || value.truncated !== (value.next_cursor !== null)
    || value.next_cursor !== null && (typeof value.next_cursor !== "string" || !CURSOR.test(value.next_cursor))) throw new PublicPlanningError("response_invalid");
  const identifiers = new Set<string>();
  if (!value.candidates.every((item) => !identifiers.has(item.id) && (identifiers.add(item.id), true))) throw new PublicPlanningError("response_invalid");
  return structuredClone(value) as PublicPlanningDependencyPickerPage;
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

export function failure(payload: unknown, response: Response): never {
  if (!record(payload) || !keys(payload, "schema_version,status") || payload.schema_version !== 1) throw new PublicPlanningError("response_invalid");
  const mapped: Record<string, string> = { "400:invalid": "invalid", "404:not_found": "not_found", "409:conflict": "conflict", "409:active_run": "active_run", "409:queue_active": "queue_active", "500:partial": "partial", "500:error": "error", "501:unsupported": "unsupported", "503:unavailable": "unavailable" };
  throw new PublicPlanningError(mapped[`${response.status}:${payload.status}`] ?? "response_invalid");
}

export async function request(path: string, init: RequestInit = {}, timeout = READ_TIMEOUT_MILLISECONDS): Promise<{ payload: unknown; response: Response }> {
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

export async function readPlanningTaskDetail(taskId: string): Promise<PublicPlanningTaskDetailResult> {
  if (!TASK_ID.test(taskId)) throw new PublicPlanningError("invalid");
  const parameters = new URLSearchParams({ task_id: taskId });
  const { response, payload } = await request(`/api/agent-console/planning-task-detail?${parameters.toString()}`);
  if (response.status === 200) return parsePlanningTaskDetailResult(payload, taskId);
  failure(payload, response);
}

export async function readPlanningDependencyPicker(taskId: string, query: string, cursor: string | null = null): Promise<PublicPlanningDependencyPickerPage> {
  if (!TASK_ID.test(taskId) || typeof query !== "string" || [...query].length > 160 || query.trim() !== query || /\p{C}/u.test(query) || cursor !== null && !CURSOR.test(cursor)) throw new PublicPlanningError("invalid");
  const parameters = new URLSearchParams({ task_id: taskId }); if (query) parameters.set("q", query); if (cursor !== null) parameters.set("cursor", cursor);
  const { response, payload } = await request(`/api/agent-console/planning-dependency-picker?${parameters.toString()}`);
  if (response.status === 200) return parsePlanningDependencyPickerPage(payload, taskId, query);
  failure(payload, response);
}

export async function readPlanningTaskDependencies(taskId: string): Promise<PublicPlanningTaskDependencies> {
  if (!TASK_ID.test(taskId)) throw new PublicPlanningError("invalid");
  const parameters = new URLSearchParams({ task_id: taskId });
  const { response, payload } = await request(`/api/agent-console/planning-task-dependencies?${parameters.toString()}`);
  if (response.status === 200) return parsePlanningTaskDependencies(payload, taskId);
  failure(payload, response);
}

export async function readPlanningDependencyMap(projectId: string, query: string = "", savedView: PublicPlanningSavedView = "all"): Promise<PublicPlanningDependencyMap> {
  if (!PROJECT_ID.test(projectId) || typeof query !== "string" || [...query].length > 160 || query.trim() !== query || /\p{C}/u.test(query) || !SAVED_VIEWS.includes(savedView)) throw new PublicPlanningError("invalid");
  const parameters = new URLSearchParams({ project_id: projectId });
  if (query) parameters.set("q", query); if (savedView !== "all") parameters.set("view", savedView);
  const { response, payload } = await request(`/api/agent-console/planning-dependency-map?${parameters.toString()}`);
  if (response.status === 200) return parsePlanningDependencyMap(payload, projectId);
  failure(payload, response);
}

export async function updatePlanningProject(projectId: string, expectedRevision: number, action: "rename" | "archive" | "restore", name: string | null): Promise<PublicPlanningProjectMutation> {
  if (!PROJECT_ID.test(projectId) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || !["rename", "archive", "restore"].includes(action) || action === "rename" && !text(name, 120) || action !== "rename" && name !== null) throw new PublicPlanningError("invalid");
  const { response, payload } = await request(`/api/planning/projects/${encodeURIComponent(projectId)}/${action}`, { body: JSON.stringify({ expected_revision: expectedRevision, action, name }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS);
  if (response.status === 200) return parsePlanningProjectMutation(payload, projectId);
  failure(payload, response);
}

export async function updatePlanningTask(taskId: string, expectedRevision: number, changes: Record<string, unknown>): Promise<PublicPlanningTaskMutation> {
  if (!TASK_ID.test(taskId) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || !record(changes) || Object.keys(changes).length === 0) throw new PublicPlanningError("invalid");
  const { response, payload } = await request(`/api/planning/tasks/${encodeURIComponent(taskId)}/edit`, { body: JSON.stringify({ expected_revision: expectedRevision, changes }), headers: { "Content-Type": "application/json" }, method: "POST" }, PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS);
  if (response.status === 200) return parsePlanningTaskMutation(payload, taskId);
  failure(payload, response);
}
