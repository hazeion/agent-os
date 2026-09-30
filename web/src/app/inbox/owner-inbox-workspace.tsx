"use client";

import { useEffect, useRef, useState } from "react";
import { type DeliverableReviewAction, type DeliverableReviewPreview, type DeliverableSlot } from "@/lib/project-deliverable-contract";
import { type InboxItem, type InboxOpen, type InboxPage, type InboxView } from "@/lib/owner-inbox-contract";
import { ownerInbox, PublicOwnerInboxError } from "@/lib/public-owner-inbox";
import { resultView } from "../tasks/project-deliverable-editor";

const VIEWS: Array<{ id: InboxView; label: string }> = [{ id: "needs_me", label: "Needs me" }, { id: "unread", label: "Unread" }, { id: "all", label: "All" }];
const SLOTS = ["layout", "products", "steps"] as const;
const LABELS: Record<DeliverableSlot, string> = { layout: "Garage layout", products: "Products and sources", steps: "Implementation order" };
function message(error: unknown): string {
  if (error instanceof PublicOwnerInboxError && error.code === "stale") return "This item changed. Refresh it before reviewing.";
  if (error instanceof PublicOwnerInboxError && error.code === "capacity") return "The Inbox is full. Finish and acknowledge older review items before trying again.";
  return "Mentat could not verify this Inbox item. Refresh before trying again.";
}
function sameHeads(preview: DeliverableReviewPreview, opened: InboxOpen): boolean {
  if (opened.item.kind !== "result_review" || !opened.project || preview.project_id !== opened.project.project.id || preview.project_revision !== opened.project.project.revision || preview.heads.length !== 3) return false;
  return preview.heads.every((head, index) => {
    const current = opened.project!.slots.find((slot) => slot.slot === head.slot);
    return head.slot === SLOTS[index] && current?.versions[0]?.id === head.version_id
      && current.head_revision === head.revision && current.versions[0].content !== null && current.versions[0].origin === head.origin;
  });
}
function stateLabel(item: InboxItem): string {
  if (item.state === "needs_review") return "Needs review";
  if (item.state === "activation_required") return "Project not active";
  if (item.state === "stale") return "Stale";
  if (item.state === "resolved") return "Resolved";
  if (item.state === "checking") return "Needs checking";
  return item.state.charAt(0).toUpperCase() + item.state.slice(1);
}
function runExplanation(item: InboxItem): string {
  if (item.kind !== "run_outcome") return "";
  if (item.state === "checking") return "Mentat cannot yet verify the final outcome. This notice stays open after you acknowledge it.";
  if (item.state === "failed" || item.state === "interrupted") return "This Run ended without a completed result. Acknowledging or dismissing this notice does not retry the work.";
  if (item.state === "completed") return "The Run finished. Review any Project results in their own review item.";
  if (item.state === "stopped" || item.state === "cancelled") return "This Run ended without continuing its work.";
  return "This notice is resolved. Its saved outcome remains available here.";
}
function runOutcomeLabel(run: NonNullable<InboxOpen["run"]>): string {
  if (run.status === "unknown" || !["completed", "failed", "cancelled", "stopped", "interrupted"].includes(run.status)
      || run.partial || !run.terminal_finalized) return "Needs checking";
  return run.status.charAt(0).toUpperCase() + run.status.slice(1);
}
export function OwnerInboxWorkspace() {
  const [view, setView] = useState<InboxView>("needs_me");
  const [page, setPage] = useState<InboxPage | null>(null), [listState, setListState] = useState<"loading" | "ready" | "error">("loading");
  const [detail, setDetail] = useState<InboxOpen | null>(null), [detailState, setDetailState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [notice, setNotice] = useState(""), [detailNotice, setDetailNotice] = useState("");
  const [busy, setBusy] = useState(false), [action, setAction] = useState<DeliverableReviewAction | null>(null);
  const [affected, setAffected] = useState<DeliverableSlot[]>([]), [note, setNote] = useState("");
  const [preview, setPreview] = useState<DeliverableReviewPreview | null>(null);
  const listGeneration = useRef(0), detailGeneration = useRef(0), locked = useRef(false);
  const detailHeading = useRef<HTMLHeadingElement>(null), listHeading = useRef<HTMLHeadingElement>(null);
  const itemButtons = useRef(new Map<string, HTMLButtonElement>()), originatingItem = useRef<string | null>(null);

  async function loadPage(nextView: InboxView, after: string | null = null, preserve = false) {
    const generation = ++listGeneration.current;
    const resetsOlderPages = preserve && after === null && (page?.items.length ?? 0) > 50;
    if (after === null && !preserve) { setListState("loading"); setPage(null); }
    setNotice("");
    try {
      const next = await ownerInbox("page", { view: nextView, after });
      if (generation !== listGeneration.current) return;
      setPage((current) => after === null || !current ? next : {
        ...next, items: [...current.items, ...next.items.filter((entry) => !current.items.some((old) => old.id === entry.id))],
      });
      setListState("ready");
      if (resetsOlderPages) setNotice("Inbox refreshed to newest items. Load more to return to older items.");
    } catch (error) {
      if (generation !== listGeneration.current) return;
      if (after === null && !preserve) setListState("error");
      setNotice(error instanceof PublicOwnerInboxError && error.code === "stale" ? "The list changed. Refresh to continue." : "Inbox is unavailable. Refresh to try again.");
    }
  }
  useEffect(() => {
    let active = true;
    const listToken = listGeneration, detailToken = detailGeneration;
    queueMicrotask(() => {
      if (!active) return;
      const linked = new URL(window.location.href).searchParams.get("item");
      void loadPage("needs_me").then(() => { if (active && linked) void openItem(linked, false); });
    });
    return () => { active = false; listToken.current++; detailToken.current++; };
    // Initial URL handoff runs once; later item openings use explicit actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { if (detailState === "ready") detailHeading.current?.focus(); }, [detailState, detail?.item.id]);

  async function openItem(itemId: string, changeUrl = true) {
    const generation = ++detailGeneration.current;
    setDetail(null); setDetailState("loading"); setDetailNotice(""); setPreview(null); setAction(null); setNote(""); setAffected([]);
    if (changeUrl) window.history.replaceState(null, "", `/inbox?item=${encodeURIComponent(itemId)}`);
    try {
      let opened = await ownerInbox("open", { item_id: itemId });
      if (generation !== detailGeneration.current) return;
      if (opened.item.unread) {
        try {
          const marked = await ownerInbox("mark", { item_id: itemId, action: "read", expected_revision: opened.item.revision });
          if (generation !== detailGeneration.current) return;
          opened = { ...opened, item: { ...opened.item, revision: marked.revision, unread: false } };
          setPage((current) => current && { ...current,
            items: current.items.map((item) => item.id === itemId ? opened.item : item).filter((item) => view !== "unread" || item.unread),
            counts: { ...current.counts, unread: Math.max(0, current.counts.unread - 1) } });
          void loadPage(view, null, true);
        } catch {
          // A lost response is read back once; never submit a second mark.
          opened = await ownerInbox("open", { item_id: itemId });
          if (generation !== detailGeneration.current) return;
          setDetailNotice("Read status was checked again. Refresh the list for current counts.");
        }
      }
      setDetail(opened); setDetailState("ready");
    } catch (error) {
      if (generation !== detailGeneration.current) return;
      setDetailState("error"); setDetailNotice(message(error));
    }
  }
  function back() {
    detailGeneration.current++; setDetail(null); setDetailState("idle"); setDetailNotice(""); setPreview(null);
    window.history.replaceState(null, "", "/inbox");
    const origin = originatingItem.current;
    window.setTimeout(() => (origin && itemButtons.current.get(origin) || listHeading.current)?.focus(), 0);
  }
  function chooseView(next: InboxView) {
    if (next === view) return;
    setView(next); back(); originatingItem.current = null; void loadPage(next);
  }
  async function acknowledge() {
    if (!detail || locked.current) return;
    locked.current = true; setBusy(true); setDetailNotice("");
    try {
      const result = await ownerInbox("mark", { item_id: detail.item.id, action: "acknowledge", expected_revision: detail.item.revision });
      const refreshed = detail.item.kind === "run_outcome" ? await ownerInbox("open", { item_id: detail.item.id }) : null;
      if (refreshed && (refreshed.item.revision !== result.revision || !refreshed.item.acknowledged)) {
        setDetail(refreshed); setDetailNotice("This Run changed while acknowledgment was being checked. Review its current outcome.");
        void loadPage(view, null, true); return;
      }
      const updated: InboxItem = refreshed?.item ?? { ...detail.item, revision: result.revision, unread: false, acknowledged: true };
      setDetail(refreshed ?? { ...detail, item: updated });
      setPage((current) => current && { ...current, items: current.items.map((item) => item.id === updated.id ? updated : item).filter((item) => view !== "unread" || item.unread),
        counts: { ...current.counts, unread: detail.item.unread ? Math.max(0, current.counts.unread - 1) : current.counts.unread } });
      setDetailNotice(detail.item.kind === "run_outcome" ? updated.state === "checking" ? "Seen. Mentat still needs to verify this Run." : updated.state === "resolved" ? "Acknowledged. This notice is resolved." : "Acknowledged. The Run record remains available for review." : "Acknowledged. The result still needs its own review if it remains open.");
      detailHeading.current?.focus();
      void loadPage(view, null, true);
    } catch (error) {
      try { const current = await ownerInbox("open", { item_id: detail.item.id }); setDetail(current); setDetailNotice(current.item.acknowledged ? current.item.kind === "run_outcome" ? "The current Run notice is acknowledged. Review its outcome below." : "Acknowledged. The result review remains separate." : "Acknowledgment could not be verified. " + message(error)); if (current.item.acknowledged) detailHeading.current?.focus(); void loadPage(view, null, true); }
      catch { setDetail(null); setDetailState("error"); setDetailNotice(message(error)); }
    } finally { locked.current = false; setBusy(false); }
  }
  async function dismissRun() {
    if (!detail || detail.item.kind !== "run_outcome" || !detail.item.acknowledged || locked.current) return;
    locked.current = true; setBusy(true); setDetailNotice("");
    try {
      const marked = await ownerInbox("mark", { item_id: detail.item.id, action: "dismiss", expected_revision: detail.item.revision });
      const refreshed = await ownerInbox("open", { item_id: detail.item.id });
      setDetail(refreshed); setDetailNotice(refreshed.item.state === "resolved" && refreshed.item.revision === marked.revision
        ? "Notice dismissed. The Run record remains saved." : "This Run changed while dismissal was being checked. Review its current outcome.");
      detailHeading.current?.focus(); void loadPage(view, null, true);
    } catch (error) {
      try { const current = await ownerInbox("open", { item_id: detail.item.id }); setDetail(current); setDetailNotice(current.item.state === "resolved" ? "This notice is resolved. Review its current outcome." : "Dismissal could not be verified. " + message(error)); void loadPage(view, null, true); }
      catch { setDetail(null); setDetailState("error"); setDetailNotice(message(error)); }
    } finally { locked.current = false; setBusy(false); }
  }
  async function refreshItem() {
    if (!detail || busy) return;
    await openItem(detail.item.id, false);
    void loadPage(view, null, true);
  }
  async function previewDecision() {
    if (detail?.item.kind !== "result_review" || !detail.project || !action || locked.current) return;
    locked.current = true; setBusy(true); setDetailNotice("");
    const request = { item_id: detail.item.id, action, note: action === "accept" ? "" : note.trim(), affected_slots: action === "accept" ? [...SLOTS] : affected };
    try {
      const result = await ownerInbox("preview", request);
      if (!sameHeads(result, detail)) throw new PublicOwnerInboxError("stale");
      setPreview(result);
    } catch (error) { setPreview(null); setDetailNotice(message(error)); }
    finally { locked.current = false; setBusy(false); }
  }
  async function confirmDecision() {
    if (detail?.item.kind !== "result_review" || !detail.project || !preview || locked.current) return;
    if (!sameHeads(preview, detail)) { setPreview(null); setDetailNotice("The displayed results changed. Refresh before reviewing."); return; }
    locked.current = true; setBusy(true); setDetailNotice("");
    let result;
    try {
      result = await ownerInbox("confirm", { item_id: detail.item.id, action: preview.action, note: preview.note,
        affected_slots: preview.affected_slots, confirmation_id: preview.confirmation_id });
    } catch (error) {
      if (error instanceof PublicOwnerInboxError && error.code === "stale") setPreview(null);
      setDetailNotice("The decision could not be verified. " + message(error) + " The exact preview is retained when safe to retry.");
      locked.current = false; setBusy(false); return;
    }
    setPreview(null); setAction(null);
    try {
      const refreshed = await ownerInbox("open", { item_id: detail.item.id });
      setDetail(refreshed);
      setDetailNotice(result.action === "accept" ? "Acceptance recorded." : "Change request recorded.");
      detailHeading.current?.focus();
      void loadPage(view, null, true);
    } catch {
      setDetail(null); setDetailState("error");
      setDetailNotice("Your decision was recorded, but the Inbox could not refresh it. Refresh the list before another action.");
      detailHeading.current?.focus();
    } finally { locked.current = false; setBusy(false); }
  }
  const reviewable = detailState === "ready" && detail?.item.kind === "result_review" && detail.item.state === "needs_review" && !!detail.project && !!detail.review;
  return <section aria-label="Owner Inbox" className="owner-inbox-workspace">
    <div className="owner-inbox-toolbar"><div className="project-context-actions" role="group" aria-label="Inbox views">{VIEWS.map((candidate) => <button aria-pressed={view === candidate.id} disabled={busy} key={candidate.id} onClick={() => chooseView(candidate.id)} type="button">{candidate.label}{page ? ` ${page.counts[candidate.id]}` : ""}</button>)}</div><button disabled={busy} onClick={() => void loadPage(view, null, true)} type="button">Refresh Inbox</button></div>
    <p aria-live="polite" role="status">{notice || (listState === "loading" ? "Loading Inbox…" : listState === "error" ? "Inbox is unavailable." : "")}</p>
    <div className="owner-inbox-layout"><section aria-label="Inbox items"><h2 ref={listHeading} tabIndex={-1}>Inbox items</h2>{page?.items.length ? <ul className="owner-inbox-list">{page.items.map((item) => <li key={item.id}><button aria-current={detail?.item.id === item.id ? "true" : undefined} data-inbox-item-id={item.id} disabled={busy} onClick={() => { originatingItem.current = item.id; void openItem(item.id); }} ref={(element) => { if (element) itemButtons.current.set(item.id, element); else itemButtons.current.delete(item.id); }} type="button"><strong>{item.title}</strong><span>{stateLabel(item)}{item.unread ? " · Unread" : ""}{item.acknowledged ? " · Acknowledged" : ""}{item.kind === "run_outcome" ? ` · Reference ${item.id.slice(11)}` : ""}</span></button></li>)}</ul> : listState === "ready" ? <p>No items in this view.</p> : null}{page?.next_cursor ? <button disabled={busy} onClick={() => void loadPage(view, page.next_cursor)} type="button">Load more</button> : null}</section>
    <section aria-label="Inbox item detail" className="owner-inbox-detail"><h2 ref={detailHeading} tabIndex={-1}>{detail?.item.kind === "run_outcome" ? "Run outcome" : "Review Project results"}</h2>{detailState !== "idle" ? <button disabled={busy} onClick={back} type="button">Back to Inbox items</button> : null}<p aria-live="polite" role="status">{detailNotice || (detailState === "loading" ? "Opening Inbox item…" : "")}</p>
      {detail?.item ? <><h3>{detail.item.title}</h3>{detail.item.kind === "result_review" ? <p>{detail.item.state === "needs_review" ? "These exact saved results need your decision." : detail.item.state === "activation_required" ? "This Project must be active before its results can be reviewed. Its saved versions are below." : detail.item.state === "resolved" ? "This review item is finished. The exact saved versions are below." : "This item no longer names current Project results. Its saved versions are below."}</p> : <p>{runExplanation(detail.item)}</p>}{detail.item.kind === "result_review" && detail.item.state === "resolved" ? <a href="/tasks">Open Projects & Tasks</a> : null}<div className="project-context-actions"><button disabled={busy} onClick={() => void refreshItem()} type="button">Refresh item</button><button disabled={busy || detail.item.acknowledged} onClick={() => void acknowledge()} type="button">Acknowledge</button>{detail.item.kind === "run_outcome" && (detail.item.state === "failed" || detail.item.state === "interrupted") && detail.item.acknowledged ? <button disabled={busy} onClick={() => void dismissRun()} type="button">Dismiss notice</button> : null}</div></> : null}
      {detail?.item.kind === "run_outcome" && detail.run ? <section aria-label="Verified Run outcome"><p><strong>Source:</strong> {detail.run.source === "task_dispatch" ? "Task" : "Agent Console"}</p>{detail.run.work_title ? <p><strong>Related work:</strong> {detail.run.work_title}</p> : detail.run.retired ? <p>The related work title is no longer available.</p> : null}<p><strong>Run started:</strong> {new Date(detail.run.created_at).toLocaleString()}</p><p><strong>Notice reference:</strong> <code>{detail.item.id.slice(11)}</code></p><p><strong>Outcome:</strong> {runOutcomeLabel(detail.run)}</p><p><strong>Notice:</strong> {stateLabel(detail.item)}</p>{detail.run.retired ? <p>This is saved history. The original Run is no longer available for actions.</p> : <p>This notice stays linked to the exact Run. It does not restart work.</p>}</section> : null}
      {detail?.versions ? <section aria-label="Exact retained result versions"><h3>Saved result versions</h3>{detail.versions.map((version) => <section aria-label={`${LABELS[version.slot]} retained version`} key={version.id}><h4>{LABELS[version.slot]} · version {version.revision}</h4>{version.content ? resultView(version.slot, version.content, version.id, version.preview_attachment_id) : <p>Content unavailable.</p>}</section>)}</section> : null}
      {reviewable ? <><p>Review all three current results below. A decision records your review; it does not start Agent work.</p>{SLOTS.map((slot) => { const current = detail.project!.slots.find((entry) => entry.slot === slot)!.versions[0]; return <section aria-label={`${LABELS[slot]} current result`} key={slot}><h3>{LABELS[slot]} · version {current.revision}</h3>{resultView(slot, current.content!, current.id, current.preview_attachment_id)}</section>; })}<div className="project-context-actions"><button aria-pressed={action === "accept"} disabled={busy} onClick={() => { setAction("accept"); setPreview(null); setNote(""); setAffected([]); }} type="button">Accept saved results</button><button aria-pressed={action === "request_changes"} disabled={busy} onClick={() => { setAction("request_changes"); setPreview(null); setNote(""); setAffected([]); }} type="button">Request changes</button></div>{action === "request_changes" ? <><fieldset disabled={busy}><legend>Which results need changes?</legend>{SLOTS.map((slot) => <label key={slot}><input checked={affected.includes(slot)} onChange={(event) => { setAffected((current) => SLOTS.filter((entry) => entry === slot ? event.target.checked : current.includes(entry))); setPreview(null); }} type="checkbox" />{LABELS[slot]}</label>)}</fieldset><label>What should change?<textarea disabled={busy} maxLength={2000} onChange={(event) => { setNote(event.target.value); setPreview(null); }} value={note} /></label></> : null}{action ? <div className="project-context-actions"><button disabled={busy || action === "request_changes" && (!affected.length || !note.trim())} onClick={() => void previewDecision()} type="button">Preview {action === "accept" ? "acceptance" : "change request"}</button><button disabled={busy} onClick={() => { setAction(null); setPreview(null); }} type="button">Cancel review</button></div> : null}{preview ? <section aria-label="Confirm Inbox result review" className="project-context-confirmation"><h3>{preview.action === "accept" ? "Accept these exact versions?" : "Request changes to these exact versions?"}</h3><p>{preview.heads.map((head) => `${LABELS[head.slot]} version ${head.revision}`).join(" · ")}</p>{preview.note ? <p>{preview.note}</p> : null}<div className="project-context-actions"><button disabled={busy} onClick={() => void confirmDecision()} type="button">{preview.action === "accept" ? "Confirm acceptance" : "Send change request"}</button><button disabled={busy} onClick={() => setPreview(null)} type="button">Cancel preview</button></div></section> : null}</> : null}
    </section></div>
  </section>;
}
