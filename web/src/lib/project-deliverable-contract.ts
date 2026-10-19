export class DeliverableContractError extends Error { constructor() { super("deliverable_contract_invalid"); } }

export type DeliverableSlot = "layout" | "products" | "steps";
export type LayoutContent = { width_mm: number; depth_mm: number; notes: string; openings: Array<{ edge: "north" | "south" | "east" | "west"; offset_mm: number; width_mm: number; kind: "door" | "garage_door" | "window" }>; placements: Array<{ id: string; kind: "storage" | "workbench" | "vehicle" | "bike" | "clearance" | "other"; label: string; x_mm: number; y_mm: number; width_mm: number; depth_mm: number }> };
export type ProductsContent = { notes: string; items: Array<{ id: string; name: string; quantity: number; url: string; notes: string }> };
export type StepsContent = { notes: string; steps: Array<{ id: string; title: string; details: string; after: string[] }> };
export type DeliverableContent = LayoutContent | ProductsContent | StepsContent;
export type DeliverableVersion = { id: string; project_id?: string; slot?: DeliverableSlot; revision: number; origin: "owner_edit"; source_version_id: string | null; content: DeliverableContent | null; created_at: number; preview_attachment_id: string | null };
export type DeliverableProject = { project: { id: string; name: string; revision: number; status: "active" | "paused" | "archived" }; slots: Array<{ id: string; slot: DeliverableSlot; head_revision: number; versions: DeliverableVersion[] }> };
export type DeliverablePublished = { slot: DeliverableSlot; slot_id: string; version_id: string; revision: number; origin: "owner_edit"; preview_attachment_id: string | null };
export type RetiredDeliverable = { id: string; project_id: string; slot: DeliverableSlot; revision: number; origin: "owner_edit"; created_at: number };
export type DeliverablePreview = { version_id: string; content_base64: string; sha256: string; byte_size: number };
export type DeliverableReviewAction = "accept" | "request_changes";
export type DeliverableReviewStatus = { project_id: string; project_name: string; status: "incomplete" | "pending" | DeliverableReviewAction; latest: null | { id: string; revision: number; action: DeliverableReviewAction; note: string; affected_slots: DeliverableSlot[]; created_at: number; current: boolean } };
export type DeliverableReviewPreview = { project_id: string; project_name: string; project_revision: number; action: DeliverableReviewAction; note: string; affected_slots: DeliverableSlot[]; heads: Array<{ slot: DeliverableSlot; version_id: string; revision: number; origin: "owner_edit" }>; confirmation_id: string };
export type DeliverableReviewConfirmed = { id: string; revision: number; action: DeliverableReviewAction; project_id: string; duplicate: boolean };
export type DeliverableOperation = "project" | "version" | "retired-history" | "retired-version" | "preview" | "publish" | "review-status" | "review-preview" | "review-confirm";
export type DeliverableResults = { project: DeliverableProject; version: DeliverableVersion; "retired-history": { versions: RetiredDeliverable[]; next_offset: number | null }; "retired-version": DeliverableVersion; preview: DeliverablePreview; publish: DeliverablePublished; "review-status": DeliverableReviewStatus; "review-preview": DeliverableReviewPreview; "review-confirm": DeliverableReviewConfirmed };
export const DELIVERABLE_READS = new Set<DeliverableOperation>(["project", "version", "retired-history", "retired-version", "preview", "review-status"]);
export const DELIVERABLE_JSON_LIMIT = 128 * 1024;
export const DELIVERABLE_PREVIEW_LIMIT = 3 * 1024 * 1024;

const PROJECT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const VERSION = /^deliverable_version_[0-9a-f]{32}$/u;
const REVIEW = /^deliverable_review_[0-9a-f]{32}$/u;
const SLOT_ID = /^deliverable_[0-9a-f]{32}$/u;
const ATTACHMENT = /^attachment_[0-9a-f]{32}$/u;
const ITEM = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/u;
const SHA = /^[0-9a-f]{64}$/u;
const SLOTS = new Set(["layout", "products", "steps"]);
function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function keys(value: Record<string, unknown>, expected: string): boolean { return Object.keys(value).sort().join(",") === expected.split(",").sort().join(","); }
function integer(value: unknown, low: number, high: number): value is number { return Number.isSafeInteger(value) && (value as number) >= low && (value as number) <= high; }
function text(value: unknown, maximum: number, required = false): value is string { return typeof value === "string" && !/[\x00-\x08\x0b-\x1f]/u.test(value) && new TextEncoder().encode(value.trim()).length <= maximum && (!required || !!value.trim()); }
function slot(value: unknown): value is DeliverableSlot { return typeof value === "string" && SLOTS.has(value); }
function reviewAction(value: unknown): value is DeliverableReviewAction { return value === "accept" || value === "request_changes"; }
function affectedSlots(value: unknown): value is DeliverableSlot[] {
  return Array.isArray(value) && value.length >= 1 && value.length <= 3 && value.every(slot)
    && value.every((item, index) => index === 0 || ["layout", "products", "steps"].indexOf(value[index - 1]) < ["layout", "products", "steps"].indexOf(item));
}
function reviewNote(value: unknown): value is string { return text(value, 2000) && value === value.trim(); }
function previewId(value: unknown): value is string | null { return value === null || typeof value === "string" && ATTACHMENT.test(value); }
function sourceId(value: unknown): value is string | null { return value === null || typeof value === "string" && VERSION.test(value); }
function safeUrl(value: unknown): value is string {
  if (typeof value !== "string" || !value || value.length > 2048 || /[\x00-\x20\\<>()\[\]"']/u.test(value)) return false;
  let url: URL; try { url = new URL(value); } catch { return false; }
  return url.protocol === "https:" && !!url.hostname && url.hostname.includes(".") && /[a-z]{2,}$/u.test(url.hostname.split(".").at(-1) ?? "")
    && !url.username && !url.password && (!url.port || url.port === "443") && !url.hash && !url.hostname.endsWith(".")
    && !/\.(?:local|localhost|localdomain|internal|test|invalid)$/u.test(url.hostname);
}
function validContent(kind: DeliverableSlot, value: unknown): value is DeliverableContent {
  if (!record(value)) return false;
  try { if (new TextEncoder().encode(JSON.stringify(value)).length > 64 * 1024) return false; } catch { return false; }
  if (kind === "layout") {
    if (!keys(value, "width_mm,depth_mm,notes,openings,placements") || !integer(value.width_mm, 1000, 30000) || !integer(value.depth_mm, 1000, 30000) || !text(value.notes, 4000) || !Array.isArray(value.openings) || value.openings.length > 16 || !Array.isArray(value.placements) || value.placements.length > 64) return false;
    const width = value.width_mm as number, depth = value.depth_mm as number; const ids = new Set<string>();
    for (const raw of value.openings) {
      if (!record(raw) || !keys(raw, "edge,offset_mm,width_mm,kind") || !["north", "south", "east", "west"].includes(String(raw.edge)) || !["door", "garage_door", "window"].includes(String(raw.kind))) return false;
      const length = raw.edge === "north" || raw.edge === "south" ? width : depth;
      if (!integer(raw.offset_mm, 0, length) || !integer(raw.width_mm, 300, length) || raw.offset_mm + raw.width_mm > length) return false;
    }
    for (const raw of value.placements) {
      if (!record(raw) || !keys(raw, "id,kind,label,x_mm,y_mm,width_mm,depth_mm") || typeof raw.id !== "string" || !ITEM.test(raw.id) || ids.has(raw.id) || !["storage", "workbench", "vehicle", "bike", "clearance", "other"].includes(String(raw.kind)) || !text(raw.label, 80, true) || !integer(raw.x_mm, 0, width) || !integer(raw.y_mm, 0, depth) || !integer(raw.width_mm, 100, width) || !integer(raw.depth_mm, 100, depth) || raw.x_mm + raw.width_mm > width || raw.y_mm + raw.depth_mm > depth) return false;
      ids.add(raw.id);
    }
    return true;
  }
  if (kind === "products") {
    if (!keys(value, "items,notes") || !text(value.notes, 4000) || !Array.isArray(value.items) || value.items.length > 50) return false;
    const ids = new Set<string>();
    for (const raw of value.items) {
      if (!record(raw) || !keys(raw, "id,name,quantity,url,notes") || typeof raw.id !== "string" || !ITEM.test(raw.id) || ids.has(raw.id) || !text(raw.name, 120, true) || !integer(raw.quantity, 1, 1000) || !safeUrl(raw.url) || !text(raw.notes, 500)) return false;
      ids.add(raw.id);
    }
    return true;
  }
  if (!keys(value, "notes,steps") || !text(value.notes, 4000) || !Array.isArray(value.steps) || value.steps.length > 50) return false;
  const ids = new Set<string>();
  for (const raw of value.steps) {
    if (!record(raw) || !keys(raw, "id,title,details,after") || typeof raw.id !== "string" || !ITEM.test(raw.id) || ids.has(raw.id) || !text(raw.title, 120, true) || !text(raw.details, 1000) || !Array.isArray(raw.after) || raw.after.length > 8 || raw.after.some((id: unknown) => typeof id !== "string" || !ids.has(id)) || new Set(raw.after).size !== raw.after.length) return false;
    ids.add(raw.id);
  }
  return true;
}
function version(value: unknown, expectedKind?: DeliverableSlot, listing = false): DeliverableVersion {
  if (!record(value) || !keys(value, listing ? "id,revision,origin,source_version_id,content,created_at,preview_attachment_id" : "id,project_id,slot,revision,origin,source_version_id,content,created_at,preview_attachment_id")) throw new DeliverableContractError();
  const kind = listing ? expectedKind : value.slot;
  if (!slot(kind) || typeof value.id !== "string" || !VERSION.test(value.id) || !integer(value.revision, 1, 32)
      || value.origin !== "owner_edit" || !sourceId(value.source_version_id)
      || typeof value.created_at !== "number" || !Number.isFinite(value.created_at) || value.created_at <= 0
      || !previewId(value.preview_attachment_id) || (kind === "layout") !== (value.preview_attachment_id !== null)
      || !listing && (typeof value.project_id !== "string" || !PROJECT.test(value.project_id))) throw new DeliverableContractError();
  if (value.content !== null && !validContent(kind, value.content) || value.content === null && !listing) throw new DeliverableContractError();
  return structuredClone(value) as DeliverableVersion;
}
export function deliverableRequest(operation: DeliverableOperation, input: unknown): Record<string, unknown> {
  if (!record(input)) throw new DeliverableContractError();
  const fields = { project: "project_id", version: "project_id,version_id", "retired-history": "", "retired-version": "version_id", preview: "version_id", publish: "project_id,slot,content,expected_project_revision,expected_slot_revision,source_version_id,associated_task_id,expected_task_revision", "review-status": "project_id", "review-preview": "project_id,action,note,affected_slots", "review-confirm": "project_id,action,note,affected_slots,confirmation_id" } as const;
  if (!(operation in fields) || (operation === "retired-history" ? !(keys(input, "") || keys(input, "offset")) : !keys(input, fields[operation]))) throw new DeliverableContractError();
  if (operation === "retired-history" && "offset" in input && (!integer(input.offset, 0, 250) || input.offset % 50 !== 0)) throw new DeliverableContractError();
  if ("project_id" in input && (typeof input.project_id !== "string" || !PROJECT.test(input.project_id)) || "version_id" in input && (typeof input.version_id !== "string" || !VERSION.test(input.version_id))) throw new DeliverableContractError();
  if (operation === "publish") {
    if (!slot(input.slot) || !validContent(input.slot, input.content) || !integer(input.expected_project_revision, 1, Number.MAX_SAFE_INTEGER) || !integer(input.expected_slot_revision, 0, 31)
      || !sourceId(input.source_version_id) || (input.expected_slot_revision === 0) !== (input.source_version_id === null)
      || !(input.associated_task_id === null || typeof input.associated_task_id === "string" && TASK.test(input.associated_task_id))
      || !(input.expected_task_revision === null || integer(input.expected_task_revision, 1, Number.MAX_SAFE_INTEGER))
      || (input.associated_task_id === null) !== (input.expected_task_revision === null)) throw new DeliverableContractError();
  }
  if (operation === "review-preview" || operation === "review-confirm") {
    if (!reviewAction(input.action) || !reviewNote(input.note) || !affectedSlots(input.affected_slots)
        || input.action === "accept" && (input.note !== "" || input.affected_slots.join(",") !== "layout,products,steps")
        || input.action === "request_changes" && input.note === ""
        || operation === "review-confirm" && (typeof input.confirmation_id !== "string" || !SHA.test(input.confirmation_id))) throw new DeliverableContractError();
  }
  return structuredClone(input);
}
export function deliverableResult<K extends DeliverableOperation>(operation: K, value: unknown, request: Record<string, unknown>): DeliverableResults[K] {
  if (operation === "project") {
    if (!record(value) || !keys(value, "project,slots") || !record(value.project) || !keys(value.project, "id,name,revision,status")
        || value.project.id !== request.project_id || !text(value.project.name, 120, true) || !integer(value.project.revision, 1, Number.MAX_SAFE_INTEGER)
        || !["active", "paused", "archived"].includes(String(value.project.status)) || !Array.isArray(value.slots) || value.slots.length > 3) throw new DeliverableContractError();
    const seen = new Set<string>();
    for (const raw of value.slots) {
      if (!record(raw) || !keys(raw, "id,slot,head_revision,versions") || typeof raw.id !== "string" || !SLOT_ID.test(raw.id)
          || !slot(raw.slot) || seen.has(raw.slot) || !integer(raw.head_revision, 1, 32)
          || !Array.isArray(raw.versions) || raw.versions.length !== raw.head_revision) throw new DeliverableContractError();
      seen.add(raw.slot);
      for (const [index, entry] of raw.versions.entries()) {
        const parsed = version(entry, raw.slot, true);
        if (parsed.revision !== raw.head_revision - index || (index === 0) !== (parsed.content !== null)) throw new DeliverableContractError();
      }
    }
  } else if (operation === "version" || operation === "retired-version") {
    const parsed = version(value);
    if (parsed.id !== request.version_id || operation === "version" && parsed.project_id !== request.project_id) throw new DeliverableContractError();
  } else if (operation === "retired-history") {
    if (!record(value) || !keys(value, "versions,next_offset") || !Array.isArray(value.versions) || value.versions.length > 50
        || value.next_offset !== null && value.versions.length !== 50
        || !(value.next_offset === null || integer(value.next_offset, 50, 250) && value.next_offset % 50 === 0 && value.next_offset === Number(request.offset ?? 0) + 50)) throw new DeliverableContractError();
    for (const entry of value.versions) {
      if (!record(entry) || !keys(entry, "id,project_id,slot,revision,origin,created_at") || typeof entry.id !== "string" || !VERSION.test(entry.id)
          || typeof entry.project_id !== "string" || !PROJECT.test(entry.project_id) || !slot(entry.slot)
          || !integer(entry.revision, 1, 32) || entry.origin !== "owner_edit"
          || typeof entry.created_at !== "number" || !Number.isFinite(entry.created_at) || entry.created_at <= 0) throw new DeliverableContractError();
    }
  } else if (operation === "preview") {
    if (!record(value) || !keys(value, "version_id,content_base64,sha256,byte_size") || value.version_id !== request.version_id
        || typeof value.content_base64 !== "string" || value.content_base64.length > 3 * 1024 * 1024 || !/^[A-Za-z0-9+/]+={0,2}$/u.test(value.content_base64)
        || typeof value.sha256 !== "string" || !SHA.test(value.sha256) || !integer(value.byte_size, 1, 2 * 1024 * 1024)) throw new DeliverableContractError();
  } else if (operation === "publish") {
    if (!record(value) || !keys(value, "slot,slot_id,version_id,revision,origin,preview_attachment_id")
        || value.slot !== request.slot || typeof value.slot_id !== "string" || !SLOT_ID.test(value.slot_id)
        || typeof value.version_id !== "string" || !VERSION.test(value.version_id)
        || !integer(value.revision, 1, 32) || value.revision !== (request.expected_slot_revision as number) + 1
        || value.origin !== "owner_edit"
        || !previewId(value.preview_attachment_id) || (value.slot === "layout") !== (value.preview_attachment_id !== null)) throw new DeliverableContractError();
  } else if (operation === "review-status") {
    if (!record(value) || !keys(value, "project_id,project_name,status,latest") || value.project_id !== request.project_id
        || !text(value.project_name, 120, true) || !["incomplete", "pending", "accept", "request_changes"].includes(String(value.status))) throw new DeliverableContractError();
    if (value.latest !== null) {
      const latest = value.latest;
      if (!record(latest) || !keys(latest, "id,revision,action,note,affected_slots,created_at,current") || typeof latest.id !== "string" || !REVIEW.test(latest.id)
          || !integer(latest.revision, 1, 256) || !reviewAction(latest.action) || !reviewNote(latest.note)
          || !affectedSlots(latest.affected_slots) || latest.action === "accept" && latest.affected_slots.join(",") !== "layout,products,steps"
          || latest.action === "accept" && latest.note !== "" || latest.action === "request_changes" && latest.note === ""
          || typeof latest.created_at !== "number" || !Number.isFinite(latest.created_at) || latest.created_at <= 0
          || typeof latest.current !== "boolean" || latest.current && value.status !== latest.action) throw new DeliverableContractError();
    } else if (value.status === "accept" || value.status === "request_changes") throw new DeliverableContractError();
  } else if (operation === "review-preview") {
    if (!record(value) || !keys(value, "project_id,project_name,project_revision,action,note,affected_slots,heads,confirmation_id")
        || value.project_id !== request.project_id || !text(value.project_name, 120, true)
        || !integer(value.project_revision, 1, Number.MAX_SAFE_INTEGER) || value.action !== request.action || value.note !== request.note
        || !affectedSlots(value.affected_slots) || value.affected_slots.join(",") !== (request.affected_slots as string[]).join(",")
        || !Array.isArray(value.heads) || value.heads.length !== 3 || typeof value.confirmation_id !== "string" || !SHA.test(value.confirmation_id)) throw new DeliverableContractError();
    for (const [index, head] of value.heads.entries()) {
      if (!record(head) || !keys(head, "slot,version_id,revision,origin") || head.slot !== ["layout", "products", "steps"][index]
          || typeof head.version_id !== "string" || !VERSION.test(head.version_id) || !integer(head.revision, 1, 32) || head.origin !== "owner_edit") throw new DeliverableContractError();
    }
  } else if (operation === "review-confirm") {
    if (!record(value) || !keys(value, "id,revision,action,project_id,duplicate")
        || typeof value.id !== "string" || !REVIEW.test(value.id) || !integer(value.revision, 1, 256)
        || value.action !== request.action || value.project_id !== request.project_id || typeof value.duplicate !== "boolean") throw new DeliverableContractError();
  } else throw new DeliverableContractError();
  return structuredClone(value) as DeliverableResults[K];
}
