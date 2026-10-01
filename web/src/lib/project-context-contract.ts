/** Browser-safe Project context contract. No runtime or storage authority. */
export const CONTEXT_OPERATIONS = ["project", "version", "history", "file", "publish", "upload", "discard", "grant-preview", "grant-confirm", "revoke", "prune-preview", "prune-confirm"] as const;
export type ContextOperation = typeof CONTEXT_OPERATIONS[number];
export const CONTEXT_READS: ReadonlySet<ContextOperation> = new Set(["project", "version", "history", "file"]);
export const CONTEXT_UPLOAD_LIMIT = 14 * 1024 * 1024;
export const CONTEXT_JSON_LIMIT = 128 * 1024;
export type ContextFile = { id: string; name: string; mime_type: string; kind: "text" | "image"; byte_size: number; state: string; created_at: string; expires_at: string | null; available: boolean };
export type ContextSummary = { id: string; revision: number; created_at: number };
export type ContextVersion = ContextSummary & { brief: string; project_id: string; retired: boolean; current: boolean; files: ContextFile[]; prune_blocked: "current_version" | "granted_version" | "task_input" | null };
export type ContextGrant = { agent_id: string; context_id: string | null; revision: number; state: "active" | "revoked"; reason: string | null };
export type ContextEditor = { project: { id: string; name: string; revision: number; status: string }; current: ContextVersion | null; versions: ContextSummary[]; staged: ContextFile[]; grants: ContextGrant[] };
export type GrantPreview = { project_id: string; context_id: string; context_revision: number; brief: string; files: ContextFile[]; agent_id: string; agent_name: string; grant_revision: number; confirmation_id: string };
export type GrantResult = { project_id: string; context_id: string; agent_id: string; revision: number; state: "active" | "revoked" };
export type PrunePreview = { context_id: string; revision: number; file_count: number; confirmation_id: string };
export type ContextResults = {
  project: ContextEditor; version: ContextVersion; history: { versions: (ContextSummary & { summary: string })[] };
  file: { file: ContextFile; content_base64: string }; publish: { context_id: string; revision: number };
  upload: { file: ContextFile }; discard: { discarded: true }; "grant-preview": GrantPreview;
  "grant-confirm": GrantResult; revoke: GrantResult; "prune-preview": PrunePreview; "prune-confirm": { pruned: true };
};
export class ContextContractError extends Error { constructor() { super("project_context_invalid"); } }
type RecordValue = Record<string, unknown>;
function requireValue(condition: unknown): asserts condition { if (!condition) throw new ContextContractError(); }
function record(value: unknown): value is RecordValue { return !!value && typeof value === "object" && !Array.isArray(value); }
function exact(value: unknown, fields: string): asserts value is RecordValue { requireValue(record(value) && Object.keys(value).sort().join(",") === fields.split(",").sort().join(",")); }
function integer(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum && value <= maximum; }
function text(value: unknown, maximum: number, empty = false): value is string { return typeof value === "string" && (empty || value.length > 0) && [...value].length <= maximum; }
function brief(value: unknown): value is string { return typeof value === "string" && new TextEncoder().encode(value).length <= 16 * 1024 && !value.includes("\u0000"); }
const IDS = { project_id: /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u, agent_id: /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u, context_id: /^project_context_[0-9a-f]{32}$/u, attachment_id: /^attachment_[0-9a-f]{32}$/u };
function id(value: unknown, key: keyof typeof IDS): value is string { return typeof value === "string" && IDS[key].test(value); }
function confirmation(value: unknown): boolean { return typeof value === "string" && /^[0-9a-f]{64}$/u.test(value); }
function timestamp(value: unknown): boolean { return typeof value === "number" && Number.isFinite(value) && value > 0 && value <= 253402300799; }
function iso(value: unknown): boolean { return typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u.test(value) && Number.isFinite(Date.parse(value)); }
function list(value: unknown, maximum: number, validate: (item: unknown) => void): asserts value is unknown[] { requireValue(Array.isArray(value) && value.length <= maximum); value.forEach(validate); }
function unique(values: unknown[]): void { requireValue(new Set(values).size === values.length); }
const REQUEST_FIELDS: Record<ContextOperation, string> = {
  project: "project_id", version: "context_id", history: "", file: "attachment_id,project_id",
  publish: "project_id,expected_project_revision,expected_revision,brief,attachment_ids,expected_staged_ids",
  upload: "project_id,expected_project_revision,name,content_type,content_base64",
  discard: "project_id,expected_project_revision,attachment_id", "grant-preview": "project_id,context_id,agent_id",
  "grant-confirm": "project_id,context_id,agent_id,confirmation_id,confirmed", revoke: "project_id,context_id,agent_id,expected_revision",
  "prune-preview": "context_id", "prune-confirm": "context_id,confirmation_id,confirmed",
};
export function contextRequest(operation: ContextOperation, value: unknown): RecordValue {
  requireValue(CONTEXT_OPERATIONS.includes(operation));
  const fields = operation === "file" && record(value) && "context_id" in value ? "attachment_id,context_id" : REQUEST_FIELDS[operation];
  exact(value, fields);
  for (const [key, item] of Object.entries(value)) {
    if (key in IDS) requireValue(id(item, key as keyof typeof IDS));
    else if (key === "attachment_ids" || key === "expected_staged_ids") { list(item, 16, (entry) => requireValue(id(entry, "attachment_id"))); unique(item); }
    else if (key.startsWith("expected_")) requireValue(integer(item));
    else if (key === "brief") requireValue(brief(item));
    else if (key === "confirmed") requireValue(item === true);
    else if (key === "confirmation_id") requireValue(confirmation(item));
    else if (key === "name") requireValue(text(item, 240) && !/[\u0000-\u001f\u007f]/u.test(item));
    else if (key === "content_type") requireValue(text(item, 128, true));
    else if (key === "content_base64") requireValue(typeof item === "string" && item.length <= Math.ceil(10 * 1024 * 1024 / 3) * 4 && item.length % 4 === 0 && /^[A-Za-z0-9+/]*={0,2}$/u.test(item));
  }
  return value;
}
function file(value: unknown): void {
  exact(value, "id,name,mime_type,kind,byte_size,state,created_at,expires_at,available");
  requireValue(id(value.id, "attachment_id") && text(value.name, 240) && !/[\u0000-\u001f\u007f]/u.test(value.name));
  requireValue(text(value.mime_type, 128) && /^[a-z0-9.+-]+\/[a-z0-9.+-]+$/u.test(value.mime_type));
  requireValue(["text", "image"].includes(String(value.kind)) && integer(value.byte_size, 0, value.kind === "image" ? 10 * 1024 * 1024 : 2 * 1024 * 1024));
  if (value.kind === "image") requireValue(["image/png", "image/jpeg", "image/webp", "image/gif"].includes(String(value.mime_type)));
  requireValue(["uploading", "staged", "attached", "orphaned", "pending_delete", "deleting", "missing"].includes(String(value.state)) && typeof value.available === "boolean" && iso(value.created_at) && (value.expires_at === null || iso(value.expires_at)));
  if (value.available) requireValue(value.state === "attached" || value.state === "staged");
}
export function parseContextFile(value: unknown): ContextFile { file(value); return value as ContextFile; }
function files(value: unknown): void { list(value, 16, file); unique(value.map((entry) => (entry as RecordValue).id)); }
function summary(value: RecordValue): void { requireValue(id(value.id, "context_id") && integer(value.revision, 1) && timestamp(value.created_at)); }
function version(value: unknown): void {
  exact(value, "id,revision,brief,created_at,project_id,retired,current,files,prune_blocked"); summary(value);
  requireValue(brief(value.brief) && id(value.project_id, "project_id") && typeof value.retired === "boolean" && typeof value.current === "boolean" && !(value.retired && value.current));
  requireValue([null, "current_version", "granted_version", "task_input"].includes(value.prune_blocked as string | null) && (value.current === (value.prune_blocked === "current_version"))); files(value.files);
}
export function parseContextVersion(value: unknown): ContextVersion { version(value); return value as ContextVersion; }
export function contextResult<K extends ContextOperation>(operation: K, value: unknown, request: RecordValue): ContextResults[K] {
  if (operation === "project") {
    exact(value, "project,current,versions,staged,grants"); exact(value.project, "id,name,revision,status");
    requireValue(value.project.id === request.project_id && text(value.project.name, 240) && integer(value.project.revision, 1) && ["active", "paused", "archived"].includes(String(value.project.status)));
    if (value.current !== null) { version(value.current); requireValue((value.current as RecordValue).project_id === request.project_id && (value.current as RecordValue).current === true); }
    list(value.versions, 32, (item) => { exact(item, "id,revision,created_at"); summary(item); }); unique(value.versions.map((item) => (item as RecordValue).id));
    requireValue(value.current === null ? value.versions.length === 0 : (value.versions[0] as RecordValue)?.id === (value.current as RecordValue).id);
    files(value.staged);
    list(value.grants, 128, (item) => { exact(item, "agent_id,context_id,revision,state,reason"); requireValue(id(item.agent_id, "agent_id") && (item.context_id === null || id(item.context_id, "context_id")) && integer(item.revision, 1) && ["active", "revoked"].includes(String(item.state)) && (item.reason === null || ["owner", "project_deleted", "agent_deleted", "restored", "context_pruned"].includes(String(item.reason)))); requireValue(item.state === "active" ? item.context_id !== null && item.reason === null : item.reason !== null); });
    unique(value.grants.map((item) => (item as RecordValue).agent_id));
  } else if (operation === "version") { version(value); requireValue((value as RecordValue).id === request.context_id); }
  else if (operation === "history") { exact(value, "versions"); list(value.versions, 256, (item) => { exact(item, "id,revision,created_at,summary"); summary(item); requireValue(text(item.summary, 120)); }); unique(value.versions.map((item) => (item as RecordValue).id)); }
  else if (operation === "file" || operation === "upload") {
    exact(value, operation === "file" ? "file,content_base64" : "file"); file(value.file); requireValue((value.file as RecordValue).available === true);
    if (operation === "file") { requireValue((value.file as RecordValue).id === request.attachment_id && typeof value.content_base64 === "string" && value.content_base64.length === Math.ceil(Number((value.file as RecordValue).byte_size) / 3) * 4); }
  } else if (operation === "publish") { exact(value, "context_id,revision"); requireValue(id(value.context_id, "context_id") && integer(value.revision, 1) && value.revision === Number(request.expected_revision) + 1); }
  else if (operation === "discard") { exact(value, "discarded"); requireValue(value.discarded === true); }
  else if (operation === "grant-preview") {
    exact(value, "project_id,context_id,context_revision,brief,files,agent_id,agent_name,grant_revision,confirmation_id");
    requireValue(value.project_id === request.project_id && value.context_id === request.context_id && value.agent_id === request.agent_id && integer(value.context_revision, 1) && brief(value.brief) && text(value.agent_name, 240) && integer(value.grant_revision) && confirmation(value.confirmation_id)); files(value.files);
    requireValue((value.files as RecordValue[]).every((item) => item.available));
  } else if (operation === "grant-confirm" || operation === "revoke") { exact(value, "project_id,context_id,agent_id,revision,state"); requireValue(value.project_id === request.project_id && value.context_id === request.context_id && value.agent_id === request.agent_id && integer(value.revision, 1) && value.state === (operation === "revoke" ? "revoked" : "active")); }
  else if (operation === "prune-preview") { exact(value, "context_id,revision,file_count,confirmation_id"); requireValue(value.context_id === request.context_id && integer(value.revision, 1) && integer(value.file_count, 0, 16) && confirmation(value.confirmation_id)); }
  else { exact(value, "pruned"); requireValue(value.pruned === true); }
  return value as ContextResults[K];
}
