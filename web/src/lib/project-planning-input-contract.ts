import { parseContextFile, parseContextVersion, type ContextFile, type ContextVersion } from "./project-context-contract.ts";

export type ProjectInputVersion = { id: string; revision: number; project_revision: number; lead_role_id: string; agent_id: string; context_id: string; context_revision: number; project_brief: string; grant_revision: number; instructions: string; created_at: number; files: ContextFile[] };
export type ProjectInputEditor = { project: { id: string; name: string; revision: number; status: "active" | "paused" | "archived" }; lead: { id: string | null; revision: number; agent_id: string | null; agent_name: string | null; status: "unassigned" | "unready" | "stale" | "context_bound"; reasons: string[] }; context: ContextVersion | null; grant_revision: number | null; input_revision: number; scope_token: string; selection_token: string; save_available: boolean; version: ProjectInputVersion | null; versions: { id: string; revision: number; context_id: string; created_at: number }[] };
export type ProjectInputSave = { project_id: string; expected_project_revision: number; lead_role_id: string; expected_lead_revision: number; context_id: string; expected_grant_revision: number; expected_input_revision: number; scope_token: string; selection_token: string; action_id: string; instructions: string; attachment_ids: string[] };
export type ProjectInputReconcile = { project_id: string; action_id: string; scope_token: string };
export type ProjectInputOperation = "project" | "version" | "publish" | "reconcile";
export type ProjectInputResults = { project: ProjectInputEditor; version: ProjectInputEditor; publish: { input_id: string; revision: number; status: "saved" | "committed_needs_review" }; reconcile: { status: "not_found" | "committed_needs_review"; input_id: string | null; revision: number | null } };
export class ProjectInputContractError extends Error { constructor() { super("project_input_invalid"); } }
type RecordValue = Record<string, unknown>;
function requireValue(condition: unknown): asserts condition { if (!condition) throw new ProjectInputContractError(); }
function record(value: unknown): value is RecordValue { return !!value && typeof value === "object" && !Array.isArray(value); }
function exact(value: unknown, fields: string): asserts value is RecordValue { requireValue(record(value) && Object.keys(value).sort().join(",") === fields.split(",").sort().join(",")); }
function integer(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum && value <= maximum; }
function timestamp(value: unknown): boolean { return typeof value === "number" && Number.isFinite(value) && value > 0 && value <= 253402300799; }
const IDS = { project_id: /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u, input_id: /^project_input_[0-9a-f]{32}$/u, role_id: /^lead_role_[0-9a-f]{32}$/u, agent_id: /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u, context_id: /^project_context_[0-9a-f]{32}$/u, attachment_id: /^attachment_[0-9a-f]{32}$/u, action_id: /^project_input_action_[0-9a-f]{32}$/u };
function id(value: unknown, kind: keyof typeof IDS): value is string { return typeof value === "string" && IDS[kind].test(value); }
function hex64(value: unknown): value is string { return typeof value === "string" && /^[0-9a-f]{64}$/u.test(value); }
function boundedText(value: unknown): value is string {
  if (typeof value !== "string" || value.includes("\u0000") || new TextEncoder().encode(value).length > 16 * 1024) return false;
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) { const next = value.charCodeAt(++index); if (!(next >= 0xdc00 && next <= 0xdfff)) return false; }
    else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
}

export function projectInputRequest(operation: ProjectInputOperation, value: unknown): RecordValue {
  exact(value, operation === "project" ? "project_id" : operation === "version" ? "project_id,input_id"
    : operation === "reconcile" ? "project_id,action_id,scope_token"
    : "project_id,expected_project_revision,lead_role_id,expected_lead_revision,context_id,expected_grant_revision,expected_input_revision,scope_token,selection_token,action_id,instructions,attachment_ids");
  requireValue(id(value.project_id, "project_id"));
  if (operation === "version") requireValue(id(value.input_id, "input_id"));
  if (operation === "reconcile") requireValue(id(value.action_id, "action_id") && hex64(value.scope_token));
  if (operation === "publish") {
    requireValue(id(value.lead_role_id, "role_id") && id(value.context_id, "context_id") && id(value.action_id, "action_id")
      && integer(value.expected_project_revision, 1) && integer(value.expected_lead_revision, 1, 32)
      && integer(value.expected_grant_revision, 1) && integer(value.expected_input_revision, 0, 32)
      && hex64(value.scope_token) && hex64(value.selection_token) && boundedText(value.instructions));
    requireValue(Array.isArray(value.attachment_ids) && value.attachment_ids.length <= 8
      && value.attachment_ids.every((item: unknown) => id(item, "attachment_id"))
      && new Set(value.attachment_ids).size === value.attachment_ids.length);
  }
  return value;
}

function version(value: unknown): ProjectInputVersion {
  exact(value, "id,revision,project_revision,lead_role_id,agent_id,context_id,context_revision,project_brief,grant_revision,instructions,created_at,files");
  requireValue(id(value.id, "input_id") && id(value.lead_role_id, "role_id") && id(value.agent_id, "agent_id") && id(value.context_id, "context_id")
    && integer(value.revision, 1, 32) && integer(value.project_revision, 1) && integer(value.context_revision, 1)
    && integer(value.grant_revision, 1) && boundedText(value.project_brief) && boundedText(value.instructions) && timestamp(value.created_at));
  requireValue(Array.isArray(value.files) && value.files.length <= 8);
  let files: ContextFile[];
  try { files = value.files.map(parseContextFile); } catch { throw new ProjectInputContractError(); }
  requireValue(new Set(files.map((item) => item.id)).size === files.length && files.filter((item) => item.kind === "image").length <= 1);
  return value as ProjectInputVersion;
}

export function projectInputEditor(value: unknown, request: RecordValue): ProjectInputEditor {
  exact(value, "project,lead,context,grant_revision,input_revision,scope_token,selection_token,save_available,version,versions");
  exact(value.project, "id,name,revision,status");
  requireValue(value.project.id === request.project_id && id(value.project.id, "project_id")
    && typeof value.project.name === "string" && [...value.project.name].length > 0 && [...value.project.name].length <= 240
    && integer(value.project.revision, 1) && ["active", "paused", "archived"].includes(String(value.project.status)));
  exact(value.lead, "id,revision,agent_id,agent_name,status,reasons");
  requireValue((value.lead.id === null || id(value.lead.id, "role_id")) && integer(value.lead.revision, 0, 32)
    && (value.lead.agent_id === null || id(value.lead.agent_id, "agent_id"))
    && (value.lead.agent_name === null || typeof value.lead.agent_name === "string" && [...value.lead.agent_name].length <= 120)
    && ["unassigned", "unready", "stale", "context_bound"].includes(String(value.lead.status))
    && Array.isArray(value.lead.reasons) && value.lead.reasons.length <= 5
    && value.lead.reasons.every((item: unknown) => typeof item === "string" && ["project_inactive", "agent_changed", "context_grant_needed", "context_changed", "grant_changed"].includes(item)));
  let context: ContextVersion | null;
  try { context = value.context === null ? null : parseContextVersion(value.context); }
  catch { throw new ProjectInputContractError(); }
  requireValue(context === null || context.project_id === request.project_id && context.current && !context.retired);
  requireValue(integer(value.input_revision, 0, 32) && hex64(value.scope_token) && hex64(value.selection_token)
    && typeof value.save_available === "boolean"
    && (value.grant_revision === null || integer(value.grant_revision, 1))
    && (!value.save_available || value.project.status === "active" && value.lead.status === "context_bound"
      && context !== null && value.grant_revision !== null && value.input_revision < 32));
  requireValue(Array.isArray(value.versions) && value.versions.length <= 32);
  for (const item of value.versions) { exact(item, "id,revision,context_id,created_at"); requireValue(id(item.id, "input_id") && id(item.context_id, "context_id") && integer(item.revision, 1, 32) && timestamp(item.created_at)); }
  requireValue(new Set(value.versions.map((item: RecordValue) => item.id)).size === value.versions.length
    && (value.versions.length === 0 ? value.input_revision === 0 : value.versions[0].revision === value.input_revision));
  if (value.version !== null) {
    const selected = version(value.version);
    requireValue(value.versions.some((item: RecordValue) => item.id === selected.id && item.revision === selected.revision)
      && (request.input_id === undefined || selected.id === request.input_id));
  } else requireValue(value.versions.length === 0);
  return value as ProjectInputEditor;
}

export function projectInputPublished(value: unknown, request: RecordValue): { input_id: string; revision: number; status: "saved" | "committed_needs_review" } {
  exact(value, "input_id,revision,status");
  requireValue(id(value.input_id, "input_id") && integer(value.revision, 1, 32)
    && value.revision === Number(request.expected_input_revision) + 1
    && ["saved", "committed_needs_review"].includes(String(value.status)));
  return value as { input_id: string; revision: number; status: "saved" | "committed_needs_review" };
}

export function projectInputReconciled(value: unknown): { status: "not_found" | "committed_needs_review"; input_id: string | null; revision: number | null } {
  exact(value, "status,input_id,revision");
  requireValue(value.status === "not_found" ? value.input_id === null && value.revision === null
    : value.status === "committed_needs_review" && id(value.input_id, "input_id") && integer(value.revision, 1, 32));
  return value as { status: "not_found" | "committed_needs_review"; input_id: string | null; revision: number | null };
}

export function projectInputResult<K extends ProjectInputOperation>(operation: K, value: unknown, request: RecordValue): ProjectInputResults[K] {
  return (operation === "publish" ? projectInputPublished(value, request)
    : operation === "reconcile" ? projectInputReconciled(value)
      : projectInputEditor(value, request)) as ProjectInputResults[K];
}
