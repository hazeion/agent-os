import { parseContextFile, parseContextVersion, type ContextFile, type ContextVersion } from "./project-context-contract.ts";

export type TaskInputVersion = { id: string; revision: number; task_revision: number; agent_id: string; context_id: string; context_revision: number; project_brief: string; grant_revision: number; instructions: string; created_at: number; files: ContextFile[] };
export type TaskInputEditor = { task: { id: string; title: string; revision: number; project_id: string | null; project_status: "active" | "paused" | "archived" | null; assigned_agent_id: string | null }; input_revision: number; expected_task_token: string; version: TaskInputVersion | null; versions: { id: string; revision: number; context_id: string; created_at: number }[]; eligible_contexts: { context: ContextVersion; grant_revision: number }[] };
export type TaskInputRequest = { task_id: string; project_id: string; agent_id: string; expected_task_revision: number; expected_input_revision: number; context_id: string; expected_grant_revision: number; expected_task_token: string; instructions: string; attachment_ids: string[] };
export class TaskInputContractError extends Error { constructor() { super("task_input_invalid"); } }
type RecordValue = Record<string, unknown>;
function requireValue(condition: unknown): asserts condition { if (!condition) throw new TaskInputContractError(); }
function record(value: unknown): value is RecordValue { return !!value && typeof value === "object" && !Array.isArray(value); }
function exact(value: unknown, fields: string): asserts value is RecordValue { requireValue(record(value) && Object.keys(value).sort().join(",") === fields.split(",").sort().join(",")); }
function integer(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum && value <= maximum; }
const IDS = { task_id: /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u, project_id: /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u, agent_id: /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u, context_id: /^project_context_[0-9a-f]{32}$/u, input_id: /^task_input_[0-9a-f]{32}$/u, attachment_id: /^attachment_[0-9a-f]{32}$/u };
function id(value: unknown, kind: keyof typeof IDS): value is string { return typeof value === "string" && IDS[kind].test(value); }
function instructions(value: unknown): value is string {
  if (typeof value !== "string" || value.includes("\u0000") || new TextEncoder().encode(value).length > 16 * 1024) return false;
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) { const next = value.charCodeAt(++index); if (!(next >= 0xdc00 && next <= 0xdfff)) return false; }
    else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
}
function timestamp(value: unknown): boolean { return typeof value === "number" && Number.isFinite(value) && value > 0 && value <= 253402300799; }

export function taskInputRequest(value: unknown): TaskInputRequest {
  exact(value, "task_id,project_id,agent_id,expected_task_revision,expected_input_revision,context_id,expected_grant_revision,expected_task_token,instructions,attachment_ids");
  requireValue(id(value.task_id, "task_id") && id(value.project_id, "project_id") && id(value.agent_id, "agent_id") && id(value.context_id, "context_id"));
  requireValue(integer(value.expected_task_revision, 1) && integer(value.expected_input_revision) && integer(value.expected_grant_revision, 1) && typeof value.expected_task_token === "string" && /^[0-9a-f]{64}$/u.test(value.expected_task_token) && instructions(value.instructions));
  requireValue(Array.isArray(value.attachment_ids) && value.attachment_ids.length <= 8 && value.attachment_ids.every((item: unknown) => id(item, "attachment_id")) && new Set(value.attachment_ids).size === value.attachment_ids.length);
  return value as TaskInputRequest;
}

export function parseTaskInputVersion(value: unknown): TaskInputVersion {
  exact(value, "id,revision,task_revision,agent_id,context_id,context_revision,project_brief,grant_revision,instructions,created_at,files");
  requireValue(id(value.id, "input_id") && id(value.agent_id, "agent_id") && id(value.context_id, "context_id") && integer(value.revision, 1) && integer(value.task_revision, 1) && integer(value.context_revision, 1) && integer(value.grant_revision, 1) && instructions(value.instructions) && instructions(value.project_brief) && timestamp(value.created_at));
  requireValue(Array.isArray(value.files) && value.files.length <= 8);
  const files = value.files.map(parseContextFile); requireValue(new Set(files.map((item) => item.id)).size === files.length);
  return value as TaskInputVersion;
}

export function taskInputEditor(value: unknown, taskId: string, selectedId?: string): TaskInputEditor {
  exact(value, "task,input_revision,expected_task_token,version,versions,eligible_contexts"); exact(value.task, "id,title,revision,project_id,project_status,assigned_agent_id");
  requireValue(value.task.id === taskId && id(taskId, "task_id") && typeof value.task.title === "string" && [...value.task.title].length > 0 && [...value.task.title].length <= 160 && integer(value.task.revision, 1));
  requireValue((value.task.project_id === null && value.task.project_status === null || id(value.task.project_id, "project_id") && ["active", "paused", "archived"].includes(String(value.task.project_status))) && (value.task.assigned_agent_id === null || id(value.task.assigned_agent_id, "agent_id")));
  requireValue(integer(value.input_revision) && typeof value.expected_task_token === "string" && /^[0-9a-f]{64}$/u.test(value.expected_task_token) && Array.isArray(value.versions) && value.versions.length <= 32 && Array.isArray(value.eligible_contexts) && value.eligible_contexts.length <= 32);
  value.versions.forEach((item: unknown) => { exact(item, "id,revision,context_id,created_at"); requireValue(id(item.id, "input_id") && id(item.context_id, "context_id") && integer(item.revision, 1) && timestamp(item.created_at)); });
  requireValue(new Set(value.versions.map((item: RecordValue) => item.id)).size === value.versions.length && (value.versions.length === 0 ? value.input_revision === 0 : value.versions[0].revision === value.input_revision));
  const projectId = value.task.project_id;
  const eligible = value.eligible_contexts.map((item: unknown) => { exact(item, "context,grant_revision"); requireValue(integer(item.grant_revision, 1)); return { context: parseContextVersion(item.context), grant_revision: item.grant_revision }; });
  requireValue(new Set(eligible.map((item) => item.context.id)).size === eligible.length && eligible.every((item) => item.context.project_id === projectId && !item.context.retired));
  if (value.version !== null) { const selected = parseTaskInputVersion(value.version); requireValue(value.versions.some((item: RecordValue) => item.id === selected.id && item.revision === selected.revision && item.context_id === selected.context_id)); if (selectedId !== undefined) requireValue(selected.id === selectedId); }
  else requireValue(value.versions.length === 0 && selectedId === undefined);
  return value as TaskInputEditor;
}

export function taskInputPublished(value: unknown, request: TaskInputRequest): { input_id: string; revision: number } {
  exact(value, "input_id,revision"); requireValue(id(value.input_id, "input_id") && integer(value.revision, 1) && value.revision === request.expected_input_revision + 1);
  return value as { input_id: string; revision: number };
}

export type RetiredTaskInputSummary = { id: string; revision: number; created_at: number; summary: string };
export function retiredTaskInputHistory(value: unknown): { versions: RetiredTaskInputSummary[] } {
  exact(value, "versions"); requireValue(Array.isArray(value.versions) && value.versions.length <= 256);
  for (const item of value.versions) { exact(item, "id,revision,created_at,summary"); requireValue(id(item.id, "input_id") && integer(item.revision, 1) && timestamp(item.created_at) && typeof item.summary === "string" && [...item.summary].length > 0 && [...item.summary].length <= 120); }
  requireValue(new Set(value.versions.map((item: RecordValue) => item.id)).size === value.versions.length);
  return value as { versions: RetiredTaskInputSummary[] };
}
export function taskInputPrunePreview(value: unknown, inputId: string): { input_id: string; revision: number; file_count: number; confirmation_id: string } {
  exact(value, "input_id,revision,file_count,confirmation_id");
  requireValue(id(inputId, "input_id") && value.input_id === inputId && integer(value.revision, 1) && integer(value.file_count, 0, 8) && typeof value.confirmation_id === "string" && /^[0-9a-f]{64}$/u.test(value.confirmation_id));
  return value as { input_id: string; revision: number; file_count: number; confirmation_id: string };
}
export function taskInputPruned(value: unknown): { pruned: true } { exact(value, "pruned"); requireValue(value.pruned === true); return value as { pruned: true }; }
