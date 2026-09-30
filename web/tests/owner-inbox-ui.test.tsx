import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { JSDOM } from "jsdom";

const origin = "http://127.0.0.1:8890";
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: `${origin}/inbox`, pretendToBeVisual: true });
for (const name of ["document", "HTMLElement", "MouseEvent", "MutationObserver", "Node", "navigator", "window"] as const) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });
const { cleanup, fireEvent, render, screen, waitFor, within } = await import("@testing-library/react");
const { OwnerInboxWorkspace } = await import("../src/app/inbox/owner-inbox-workspace.tsx");
const originalFetch = globalThis.fetch;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; dom.reconfigure({ url: `${origin}/inbox` }); });
const itemId = `inbox_item_${"a".repeat(32)}`;
const projectId = "project_garage";
const versionIds = ["1", "2", "3"].map((digit) => `deliverable_version_${digit.repeat(32)}`);
const slots = (["layout", "products", "steps"] as const).map((slot, index) => ({ id: `deliverable_${String(index + 1).repeat(32)}`, slot, head_revision: 1,
  versions: [{ id: versionIds[index], revision: 1, origin: "owner_edit", source_version_id: null,
    content: slot === "layout" ? { width_mm: 6000, depth_mm: 5000, notes: "Clear bicycle path", openings: [], placements: [] }
      : slot === "products" ? { notes: "Check shelf capacity", items: [] } : { notes: "Measure before buying", steps: [] },
    created_at: 1790035200, preview_attachment_id: slot === "layout" ? `attachment_${"b".repeat(32)}` : null }],
}));
function fixture({ stale = false, loseConfirmOnce = false, loseAckOnce = false, changePreviewHead = false, delayFirstPage = false, extraPage = false, initiallyRead = false } = {}) {
  const calls: Array<{ path: string; method: string; body: Record<string, unknown> | null }> = [];
  const state = { calls, read: initiallyRead, acknowledged: false, resolved: false, revision: 1, decisions: 0, releasePage: null as null | (() => void) };
  const item = () => ({ id: itemId, kind: "result_review", revision: state.revision, created_at: 1790035200,
    unread: !state.read, acknowledged: state.acknowledged, state: stale ? "stale" : state.resolved ? "resolved" : "needs_review", title: stale ? "Retained Project results" : "Review Garage results" });
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input), origin), path = url.pathname, method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : null;
    calls.push({ path, method, body });
    if (path === "/api/inbox") {
      if (extraPage) {
        const first = Array.from({ length: 50 }, (_, index) => ({ ...item(),
          id: `inbox_item_${(100 + index).toString(16).padStart(32, "0")}`,
          title: `Review earlier Project ${index}`, created_at: 1790035300 - index }));
        return Response.json(url.searchParams.has("after")
          ? { items: [item()], next_cursor: null, counts: { needs_me: 51, unread: state.read ? 0 : 51, all: 51 } }
          : { items: first, next_cursor: first.at(-1)!.id, counts: { needs_me: 51, unread: state.read ? 0 : 51, all: 51 } });
      }
      const payload = { items: stale && url.searchParams.get("view") === "needs_me" || state.read && url.searchParams.get("view") === "unread" ? [] : [item()], next_cursor: null,
        counts: { needs_me: stale || state.resolved ? 0 : 1, unread: state.read ? 0 : 1, all: 1 } };
      if (delayFirstPage && calls.filter((call) => call.path === "/api/inbox").length === 1) await new Promise<void>((resolve) => { state.releasePage = resolve; });
      return Response.json(payload);
    }
    if (path === `/api/inbox/${itemId}`) return Response.json({ item: item(), project: stale || state.resolved ? null : { project: { id: projectId, name: "Garage", revision: 1, status: "active" }, slots },
      review: stale || state.resolved ? null : { project_id: projectId, project_name: "Garage", status: "pending", latest: null },
      versions: stale || state.resolved ? slots.map((entry) => ({ ...entry.versions[0], project_id: projectId, slot: entry.slot })) : null });
    if (path === `/api/inbox/${itemId}/mark`) { state.read = true; if (body?.action === "acknowledge") state.acknowledged = true; state.revision++;
      if (loseAckOnce && body?.action === "acknowledge") throw new Error("ack response lost");
      return Response.json({ id: itemId, revision: state.revision, duplicate: false }); }
    if (path === `/api/inbox/${itemId}/review/preview`) return Response.json({ project_id: projectId, project_name: "Garage", project_revision: 1,
      action: body?.action, note: body?.note, affected_slots: body?.affected_slots,
      heads: (["layout", "products", "steps"] as const).map((slot, index) => ({ slot, version_id: changePreviewHead && slot === "products" ? `deliverable_version_${"e".repeat(32)}` : versionIds[index], revision: 1, origin: "owner_edit" })), confirmation_id: "f".repeat(64) });
    if (path === `/api/inbox/${itemId}/review/confirm`) {
      const duplicate = state.resolved;
      if (!duplicate) { state.resolved = true; state.revision++; state.decisions++; }
      if (loseConfirmOnce && !duplicate) throw new Error("response lost after accepted confirmation");
      return Response.json({ id: `deliverable_review_${"d".repeat(32)}`, revision: 1,
        action: body?.action, project_id: projectId, duplicate });
    }
    throw new Error(`Unexpected Inbox transport: ${path}`);
  };
  return state;
}

function runFixture({ uncertain = false, retired = false, changeAfterAck = false, loseDismissOnce = false } = {}) {
  const runId = `inbox_item_${"c".repeat(32)}`;
  const state = { read: false, acknowledged: false, resolved: false, changed: false, revision: 1,
    calls: [] as Array<{ path: string; action?: unknown }> };
  const item = () => ({ id: runId, kind: "run_outcome", revision: state.revision, created_at: 1790035200,
    unread: !state.read, acknowledged: state.acknowledged,
    state: state.resolved ? "resolved" : uncertain || state.changed ? "checking" : "failed",
    title: uncertain || state.changed ? "Agent run needs checking" : "Agent run failed" });
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input), origin), path = url.pathname;
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : null;
    state.calls.push({ path, action: body?.action });
    if (path === "/api/inbox") return Response.json({ items: state.resolved && url.searchParams.get("view") === "needs_me" || state.read && url.searchParams.get("view") === "unread" ? [] : [item()],
      next_cursor: null, counts: { needs_me: state.resolved ? 0 : 1, unread: state.read ? 0 : 1, all: 1 } });
    if (path === `/api/inbox/${runId}`) return Response.json({ item: item(), run: {
      source: "console", status: (uncertain && !retired) || state.changed ? "unknown" : "failed", partial: uncertain || state.changed,
      terminal_finalized: !uncertain && !state.changed, retired, source_revision: state.changed ? 2 : 1,
      work_title: retired ? null : "Garage research", created_at: "2026-09-24T12:00:00+00:00",
    } });
    if (path === `/api/inbox/${runId}/mark`) {
      state.read = true;
      if (body?.action === "acknowledge" || body?.action === "dismiss") state.acknowledged = true;
      if (body?.action === "dismiss") state.resolved = true;
      state.revision++;
      const markedRevision = state.revision;
      if (body?.action === "acknowledge" && changeAfterAck) {
        state.changed = true; state.read = false; state.acknowledged = false; state.revision++;
      }
      if (body?.action === "dismiss" && loseDismissOnce) throw new Error("dismiss response lost");
      return Response.json({ id: runId, revision: markedRevision, duplicate: false });
    }
    throw new Error(`Run notice must not call ${path}`);
  };
  return state;
}

test("verified Run failure is acknowledged and dismissed without Project review controls", async () => {
  const state = runFixture(); render(<OwnerInboxWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: /Agent run failed/u }));
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByRole("heading", { name: "Run outcome" });
  assert.ok(within(detail).getByText(/Source:/u));
  assert.ok(within(detail).getByText(/Garage research/u));
  assert.ok(within(detail).getByText("c".repeat(32)));
  assert.equal(within(detail).queryByRole("link", { name: "Open Runs" }), null);
  assert.equal(within(detail).queryByRole("button", { name: "Accept saved results" }), null);
  assert.equal(within(detail).queryByRole("button", { name: "Dismiss notice" }), null);
  fireEvent.click(within(detail).getByRole("button", { name: "Acknowledge" }));
  const dismiss = await within(detail).findByRole("button", { name: "Dismiss notice" });
  fireEvent.click(dismiss);
  await within(detail).findByText("Notice dismissed. The Run record remains saved.");
  assert.ok(within(detail).getByText(/notice is resolved/u));
  const outcome = within(detail).getByRole("region", { name: "Verified Run outcome" }).textContent ?? "";
  assert.match(outcome, /Outcome: Failed/u);
  assert.match(outcome, /Notice: Resolved/u);
  assert.equal(state.calls.some((call) => call.path.includes("/review/")), false);
  assert.equal(state.calls.filter((call) => call.action === "dismiss").length, 1);
});

test("uncertain Run remains visible after acknowledgment and cannot be dismissed", async () => {
  const state = runFixture({ uncertain: true, retired: true }); render(<OwnerInboxWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: /Agent run needs checking/u }));
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText(/cannot yet verify the final outcome/u);
  assert.ok(within(detail).getByText(/saved history/u));
  assert.ok(within(detail).getByText("The related work title is no longer available."));
  assert.equal(within(detail).queryByRole("link", { name: "Open Runs" }), null);
  fireEvent.click(within(detail).getByRole("button", { name: "Acknowledge" }));
  await within(detail).findByText("Seen. Mentat still needs to verify this Run.");
  assert.equal(within(detail).queryByRole("button", { name: "Dismiss notice" }), null);
  assert.equal(state.resolved, false);
  assert.equal(state.calls.some((call) => call.path.includes("/review/")), false);
});

test("matching Run titles and times retain distinct full notice references", async () => {
  const ids = ["d", "e"].map((digit) => `inbox_item_${digit.repeat(32)}`);
  globalThis.fetch = async () => Response.json({ items: ids.map((id, index) => ({
    id, kind: "run_outcome", revision: 1, created_at: 1790035200 - index,
    unread: true, acknowledged: false, state: "failed", title: "Agent run failed · Garage research · Sep 24, 2026 12:00:00 +0000",
  })), next_cursor: null, counts: { needs_me: 2, unread: 2, all: 2 } });
  render(<OwnerInboxWorkspace />);
  await screen.findByRole("button", { name: new RegExp(ids[0].slice(11), "u") });
  assert.ok(screen.getByRole("button", { name: new RegExp(ids[1].slice(11), "u") }));
});

test("a newer Run outcome prevents a stale acknowledgment success claim", async () => {
  const state = runFixture({ changeAfterAck: true }); render(<OwnerInboxWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: /Agent run failed/u }));
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText(/Garage research/u);
  fireEvent.click(within(detail).getByRole("button", { name: "Acknowledge" }));
  await within(detail).findByText(/This Run changed while acknowledgment was being checked/u);
  assert.equal(state.acknowledged, false);
  assert.equal(within(detail).queryByText("Acknowledged. The Run record remains available for review."), null);
  assert.equal(state.calls.filter((call) => call.action === "acknowledge").length, 1);
});

test("a lost dismissal response reports current resolution without claiming its cause", async () => {
  const state = runFixture({ loseDismissOnce: true }); render(<OwnerInboxWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: /Agent run failed/u }));
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText(/Garage research/u);
  fireEvent.click(within(detail).getByRole("button", { name: "Acknowledge" }));
  fireEvent.click(await within(detail).findByRole("button", { name: "Dismiss notice" }));
  await within(detail).findByText("This notice is resolved. Review its current outcome.");
  assert.equal(state.resolved, true);
  assert.equal(state.calls.filter((call) => call.action === "dismiss").length, 1);
});

test("owner reviews the exact three saved results through item-bound routes only", async () => {
  const state = fixture(); render(<OwnerInboxWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: /Review Garage results/u }));
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText("Clear bicycle path");
  assert.ok(within(detail).getByText("Check shelf capacity"));
  assert.ok(within(detail).getByText("Measure before buying"));
  const content = within(detail).getByRole("heading", { name: "Garage layout · version 1" });
  const accept = within(detail).getByRole("button", { name: "Accept saved results" });
  assert.ok(content.compareDocumentPosition(accept) & Node.DOCUMENT_POSITION_FOLLOWING);
  fireEvent.click(accept);
  fireEvent.click(within(detail).getByRole("button", { name: "Preview acceptance" }));
  await within(detail).findByRole("button", { name: "Confirm acceptance" });
  const confirm = within(detail).getByRole("button", { name: "Confirm acceptance" });
  confirm.focus(); fireEvent.click(confirm);
  await within(detail).findByText("Acceptance recorded.");
  assert.equal(document.activeElement, within(detail).getByRole("heading", { name: "Review Project results" }));
  assert.equal(state.resolved, true);
  assert.equal(state.calls.some((call) => call.path.startsWith("/api/projects/") || call.path.includes("/runs")), false);
  assert.equal(state.calls.filter((call) => call.path.endsWith("/review/confirm")).length, 1);
});

test("a retained stale item can be acknowledged without opening review controls", async () => {
  const state = fixture({ stale: true }); dom.reconfigure({ url: `${origin}/inbox?item=${itemId}` }); render(<OwnerInboxWorkspace />);
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText(/This item no longer names current Project results/u);
  assert.ok(within(detail).getByText("Clear bicycle path"));
  assert.equal(within(detail).queryByRole("button", { name: "Accept saved results" }), null);
  const acknowledge = within(detail).getByRole("button", { name: "Acknowledge" });
  acknowledge.focus(); fireEvent.click(acknowledge);
  await waitFor(() => assert.equal(state.acknowledged, true));
  assert.equal(state.calls.some((call) => call.path.includes("/review/")), false);
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(document.activeElement, within(detail).getByRole("heading", { name: "Review Project results" }));
});

test("changed preview heads and a lost confirmation cannot silently apply another review", async () => {
  const stale = fixture({ changePreviewHead: true }); render(<OwnerInboxWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: /Review Garage results/u }));
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText("Clear bicycle path");
  fireEvent.click(within(detail).getByRole("button", { name: "Accept saved results" }));
  fireEvent.click(within(detail).getByRole("button", { name: "Preview acceptance" }));
  await within(detail).findByText("This item changed. Refresh it before reviewing.");
  assert.equal(within(detail).queryByRole("button", { name: "Confirm acceptance" }), null);
  assert.equal(stale.decisions, 0);
  cleanup(); dom.reconfigure({ url: `${origin}/inbox` });
  const accepted = fixture({ loseConfirmOnce: true }); render(<OwnerInboxWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: /Review Garage results/u }));
  const reopened = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(reopened).findByText("Clear bicycle path");
  fireEvent.click(within(reopened).getByRole("button", { name: "Accept saved results" }));
  fireEvent.click(within(reopened).getByRole("button", { name: "Preview acceptance" }));
  fireEvent.click(await within(reopened).findByRole("button", { name: "Confirm acceptance" }));
  await within(reopened).findByText(/decision could not be verified/u);
  assert.equal(accepted.decisions, 1);
  fireEvent.click(within(reopened).getByRole("button", { name: "Confirm acceptance" }));
  await within(reopened).findByText("Acceptance recorded.");
  assert.equal(accepted.decisions, 1);
  assert.equal(accepted.calls.filter((call) => call.path.endsWith("/review/confirm")).length, 2);
});

test("reading an item removes it from Unread while it stays in Needs me", async () => {
  fixture(); render(<OwnerInboxWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: "Unread 1" }));
  fireEvent.click(await screen.findByRole("button", { name: /Review Garage results/u }));
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText("Clear bicycle path");
  await waitFor(() => assert.equal(screen.queryByRole("button", { name: /Review Garage results/u }), null));
  fireEvent.click(screen.getByRole("button", { name: /Needs me/u }));
  assert.ok(await screen.findByRole("button", { name: /Review Garage results/u }));
});

test("deep-link read waits for the first list and cannot restore stale Unread state", async () => {
  const state = fixture({ delayFirstPage: true }); dom.reconfigure({ url: `${origin}/inbox?item=${itemId}` }); render(<OwnerInboxWorkspace />);
  await waitFor(() => assert.ok(state.releasePage));
  assert.equal(state.calls.some((call) => call.path === `/api/inbox/${itemId}`), false);
  state.releasePage!();
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText("Clear bicycle path");
  await waitFor(() => assert.equal(screen.getByRole("button", { name: "Unread 0" }).getAttribute("aria-pressed"), "false"));
  assert.equal(state.read, true);
});

test("a lost acknowledgment response reads back detail and refreshes list state", async () => {
  const state = fixture({ loseAckOnce: true }); render(<OwnerInboxWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: "All 1" }));
  fireEvent.click(await screen.findByRole("button", { name: /Review Garage results/u }));
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText("Clear bicycle path");
  fireEvent.click(within(detail).getByRole("button", { name: "Acknowledge" }));
  await within(detail).findByText("Acknowledged. The result review remains separate.");
  await waitFor(() => assert.match(screen.getByRole("button", { name: /Review Garage results/u }).textContent ?? "", /Acknowledged/u));
  assert.equal(state.acknowledged, true);
});

test("Back restores focus to the originating Inbox item", async () => {
  fixture(); render(<OwnerInboxWorkspace />);
  const item = await screen.findByRole("button", { name: /Review Garage results/u });
  item.focus(); fireEvent.click(item);
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText("Clear bicycle path");
  fireEvent.click(within(detail).getByRole("button", { name: "Back to Inbox items" }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(document.activeElement, item);
});

test("an action on a loaded older page announces pagination reset and focuses the list heading", async () => {
  fixture({ extraPage: true }); render(<OwnerInboxWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
  const old = await screen.findByRole("button", { name: /Review Garage results/u });
  old.focus(); fireEvent.click(old);
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText("Clear bicycle path");
  await screen.findByText("Inbox refreshed to newest items. Load more to return to older items.");
  fireEvent.click(within(detail).getByRole("button", { name: "Back to Inbox items" }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(document.activeElement, screen.getByRole("heading", { name: "Inbox items" }));
});

test("acknowledging a read item on an older page resets its cursor before Load more", async () => {
  fixture({ extraPage: true, initiallyRead: true }); render(<OwnerInboxWorkspace />);
  fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
  fireEvent.click(await screen.findByRole("button", { name: /Review Garage results/u }));
  const detail = await screen.findByRole("region", { name: "Inbox item detail" });
  await within(detail).findByText("Clear bicycle path");
  fireEvent.click(within(detail).getByRole("button", { name: "Acknowledge" }));
  await screen.findByText("Inbox refreshed to newest items. Load more to return to older items.");
  assert.equal(screen.queryByRole("button", { name: /Review Garage results/u }), null);
  assert.ok(screen.getByRole("button", { name: "Load more" }));
});
