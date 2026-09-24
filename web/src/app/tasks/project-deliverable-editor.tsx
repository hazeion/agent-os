"use client";
/* eslint-disable @next/next/no-img-element -- Version-bound private PNGs are already size-limited and served directly with owner authentication. */

import { useEffect, useRef, useState } from "react";
import { deliverableRequest, type DeliverableContent, type DeliverableProject, type DeliverableSlot, type DeliverableVersion, type LayoutContent, type ProductsContent, type StepsContent } from "@/lib/project-deliverable-contract";
import { deliverablePreviewUrl, projectDeliverables, PublicDeliverableError } from "@/lib/public-project-deliverables";
import { ProjectDeliverableReview } from "./project-deliverable-review";

export type DeliverableDraft = { projectRevision: number; slotRevision: number; sourceVersionId: string | null; content: DeliverableContent };
type DraftChange = (slot: DeliverableSlot, update: (current: DeliverableDraft | null) => DeliverableDraft | null) => void;
const LABELS: Record<DeliverableSlot, string> = { layout: "Garage layout", products: "Products and sources", steps: "Implementation order" };
function initialContent(slot: DeliverableSlot): DeliverableContent {
  if (slot === "layout") return { width_mm: 0, depth_mm: 0, notes: "", openings: [], placements: [] };
  if (slot === "products") return { notes: "", items: [] };
  return { notes: "", steps: [] };
}
function errorMessage(error: unknown): string {
  if (error instanceof PublicDeliverableError && error.code === "inbox_capacity") return "The Inbox is full. Your result draft is preserved; finish and acknowledge older review items before saving again.";
  if (error instanceof PublicDeliverableError && ["revision_conflict", "source_changed", "project_changed", "task_changed"].includes(error.code)) return "The Project or saved result changed. Your draft is preserved; refresh and review it before saving.";
  if (error instanceof PublicDeliverableError && ["content_invalid", "content_capacity", "link_invalid", "preview_capacity", "capacity"].includes(error.code)) return "This result needs a smaller or valid layout, link, or document. Your draft is preserved.";
  return "Mentat could not verify this result. Your draft is preserved; refresh before trying again.";
}
function numeric(value: string): number { return value === "" ? 0 : Number(value); }
function markdownText(value: string): string { return value.replace(/[\\`*_{}\[\]()#+\-.!|<>]/gu, (character) => `\\${character}`); }
function downloadDocument(slot: "products" | "steps", content: ProductsContent | StepsContent) {
  const lines = slot === "products" ? ["# Garage products and sources", "", ...(content as ProductsContent).items.flatMap((item) => [
    `- ${markdownText(item.name)} × ${item.quantity} — [Source](${item.url})`, ...(item.notes ? [`  ${markdownText(item.notes)}`] : []),
  ])] : ["# Garage implementation order", "", ...(content as StepsContent).steps.flatMap((step, index) => [
    `${index + 1}. ${markdownText(step.title)}`, ...(step.details ? [`   ${markdownText(step.details)}`] : []),
    ...(step.after.length ? [`   After: ${step.after.map(markdownText).join(", ")}`] : []),
  ])];
  if (content.notes) lines.push("", "## Notes", "", markdownText(content.notes));
  const url = URL.createObjectURL(new Blob([`${lines.join("\n").trimEnd()}\n`], { type: "text/markdown;charset=utf-8" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = slot === "products" ? "garage-products.md" : "garage-implementation.md";
  const revoke = URL.revokeObjectURL.bind(URL);
  document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => revoke(url), 1000);
}
function resultView(slot: DeliverableSlot, content: DeliverableContent, versionId: string, previewId: string | null) {
  if (slot === "layout") {
    const layout = content as LayoutContent;
    return <><p>{layout.width_mm / 1000} m wide × {layout.depth_mm / 1000} m deep</p>{previewId ? <><img alt="Saved dimensioned garage layout" className="project-deliverable-preview" height={900} src={deliverablePreviewUrl(versionId)} width={1200} /><a download="garage-layout.png" href={deliverablePreviewUrl(versionId)}>Download layout image</a></> : null}<p>{layout.notes}</p><p>Placed objects</p><ul>{layout.placements.map((item) => <li key={item.id}>{item.label} ({item.kind}): {item.x_mm} mm from left, {item.y_mm} mm from top; {item.width_mm} × {item.depth_mm} mm</li>)}</ul>{!layout.placements.length ? <p>No objects placed.</p> : null}<p>Doors and windows</p><ul>{layout.openings.map((item, index) => <li key={index}>{item.kind.replaceAll("_", " ")} on {item.edge} wall: {item.offset_mm} mm from corner; {item.width_mm} mm wide</li>)}</ul>{!layout.openings.length ? <p>No openings recorded.</p> : null}</>;
  }
  if (slot === "products") {
    const products = content as ProductsContent;
    return <><ol>{products.items.map((item) => <li key={item.id}>{item.name} × {item.quantity} · <a href={item.url} rel="noopener noreferrer" target="_blank">Source</a>{item.notes ? ` · ${item.notes}` : ""}</li>)}</ol><p>{products.notes}</p><button onClick={() => downloadDocument("products", products)} type="button">Download product document</button></>;
  }
  const steps = content as StepsContent;
  return <><ol>{steps.steps.map((item) => <li key={item.id}><strong>{item.title}</strong>{item.details ? ` · ${item.details}` : ""}{item.after.length ? ` · After: ${item.after.join(", ")}` : ""}</li>)}</ol><p>{steps.notes}</p><button onClick={() => downloadDocument("steps", steps)} type="button">Download implementation document</button></>;
}
function LayoutForm({ value, change, disabled }: { value: LayoutContent; change: (value: LayoutContent) => void; disabled: boolean }) {
  return <div className="project-deliverable-form">
    <p>Enter measured dimensions. Mentat will not guess missing measurements.</p>
    <label>Garage width (mm)<input disabled={disabled} min={1000} max={30000} onChange={(event) => change({ ...value, width_mm: numeric(event.target.value) })} type="number" value={value.width_mm || ""} /></label>
    <label>Garage depth (mm)<input disabled={disabled} min={1000} max={30000} onChange={(event) => change({ ...value, depth_mm: numeric(event.target.value) })} type="number" value={value.depth_mm || ""} /></label>
    <label>Layout notes<textarea disabled={disabled} maxLength={4000} onChange={(event) => change({ ...value, notes: event.target.value })} value={value.notes} /></label>
    <fieldset disabled={disabled}><legend>Objects and storage zones</legend>{value.placements.map((item, index) => {
      const update = (changes: Partial<LayoutContent["placements"][number]>) => change({ ...value, placements: value.placements.map((row, position) => position === index ? { ...row, ...changes } : row) });
      return <div className="project-deliverable-row" key={item.id}>
        <label>Name<input maxLength={80} onChange={(event) => update({ label: event.target.value })} value={item.label} /></label>
        <label>Kind<select onChange={(event) => update({ kind: event.target.value as LayoutContent["placements"][number]["kind"] })} value={item.kind}>{["storage", "workbench", "vehicle", "bike", "clearance", "other"].map((kind) => <option key={kind}>{kind}</option>)}</select></label>
        {(["x_mm", "y_mm", "width_mm", "depth_mm"] as const).map((field) => <label key={field}>{field.replaceAll("_", " ")}<input min={0} onChange={(event) => update({ [field]: numeric(event.target.value) })} type="number" value={item[field]} /></label>)}
        <button onClick={() => change({ ...value, placements: value.placements.filter((row) => row.id !== item.id) })} type="button">Remove {item.label || "object"}</button>
      </div>;
    })}<button disabled={value.placements.length >= 64} onClick={() => change({ ...value, placements: [...value.placements, { id: `item_${crypto.randomUUID().slice(0, 8)}`, kind: "storage", label: "", x_mm: 0, y_mm: 0, width_mm: 500, depth_mm: 500 }] })} type="button">Add object</button></fieldset>
    <fieldset disabled={disabled}><legend>Doors and windows</legend>{value.openings.map((item, index) => {
      const update = (changes: Partial<LayoutContent["openings"][number]>) => change({ ...value, openings: value.openings.map((row, position) => position === index ? { ...row, ...changes } : row) });
      return <div className="project-deliverable-row" key={index}><label>Wall<select onChange={(event) => update({ edge: event.target.value as LayoutContent["openings"][number]["edge"] })} value={item.edge}>{["north", "south", "east", "west"].map((edge) => <option key={edge}>{edge}</option>)}</select></label><label>Kind<select onChange={(event) => update({ kind: event.target.value as LayoutContent["openings"][number]["kind"] })} value={item.kind}>{["door", "garage_door", "window"].map((kind) => <option key={kind}>{kind}</option>)}</select></label><label>Offset (mm)<input min={0} onChange={(event) => update({ offset_mm: numeric(event.target.value) })} type="number" value={item.offset_mm} /></label><label>Width (mm)<input min={300} onChange={(event) => update({ width_mm: numeric(event.target.value) })} type="number" value={item.width_mm} /></label><button onClick={() => change({ ...value, openings: value.openings.filter((_, position) => position !== index) })} type="button">Remove opening</button></div>;
    })}<button disabled={value.openings.length >= 16} onClick={() => change({ ...value, openings: [...value.openings, { edge: "south", kind: "door", offset_mm: 0, width_mm: 900 }] })} type="button">Add opening</button></fieldset>
  </div>;
}
function ProductsForm({ value, change, disabled }: { value: ProductsContent; change: (value: ProductsContent) => void; disabled: boolean }) {
  return <div className="project-deliverable-form"><p>Save source links for review. No products will be purchased.</p><label>Product notes<textarea disabled={disabled} maxLength={4000} onChange={(event) => change({ ...value, notes: event.target.value })} value={value.notes} /></label><fieldset disabled={disabled}><legend>Products</legend>{value.items.map((item, index) => {
    const update = (changes: Partial<ProductsContent["items"][number]>) => change({ ...value, items: value.items.map((row, position) => position === index ? { ...row, ...changes } : row) });
    return <div className="project-deliverable-row" key={item.id}><label>Name<input maxLength={120} onChange={(event) => update({ name: event.target.value })} value={item.name} /></label><label>Quantity<input min={1} max={1000} onChange={(event) => update({ quantity: numeric(event.target.value) })} type="number" value={item.quantity} /></label><label>HTTPS source link<input maxLength={2048} onChange={(event) => update({ url: event.target.value })} type="url" value={item.url} /></label><label>Notes<input maxLength={500} onChange={(event) => update({ notes: event.target.value })} value={item.notes} /></label><button onClick={() => change({ ...value, items: value.items.filter((row) => row.id !== item.id) })} type="button">Remove {item.name || "product"}</button></div>;
  })}<button disabled={value.items.length >= 50} onClick={() => change({ ...value, items: [...value.items, { id: `product_${crypto.randomUUID().slice(0, 8)}`, name: "", quantity: 1, url: "", notes: "" }] })} type="button">Add product</button></fieldset></div>;
}
function StepsForm({ value, change, disabled }: { value: StepsContent; change: (value: StepsContent) => void; disabled: boolean }) {
  const hasDependencies = value.steps.some((step) => step.after.length > 0);
  return <div className="project-deliverable-form"><label>Implementation notes<textarea disabled={disabled} maxLength={4000} onChange={(event) => change({ ...value, notes: event.target.value })} value={value.notes} /></label><fieldset disabled={disabled}><legend>Steps in order</legend>{hasDependencies ? <small>Steps with saved prerequisites cannot be reordered here.</small> : null}{value.steps.map((item, index) => {
    const update = (changes: Partial<StepsContent["steps"][number]>) => change({ ...value, steps: value.steps.map((row, position) => position === index ? { ...row, ...changes } : row) });
    return <div className="project-deliverable-row" key={item.id}><strong>Step {index + 1}</strong><label>Title<input maxLength={120} onChange={(event) => update({ title: event.target.value })} value={item.title} /></label><label>Details<textarea maxLength={1000} onChange={(event) => update({ details: event.target.value })} value={item.details} /></label><div className="project-context-actions"><button disabled={hasDependencies || index === 0} onClick={() => { const next = [...value.steps]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; change({ ...value, steps: next }); }} type="button">Move up</button><button disabled={hasDependencies || index === value.steps.length - 1} onClick={() => { const next = [...value.steps]; [next[index + 1], next[index]] = [next[index], next[index + 1]]; change({ ...value, steps: next }); }} type="button">Move down</button><button onClick={() => change({ ...value, steps: value.steps.filter((row) => row.id !== item.id).map((step) => ({ ...step, after: step.after.filter((id) => id !== item.id) })) })} type="button">Remove step</button></div></div>;
  })}<button disabled={value.steps.length >= 50} onClick={() => change({ ...value, steps: [...value.steps, { id: `step_${crypto.randomUUID().slice(0, 8)}`, title: "", details: "", after: [] }] })} type="button">Add step</button></fieldset></div>;
}

export function ProjectDeliverableEditor({ projectId, drafts, onDraftChange }: { projectId: string; drafts?: Partial<Record<DeliverableSlot, DeliverableDraft | null>>; onDraftChange: DraftChange }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [needsReconciliation, setNeedsReconciliation] = useState(false);
  const [view, setView] = useState<DeliverableProject | null>(null), [viewGeneration, setViewGeneration] = useState(0), [slot, setSlot] = useState<DeliverableSlot>("layout"), [selected, setSelected] = useState<DeliverableVersion | null>(null);
  const mounted = useRef(true), locked = useRef(false);
  const published = useRef<{ slot: DeliverableSlot; versionId: string; draft: DeliverableDraft } | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const current = view?.slots.find((item) => item.slot === slot);
  const draft = drafts?.[slot] ?? null;
  const stale = !!draft && !!view && (draft.projectRevision !== view.project.revision || draft.slotRevision !== (current?.head_revision ?? 0) || draft.sourceVersionId !== (current?.versions[0]?.id ?? null));
  let canSave = false;
  if (draft && view?.project.status === "active" && !stale && !needsReconciliation) {
    try { deliverableRequest("publish", { project_id: projectId, slot, content: draft.content, expected_project_revision: draft.projectRevision, expected_slot_revision: draft.slotRevision, source_version_id: draft.sourceVersionId, associated_task_id: null, expected_task_revision: null }); canSave = true; } catch { /* Keep the incomplete draft. */ }
  }
  async function perform(action: () => Promise<unknown>) {
    if (locked.current) return; locked.current = true; setBusy(true); setNotice("");
    try { await action(); } catch (error) { if (mounted.current) setNotice(errorMessage(error)); }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  async function refresh(): Promise<"current" | "history" | false> {
    const data = await projectDeliverables("project", { project_id: projectId });
    if (!mounted.current) return false;
    setView(data); setViewGeneration((currentGeneration) => currentGeneration + 1); setSelected(null);
    const pending = published.current;
    if (pending) {
      const slotView = data.slots.find((item) => item.slot === pending.slot);
      if (!slotView?.versions.some((item) => item.id === pending.versionId)) {
        setNeedsReconciliation(true);
        return false;
      }
      onDraftChange(pending.slot, (currentDraft) => currentDraft === pending.draft ? null : currentDraft);
      published.current = null;
      setNeedsReconciliation(false);
      return slotView.versions[0]?.id === pending.versionId ? "current" : "history";
    }
    setNeedsReconciliation(false);
    return "current";
  }
  function beginEdit() {
    if (!view) return;
    const head = current?.versions[0];
    onDraftChange(slot, () => ({ projectRevision: view.project.revision, slotRevision: current?.head_revision ?? 0, sourceVersionId: head?.id ?? null,
      content: head?.content ? structuredClone(head.content) : initialContent(slot) }));
    setSelected(null);
  }
  function changeContent(value: DeliverableContent) { onDraftChange(slot, (currentDraft) => currentDraft ? { ...currentDraft, content: value } : null); }
  async function save() {
    if (!draft || !canSave) return;
    let result: { version_id: string; revision: number };
    try {
      result = await projectDeliverables("publish", { project_id: projectId, slot, content: draft.content, expected_project_revision: draft.projectRevision,
        expected_slot_revision: draft.slotRevision, source_version_id: draft.sourceVersionId, associated_task_id: null, expected_task_revision: null });
    } catch (error) {
      if (!(error instanceof PublicDeliverableError) || ["revision_conflict", "source_changed", "project_changed", "task_changed", "unavailable", "invalid_response"].includes(error.code)) setNeedsReconciliation(true);
      throw error;
    }
    published.current = { slot, versionId: result.version_id, draft };
    setNeedsReconciliation(true);
    try {
      const verified = await refresh();
      if (mounted.current) setNotice(verified === "history" ? `Version ${result.revision} was saved, and a newer version is now current. Review the history before editing.` : verified ? `${LABELS[slot]} saved as a new version. No Agent work was started.` : `Version ${result.revision} was accepted, but the saved list has not caught up. Your draft remains; refresh before editing.`);
    } catch {
      if (mounted.current) setNotice(`Version ${result.revision} was accepted, but the saved list could not refresh. Your draft remains; refresh before editing.`);
    }
  }
  async function inspect(versionId: string) { const item = await projectDeliverables("version", { project_id: projectId, version_id: versionId }); if (mounted.current) setSelected(item); }
  const shown = selected ?? (current?.versions[0]?.content ? { ...current.versions[0], slot, content: current.versions[0].content } : null);
  return <section aria-label="Project results" className="project-context-panel">
    <div className="project-context-heading"><h3>Project results</h3><button aria-expanded={open} disabled={busy} onClick={() => { setOpen(!open); if (!open && !view) void perform(refresh); }} type="button">{open ? "Hide results" : "Open results"}</button></div>
    {open ? <div className="project-context-body"><p>Keep a dimensioned layout, linked products, and an order of work. Saved versions remain available for review.</p><p aria-live="polite" role="status">{busy ? "Checking…" : notice}</p><div className="project-context-actions"><button disabled={busy} onClick={() => void perform(refresh)} type="button">Refresh results</button></div>
      <div aria-label="Result type" className="project-context-actions">{(["layout", "products", "steps"] as const).map((kind) => <button aria-pressed={slot === kind} disabled={busy} key={kind} onClick={() => { setSlot(kind); setSelected(null); }} type="button">{LABELS[kind]}</button>)}</div>
      {view ? <><h4>{LABELS[slot]}</h4><div className="project-context-actions"><button disabled={busy || !!draft || view.project.status !== "active"} onClick={beginEdit} type="button">{current ? "Edit latest version" : "Create result"}</button></div>
        {stale ? <div className="project-context-confirmation"><p>The Project or saved result changed. Your draft is preserved.</p><button disabled={busy} onClick={() => { onDraftChange(slot, () => null); beginEdit(); }} type="button">Use current version</button></div> : null}
        {draft ? <><p>Editing version {draft.slotRevision + 1}. Saving creates history; it does not start an Agent.</p>{slot === "layout" ? <LayoutForm change={(value) => changeContent(value)} disabled={busy || stale} value={draft.content as LayoutContent} /> : slot === "products" ? <ProductsForm change={(value) => changeContent(value)} disabled={busy || stale} value={draft.content as ProductsContent} /> : <StepsForm change={(value) => changeContent(value)} disabled={busy || stale} value={draft.content as StepsContent} />}<div className="project-context-actions"><button disabled={busy || !canSave} onClick={() => void perform(save)} type="button">Save result version</button><button disabled={busy} onClick={() => onDraftChange(slot, () => null)} type="button">Discard draft</button></div></> : null}
        {current ? <><p>Saved versions</p><ul>{current.versions.map((item) => <li key={item.id}><button disabled={busy} onClick={() => void perform(() => inspect(item.id))} type="button">View version {item.revision}</button>{item.revision === current.head_revision ? " · latest" : ""}</li>)}</ul></> : <p>No saved {LABELS[slot].toLowerCase()} yet.</p>}
        {shown?.content ? <section aria-label="Saved Project result"><h5>Version {shown.revision}</h5>{resultView(slot, shown.content, shown.id, shown.preview_attachment_id)}</section> : null}
        {view.project.status === "active" ? <ProjectDeliverableReview hasDrafts={Object.values(drafts ?? {}).some(Boolean)} key={`${viewGeneration}:${view.project.revision}:${view.slots.map((item) => item.versions[0]?.id ?? "").join(":")}`} projectId={projectId} projectView={view} renderResult={resultView} /> : null}
      </> : !busy ? <p>Project results are unavailable. Refresh to try again.</p> : null}
    </div> : null}
  </section>;
}

export function RetiredDeliverableHistory() {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [versions, setVersions] = useState<Array<{ id: string; project_id: string; slot: DeliverableSlot; revision: number }>>([]), [selected, setSelected] = useState<DeliverableVersion | null>(null);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const mounted = useRef(true), locked = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function perform(action: () => Promise<void>) { if (locked.current) return; locked.current = true; setBusy(true); setNotice(""); try { await action(); } catch (error) { if (mounted.current) setNotice(errorMessage(error)); } finally { locked.current = false; if (mounted.current) setBusy(false); } }
  async function refresh() { const result = await projectDeliverables("retired-history", {}); if (mounted.current) { setVersions(result.versions); setNextOffset(result.next_offset); setSelected(null); } }
  async function loadMore() { if (nextOffset === null) return; const result = await projectDeliverables("retired-history", { offset: nextOffset }); if (mounted.current) { setVersions((current) => [...current, ...result.versions.filter((item) => !current.some((previous) => previous.id === item.id))]); setNextOffset(result.next_offset); } }
  return <section aria-label="Retained Project results" className="project-context-panel"><button aria-expanded={open} disabled={busy} onClick={() => { setOpen(!open); if (!open) void perform(refresh); }} type="button">Retained Project results</button>{open ? <div className="project-context-body"><p>Results kept after an old Project was deleted remain separate from any new Project with the same name.</p><p role="status">{busy ? "Checking…" : notice}</p><button disabled={busy} onClick={() => void perform(refresh)} type="button">Refresh retained results</button><ul>{versions.map((item) => <li key={item.id}><span>{LABELS[item.slot]} · version {item.revision} · Project {item.project_id}</span><button disabled={busy} onClick={() => void perform(async () => { const result = await projectDeliverables("retired-version", { version_id: item.id }); if (mounted.current) setSelected(result); })} type="button">View retained version</button></li>)}</ul>{nextOffset !== null ? <button disabled={busy} onClick={() => void perform(loadMore)} type="button">Load more retained results</button> : null}{!versions.length && !busy ? <p>No retained Project results.</p> : null}{selected?.content && selected.slot ? <section aria-label="Retained result version"><h4>{LABELS[selected.slot]} · version {selected.revision}</h4>{resultView(selected.slot, selected.content, selected.id, selected.preview_attachment_id)}</section> : null}</div> : null}</section>;
}
