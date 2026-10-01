import { deliverableResult, type DeliverableOperation, type DeliverableResults, type DeliverableProject, type DeliverableReviewConfirmed, type DeliverableReviewPreview, type DeliverableReviewStatus, type DeliverableSlot, type DeliverableVersion } from "./project-deliverable-contract.ts";

export class OwnerInboxContractError extends Error { constructor() { super("owner_inbox_contract_invalid"); } }
export type InboxView = "needs_me" | "unread" | "all";
export type InboxItem = { id: string; kind: "result_review"; revision: number; created_at: number; unread: boolean; acknowledged: boolean; state: "needs_review" | "activation_required" | "stale" | "resolved"; title: string };
export type InboxPage = { items: InboxItem[]; next_cursor: string | null; counts: Record<InboxView, number> };
export type InboxRetainedVersion = DeliverableVersion & { project_id: string; slot: DeliverableSlot };
export type InboxOpen = { item: InboxItem; project: DeliverableProject | null; review: DeliverableReviewStatus | null; versions: InboxRetainedVersion[] | null };
export type InboxOperation = "page" | "open" | "mark" | "preview" | "confirm";
export type InboxResults = { page: InboxPage; open: InboxOpen; mark: { id: string; revision: number; duplicate: boolean }; preview: DeliverableReviewPreview; confirm: DeliverableReviewConfirmed };
export const INBOX_JSON_LIMIT = 512 * 1024;
const ITEM = /^inbox_item_[0-9a-f]{32}$/u;
const SHA = /^[0-9a-f]{64}$/u;
const SLOTS = ["layout", "products", "steps"] as const;
function record(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
function keys(value: Record<string, unknown>, expected: string): boolean { return Object.keys(value).sort().join(",") === expected.split(",").filter(Boolean).sort().join(","); }
function integer(value: unknown, min: number, max: number): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= min && value <= max; }
function itemId(value: unknown): value is string { return typeof value === "string" && ITEM.test(value); }
function limitedText(value: unknown, maximum: number): value is string { return typeof value === "string" && new TextEncoder().encode(value).length <= maximum && !/[\u0000-\u0008\u000B-\u001F\u007F]/u.test(value); }
function affected(value: unknown): value is DeliverableSlot[] { return Array.isArray(value) && value.length >= 1 && value.length <= 3 && value.every((slot) => SLOTS.includes(slot)) && value.join(",") === SLOTS.filter((slot) => value.includes(slot)).join(","); }
function actionFields(value: Record<string, unknown>): boolean {
  return (value.action === "accept" || value.action === "request_changes") && limitedText(value.note, 2000)
    && affected(value.affected_slots) && (value.action === "accept" ? value.note === "" && value.affected_slots.join(",") === SLOTS.join(",") : String(value.note).trim().length > 0);
}
function checkedDeliverable<K extends DeliverableOperation>(operation: K, value: unknown, request: Record<string, unknown>): DeliverableResults[K] {
  try { return deliverableResult(operation, value, request); } catch { throw new OwnerInboxContractError(); }
}
export function inboxRequest(operation: InboxOperation, input: unknown): Record<string, unknown> {
  if (!record(input)) throw new OwnerInboxContractError();
  if (operation === "page") {
    if (!keys(input, "view,after") || !["needs_me", "unread", "all"].includes(String(input.view)) || !(input.after === null || itemId(input.after))) throw new OwnerInboxContractError();
  } else if (operation === "open") {
    if (!keys(input, "item_id") || !itemId(input.item_id)) throw new OwnerInboxContractError();
  } else if (operation === "mark") {
    if (!keys(input, "item_id,action,expected_revision") || !itemId(input.item_id) || !["read", "acknowledge"].includes(String(input.action)) || !integer(input.expected_revision, 1, 16)) throw new OwnerInboxContractError();
  } else if (operation === "preview" || operation === "confirm") {
    if (!keys(input, operation === "preview" ? "item_id,action,note,affected_slots" : "item_id,action,note,affected_slots,confirmation_id")
        || !itemId(input.item_id) || !actionFields(input) || operation === "confirm" && (typeof input.confirmation_id !== "string" || !SHA.test(input.confirmation_id))) throw new OwnerInboxContractError();
  } else throw new OwnerInboxContractError();
  return structuredClone(input);
}
function item(value: unknown): InboxItem {
  if (!record(value) || !keys(value, "id,kind,revision,created_at,unread,acknowledged,state,title") || !itemId(value.id)
      || value.kind !== "result_review" || !integer(value.revision, 1, 16)
      || typeof value.created_at !== "number" || !Number.isFinite(value.created_at) || value.created_at <= 0
      || typeof value.unread !== "boolean" || typeof value.acknowledged !== "boolean"
      || !["needs_review", "activation_required", "stale", "resolved"].includes(String(value.state))
      || !limitedText(value.title, 500) || value.title.length === 0) throw new OwnerInboxContractError();
  return value as InboxItem;
}
export function inboxResult<K extends InboxOperation>(operation: K, raw: unknown, request: Record<string, unknown>): InboxResults[K] {
  if (!record(raw) || !keys(raw, "schema_version,service,runtime,status,data") || raw.schema_version !== 1 || raw.service !== "mentat-local-bridge" || raw.runtime !== "python" || raw.status !== "ready") throw new OwnerInboxContractError();
  return inboxDataResult(operation, raw.data, request);
}
export function inboxDataResult<K extends InboxOperation>(operation: K, value: unknown, request: Record<string, unknown>): InboxResults[K] {
  if (operation === "page") {
    if (!record(value) || !keys(value, "items,next_cursor,counts") || !Array.isArray(value.items) || value.items.length > 50
        || !(value.next_cursor === null || itemId(value.next_cursor) && value.items.length === 50)
        || !record(value.counts) || !keys(value.counts, "needs_me,unread,all")
        || !integer(value.counts.needs_me, 0, 2048) || !integer(value.counts.unread, 0, 2048) || !integer(value.counts.all, 0, 2048)
        || value.counts.needs_me > value.counts.all || value.counts.unread > value.counts.all) throw new OwnerInboxContractError();
    const items = value.items.map(item);
    if (new Set(items.map((entry) => entry.id)).size !== items.length || value.next_cursor !== null && value.next_cursor !== items.at(-1)?.id
        || items.some((entry, index) => index > 0 && (entry.created_at > items[index - 1].created_at || entry.created_at === items[index - 1].created_at && entry.id >= items[index - 1].id))
        || request.view === "needs_me" && items.some((entry) => entry.state === "resolved")
        || request.view === "unread" && items.some((entry) => !entry.unread)) throw new OwnerInboxContractError();
  } else if (operation === "open") {
    if (!record(value) || !keys(value, "item,project,review,versions")) throw new OwnerInboxContractError();
    const selected = item(value.item);
    if (selected.id !== request.item_id || selected.state !== "needs_review" && (value.project !== null || value.review !== null)) throw new OwnerInboxContractError();
    if (selected.state === "needs_review") {
      if (value.versions !== null) throw new OwnerInboxContractError();
      if (!record(value.project) || !record(value.review) || !record(value.project.project) || typeof value.project.project.id !== "string") throw new OwnerInboxContractError();
      const projectId = value.project.project.id;
      const project = checkedDeliverable("project", value.project, { project_id: projectId });
      const review = checkedDeliverable("review-status", value.review, { project_id: projectId });
      if (project.project.status !== "active" || project.slots.length !== 3 || review.status !== "pending" || project.slots.some((slot) => !slot.versions[0]?.content)) throw new OwnerInboxContractError();
    } else {
      if (!Array.isArray(value.versions) || value.versions.length !== 3) throw new OwnerInboxContractError();
      const parsed = value.versions.map((entry, index) => {
        if (!record(entry) || entry.slot !== SLOTS[index] || typeof entry.id !== "string") throw new OwnerInboxContractError();
        return checkedDeliverable("retired-version", entry, { version_id: entry.id });
      });
      if (new Set(parsed.map((entry) => entry.id)).size !== 3 || new Set(parsed.map((entry) => entry.project_id)).size !== 1) throw new OwnerInboxContractError();
    }
  } else if (operation === "mark") {
    if (!record(value) || !keys(value, "id,revision,duplicate") || value.id !== request.item_id || !integer(value.revision, 1, 16) || typeof value.duplicate !== "boolean") throw new OwnerInboxContractError();
  } else if (operation === "preview" || operation === "confirm") {
    if (!record(value) || typeof value.project_id !== "string") throw new OwnerInboxContractError();
    checkedDeliverable(operation === "preview" ? "review-preview" : "review-confirm", value,
      { project_id: value.project_id, action: request.action, note: request.note, affected_slots: request.affected_slots });
  } else throw new OwnerInboxContractError();
  return structuredClone(value) as InboxResults[K];
}
