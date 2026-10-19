"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { type DeliverableContent, type DeliverableProject, type DeliverableReviewAction, type DeliverableReviewPreview, type DeliverableReviewStatus, type DeliverableSlot } from "@/lib/project-deliverable-contract";
import { projectDeliverables, PublicDeliverableError } from "@/lib/public-project-deliverables";

const SLOTS = ["layout", "products", "steps"] as const;
const LABELS: Record<DeliverableSlot, string> = { layout: "Garage layout", products: "Products and sources", steps: "Implementation order" };

function failure(error: unknown): string {
  if (error instanceof PublicDeliverableError && error.code === "incomplete") return "Save all three results before asking for a review.";
  if (error instanceof PublicDeliverableError && ["stale", "confirmation_conflict", "project_unavailable"].includes(error.code)) return "The Project, results, or review changed. Refresh the results and preview the decision again.";
  if (error instanceof PublicDeliverableError && error.code === "capacity") return "The review history is full. No decision was recorded.";
  if (error instanceof PublicDeliverableError && error.code === "inbox_capacity") return "The Inbox is full. No decision was recorded; finish and acknowledge older review items before trying again.";
  return "Mentat could not verify the review. Refresh and try again.";
}

type RenderResult = (slot: DeliverableSlot, content: DeliverableContent, versionId: string, previewId: string | null) => ReactNode;
function matchesDisplayedHeads(preview: DeliverableReviewPreview, projectView: DeliverableProject): boolean {
  return preview.project_id === projectView.project.id && preview.project_revision === projectView.project.revision
    && preview.heads.every((head) => {
      const current = projectView.slots.find((item) => item.slot === head.slot);
      return current?.versions[0]?.id === head.version_id && current.head_revision === head.revision
        && current.versions[0].content !== null && current.versions[0].origin === head.origin;
    });
}

export function ProjectDeliverableReview({ projectId, projectView, hasDrafts, renderResult }: { projectId: string; projectView: DeliverableProject; hasDrafts: boolean; renderResult: RenderResult }) {
  const [status, setStatus] = useState<DeliverableReviewStatus | null>(null);
  const [action, setAction] = useState<DeliverableReviewAction | null>(null);
  const [note, setNote] = useState("");
  const [affected, setAffected] = useState<DeliverableSlot[]>([]);
  const [preview, setPreview] = useState<DeliverableReviewPreview | null>(null);
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const serial = useRef(false), generation = useRef(0);

  useEffect(() => {
    const current = ++generation.current;
    let cancelled = false;
    void projectDeliverables("review-status", { project_id: projectId }).then(
      (result) => { if (!cancelled && generation.current === current) { setStatus(result); setPreview(null); setNotice(""); } },
      () => { if (!cancelled && generation.current === current) { setStatus(null); setPreview(null); setNotice("Review status is unavailable. Refresh before making a decision."); } },
    );
    return () => { cancelled = true; };
  }, [projectId, projectView]);

  async function refreshStatus() {
    const current = ++generation.current;
    let result: DeliverableReviewStatus;
    try { result = await projectDeliverables("review-status", { project_id: projectId }); }
    catch (error) { if (generation.current === current) setStatus(null); throw error; }
    if (generation.current === current) setStatus(result);
    return result;
  }
  async function perform(work: () => Promise<void>) {
    if (serial.current) return;
    serial.current = true; setBusy(true); setNotice("");
    try { await work(); } catch (error) { setNotice(failure(error)); }
    finally { serial.current = false; setBusy(false); }
  }
  async function previewDecision() {
    if (!status || status.status === "incomplete" || !action || hasDrafts) return;
    const selected = action === "accept" ? [...SLOTS] : affected;
    const result = await projectDeliverables("review-preview", {
      project_id: projectId, action, note: action === "accept" ? "" : note.trim(), affected_slots: selected,
    });
    if (!matchesDisplayedHeads(result, projectView)) {
      setPreview(null);
      throw new PublicDeliverableError("stale");
    }
    setPreview(result);
  }
  async function confirmDecision() {
    if (!preview || hasDrafts) return;
    if (!matchesDisplayedHeads(preview, projectView)) { setPreview(null); throw new PublicDeliverableError("stale"); }
    let result;
    try {
      result = await projectDeliverables("review-confirm", {
        project_id: projectId, action: preview.action, note: preview.note,
        affected_slots: preview.affected_slots, confirmation_id: preview.confirmation_id,
      });
    } catch (error) {
      if (error instanceof PublicDeliverableError && ["stale", "confirmation_conflict", "project_unavailable"].includes(error.code)) setPreview(null);
      throw error;
    }
    setPreview(null);
    try {
      const refreshed = await refreshStatus();
      setNotice(refreshed.latest?.id === result.id && refreshed.latest.current
        ? result.action === "accept" ? "Acceptance recorded." : "Change request recorded."
        : "Your decision was recorded, but the current results have changed. Review the latest versions.");
    } catch {
      setStatus(null);
      setNotice("Your decision was recorded, but its current status could not be checked. Refresh review status.");
    }
  }
  function selectAction(next: DeliverableReviewAction) {
    setAction(next); setNote(""); setAffected([]); setPreview(null); setNotice("");
  }
  function toggleSlot(slot: DeliverableSlot, selected: boolean) {
    setAffected((current) => SLOTS.filter((item) => item === slot ? selected : current.includes(item)));
    setPreview(null);
  }

  return <section aria-label="Review Project results" className="project-context-panel project-deliverable-review">
    <div className="project-context-heading"><h4>Review all three results</h4><button disabled={busy} onClick={() => void perform(async () => { await refreshStatus(); setPreview(null); })} type="button">Refresh review status</button></div>
    <p>Review the saved garage layout, product sources, and implementation order together. A decision records your review; it does not start Agent work.</p>
    <p aria-live="polite" role="status">{busy ? "Checking review…" : notice}</p>
    {status?.status === "incomplete" ? <p>Save all three result types before reviewing the bundle.</p>
      : status?.status === "accept" ? <p>The current three results are accepted.</p>
      : status?.status === "request_changes" ? <p>Changes were requested for the current results.</p>
      : status?.status === "pending" ? <p>The current results need your review.</p> : <p>Review status is being checked.</p>}
    {status?.latest && !status.latest.current ? <p>An earlier review remains in history. New result versions need a fresh decision.</p> : null}
    {status?.latest?.current && status.latest.action === "request_changes" ? <p>Requested changes to {status.latest.affected_slots.map((slot) => LABELS[slot]).join(", ")}: {status.latest.note}</p> : null}
    {hasDrafts ? <p>Save or discard open result drafts before reviewing the saved versions.</p> : null}
    {status && status.status !== "incomplete" ? <>
      <div className="project-context-actions"><button aria-pressed={action === "accept"} disabled={busy || hasDrafts} onClick={() => selectAction("accept")} type="button">Accept saved results</button><button aria-pressed={action === "request_changes"} disabled={busy || hasDrafts} onClick={() => selectAction("request_changes")} type="button">Request changes</button></div>
      {action === "request_changes" ? <><fieldset disabled={busy || hasDrafts}><legend>Which results need changes?</legend>{SLOTS.map((slot) => <label key={slot}><input checked={affected.includes(slot)} onChange={(event) => toggleSlot(slot, event.target.checked)} type="checkbox" />{LABELS[slot]}</label>)}</fieldset><label>What should change?<textarea disabled={busy || hasDrafts} maxLength={2000} onChange={(event) => { setNote(event.target.value); setPreview(null); }} value={note} /></label></> : null}
      {action ? <div className="project-context-actions"><button disabled={busy || hasDrafts || action === "request_changes" && (!affected.length || !note.trim())} onClick={() => void perform(previewDecision)} type="button">Preview {action === "accept" ? "acceptance" : "change request"}</button><button disabled={busy} onClick={() => { setAction(null); setPreview(null); }} type="button">Cancel review</button></div> : null}
      {preview && !hasDrafts && matchesDisplayedHeads(preview, projectView) ? <div aria-label="Confirm Project result review" className="project-context-confirmation"><p>{preview.action === "accept" ? "Accept these exact saved versions?" : "Request changes to these exact saved versions?"}</p><p>Review the current saved content below. A previously selected history version above is not part of this decision.</p>{preview.heads.map((head) => {
        const current = projectView.slots.find((item) => item.slot === head.slot)!.versions[0];
        return <section aria-label={`${LABELS[head.slot]} current review version`} key={head.slot}><h5>{LABELS[head.slot]} · current version {head.revision}{preview.action === "request_changes" && preview.affected_slots.includes(head.slot) ? " · needs changes" : ""}</h5>{renderResult(head.slot, current.content!, head.version_id, current.preview_attachment_id)}</section>;
      })}{preview.note ? <p>{preview.note}</p> : null}<div className="project-context-actions"><button disabled={busy} onClick={() => void perform(confirmDecision)} type="button">{preview.action === "accept" ? "Confirm acceptance" : "Send change request"}</button><button disabled={busy} onClick={() => setPreview(null)} type="button">Cancel preview</button></div></div> : null}
    </> : null}
  </section>;
}
