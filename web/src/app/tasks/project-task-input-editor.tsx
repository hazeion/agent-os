"use client";

import { useEffect, useRef, useState } from "react";
import { projectContextFileUrl } from "@/lib/public-project-context";
import { publishTaskInputs, PublicTaskInputError, readTaskInputs, readRetiredTaskInputs, readRetiredTaskInput, previewTaskInputPrune, confirmTaskInputPrune } from "@/lib/public-task-inputs";
import type { TaskInputEditor as EditorData, TaskInputVersion, RetiredTaskInputSummary } from "@/lib/task-input-contract";

export type TaskInputDraft = { projectId: string; taskToken: string; inputRevision: number; instructions: string; contextId: string; selected: string[] };
type DraftChange = (change: (current: TaskInputDraft | null) => TaskInputDraft | null) => void;
function message(error: unknown): string {
  if (error instanceof PublicTaskInputError) {
    if (["task_changed", "grant_changed", "revision_conflict", "version_unavailable", "project_unavailable", "context_unavailable", "agent_unavailable"].includes(error.code)) return "The Project, Task, Agent access, or saved inputs changed. Your draft is preserved. Refresh and review the current state.";
    if (["file_scope", "files_unavailable", "image_limit", "capacity"].includes(error.code)) return "A selected file is unavailable or exceeds the limit. Review the complete file selection.";
  }
  return "Mentat could not verify the save. Your draft is preserved. Refresh before deciding what to do next.";
}

export function ProjectTaskInputEditor({ taskId, draft: sharedDraft, onDraftChange }: { taskId: string; draft?: TaskInputDraft | null; onDraftChange?: DraftChange }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [data, setData] = useState<EditorData | null>(null);
  const [localDraft, setLocalDraft] = useState<TaskInputDraft | null>(null);
  const [needsReconciliation, setNeedsReconciliation] = useState(false);
  const [prune, setPrune] = useState<{ input_id: string; revision: number; file_count: number; confirmation_id: string } | null>(null);
  const mounted = useRef(true), locked = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const draft = onDraftChange ? sharedDraft : localDraft;
  const changeDraft = onDraftChange ?? setLocalDraft;
  function initialDraft(): TaskInputDraft {
    if (!data) throw new Error("task_input_unavailable");
    const contextId = data.version?.context_id && data.eligible_contexts.some((entry) => entry.context.id === data.version?.context_id)
      ? data.version.context_id : data.eligible_contexts[0]?.context.id ?? "";
    return { projectId: data.task.project_id ?? "", taskToken: data.expected_task_token, inputRevision: data.input_revision,
      instructions: data.version?.instructions ?? "", contextId,
      selected: data.version?.context_id === contextId ? data.version.files.map((file) => file.id) : [] };
  }
  const instructions = draft?.instructions ?? data?.version?.instructions ?? "";
  const contextId = draft?.contextId ?? (data?.version?.context_id && data.eligible_contexts.some((entry) => entry.context.id === data.version?.context_id)
    ? data.version.context_id : data?.eligible_contexts[0]?.context.id ?? "");
  const selected = draft?.selected ?? (data?.version?.context_id === contextId ? data.version.files.map((file) => file.id) : []);
  const eligible = data?.eligible_contexts.find((entry) => entry.context.id === contextId);
  const stale = !!draft && !!data && (draft.taskToken !== data.expected_task_token || draft.inputRevision !== data.input_revision);
  const chosenFiles = selected.map((id) => eligible?.context.files.find((file) => file.id === id));
  const bytes = new TextEncoder().encode(instructions).length;
  const canSave = !!data && data.task.project_status === "active" && !!data.task.assigned_agent_id && !!eligible && !stale && !needsReconciliation &&
    bytes <= 16 * 1024 && selected.length <= 8 && chosenFiles.every((file) => file?.available) && chosenFiles.filter((file) => file?.kind === "image").length <= 1;
  async function perform(action: () => Promise<void>) {
    if (locked.current) return; locked.current = true; setBusy(true); setNotice("");
    try { await action(); }
    catch (error) { if (mounted.current) { setNotice(message(error)); if (!(error instanceof PublicTaskInputError) || ["unavailable", "invalid_response"].includes(error.code)) setNeedsReconciliation(true); } }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  async function refresh(inputId?: string) {
    const result = await readTaskInputs(taskId, inputId);
    if (mounted.current) { setData(result); setNeedsReconciliation(false); setPrune(null); }
  }
  function changeInstructions(value: string) { changeDraft((current) => ({ ...(current ?? initialDraft()), instructions: value })); }
  function chooseContext(value: string) { changeDraft((current) => ({ ...(current ?? initialDraft()), contextId: value, selected: [] })); }
  function chooseFile(identifier: string, checked: boolean) { changeDraft((current) => { const base = current ?? initialDraft(); return { ...base, selected: checked ? [...base.selected, identifier] : base.selected.filter((id) => id !== identifier) }; }); }
  async function save() {
    if (!data || !eligible || !canSave) return;
    const result = await publishTaskInputs({ task_id: taskId, project_id: data.task.project_id, agent_id: data.task.assigned_agent_id,
      expected_task_revision: data.task.revision, expected_input_revision: data.input_revision, expected_task_token: data.expected_task_token,
      context_id: eligible.context.id, expected_grant_revision: eligible.grant_revision, instructions, attachment_ids: selected });
    changeDraft((current) => current && (current.taskToken !== data.expected_task_token || current.inputRevision !== data.input_revision || current.instructions !== instructions || current.contextId !== eligible.context.id || current.selected.join() !== selected.join()) ? current : null);
    await refresh();
    if (mounted.current) setNotice(`Saved Task input version ${result.revision}. No Agent work was started.`);
  }
  return <section className="project-context-panel" aria-label="Task inputs">
    <div className="project-context-heading"><h3>Task inputs</h3><button aria-expanded={open} disabled={busy} onClick={() => { setOpen(!open); if (!open && !data) void perform(() => refresh()); }} type="button">{open ? "Hide inputs" : "Prepare inputs"}</button></div>
    {open ? <div className="project-context-body"><p>Choose exactly what the assigned Agent may receive when this Task is later approved. Saving does not start work.</p>
      <p aria-live="polite" role="status">{busy ? "Checking…" : notice}</p><div className="project-context-actions"><button disabled={busy} onClick={() => void perform(() => refresh())} type="button">Refresh Task inputs</button></div>
      {data ? <>
        {data.task.project_status !== "active" ? <p>Restore this Project to active before preparing inputs.</p> : null}
        {!data.task.assigned_agent_id ? <p>Assign an Agent to this Task before selecting context.</p> : null}
        {!data.eligible_contexts.length ? <p>Grant this Agent access to a saved version in Project context first.</p> : null}
        {stale ? <div className="project-context-confirmation"><p>The Task or its inputs changed. Your draft is preserved. Review the current Task before using it.</p><button disabled={busy} onClick={() => { changeDraft(() => null); setNotice("Current Task inputs loaded. Review them before saving."); }} type="button">Use current Task</button></div> : null}
        {needsReconciliation ? <p>Refresh to verify whether the last save completed. Your draft remains available.</p> : null}
        <label>Selected Project context<select disabled={busy || !data.eligible_contexts.length} onChange={(event) => chooseContext(event.target.value)} value={contextId}><option value="">Choose approved context</option>{data.eligible_contexts.map((entry) => <option key={entry.context.id} value={entry.context.id}>Version {entry.context.revision} · {entry.context.brief.slice(0, 60) || "No brief"}</option>)}</select></label>
        {eligible ? <><p className="project-context-brief">{eligible.context.brief || "No written Project brief."}</p><fieldset disabled={busy}><legend>Files for this Task · at most eight, including one image</legend>{eligible.context.files.map((file) => <div className="project-context-file-choice" key={file.id}><label><input checked={selected.includes(file.id)} disabled={!file.available} onChange={(event) => chooseFile(file.id, event.target.checked)} type="checkbox" />{file.name}{!file.available ? " · unavailable" : ""}</label>{file.available ? <a download href={projectContextFileUrl(file.id, { context_id: eligible.context.id })}>View file</a> : null}</div>)}</fieldset></> : null}
        {selected.filter((id) => !eligible?.context.files.some((file) => file.id === id)).map((id) => <div className="project-context-file-choice" key={id}><label><input checked onChange={() => chooseFile(id, false)} type="checkbox" />Previously selected file is unavailable · deselect to continue</label></div>)}
        <label>Task-specific instructions<textarea disabled={busy || !data.task.assigned_agent_id} onChange={(event) => changeInstructions(event.target.value)} rows={5} value={instructions} /></label><small>{bytes.toLocaleString()} / 16,384 bytes</small>
        <div className="project-context-actions"><button disabled={busy || !canSave} onClick={() => void perform(save)} type="button">Save input version</button></div>
        <label>Saved input version<select disabled={busy || !data.versions.length} onChange={(event) => void perform(() => refresh(event.target.value))} value={data.version?.id ?? ""}>{!data.versions.length ? <option value="">No saved inputs</option> : data.versions.map((item) => <option key={item.id} value={item.id}>Version {item.revision}{item.revision === data.input_revision ? " · latest" : ""}</option>)}</select></label>
        {data.version ? <section aria-label="Saved Task input version"><p>Input version {data.version.revision} · Project context version {data.version.context_revision}</p><p className="project-context-brief">{data.version.project_brief || "No written Project brief."}</p><p className="project-context-brief">{data.version.instructions || "No Task-specific instructions."}</p><ul className="project-context-files">{data.version.files.map((file) => <li key={file.id}>{file.available ? <a download href={projectContextFileUrl(file.id, { context_id: data.version!.context_id })}>{file.name}</a> : <span>{file.name} · unavailable</span>}</li>)}</ul>{!data.version.files.length ? <p>No files in this saved version.</p> : null}{data.version.revision < data.input_revision ? <div className="project-context-actions"><button disabled={busy} onClick={() => void perform(async () => { const preview = await previewTaskInputPrune(data.version!.id); if (mounted.current) setPrune(preview); })} type="button">Review input removal</button></div> : <small>The latest input version must be retained while this Task exists.</small>}{prune?.input_id === data.version.id ? <div className="project-context-confirmation"><p>Remove input version {prune.revision} from this Task&apos;s history? Shared files remain. This cannot be undone.</p><div className="project-context-actions"><button disabled={busy} onClick={() => void perform(async () => { await confirmTaskInputPrune(prune.input_id, prune.confirmation_id); await refresh(); if (mounted.current) setNotice("Old Task input version removed."); })} type="button">Confirm input removal</button><button disabled={busy} onClick={() => setPrune(null)} type="button">Cancel</button></div></div> : null}</section> : null}
      </> : !busy ? <p>Task inputs are unavailable. Refresh to try again.</p> : null}
    </div> : null}
  </section>;
}

export function RetiredTaskInputHistory() {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [versions, setVersions] = useState<RetiredTaskInputSummary[]>([]);
  const [selected, setSelected] = useState<TaskInputVersion | null>(null);
  const [prune, setPrune] = useState<{ input_id: string; revision: number; file_count: number; confirmation_id: string } | null>(null);
  const mounted = useRef(true), locked = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function perform(action: () => Promise<void>) {
    if (locked.current) return; locked.current = true; setBusy(true); setNotice("");
    try { await action(); } catch (error) { if (mounted.current) { setPrune(null); setNotice(message(error)); } }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  async function refresh() { const result = await readRetiredTaskInputs(); if (mounted.current) { setVersions(result.versions); setSelected(null); setPrune(null); } }
  return <section aria-label="Retained Task input history" className="project-context-panel"><button aria-expanded={open} disabled={busy} onClick={() => { setOpen(!open); if (!open) void perform(refresh); }} type="button">Retained Task inputs</button>
    {open ? <div className="project-context-body"><p>Inputs kept after Task or Project deletion. They are separate from any new Task with the same name.</p><p aria-live="polite" role="status">{busy ? "Loading…" : notice}</p><button disabled={busy} onClick={() => void perform(refresh)} type="button">Refresh retained inputs</button>
      <ul>{versions.map((item) => <li key={item.id}><span>Version {item.revision} · {item.summary}</span><button disabled={busy} onClick={() => void perform(async () => { const detail = await readRetiredTaskInput(item.id); if (mounted.current) { setSelected(detail); setPrune(null); } })} type="button">View retained input</button></li>)}</ul>{!busy && !versions.length ? <p>No retained Task inputs.</p> : null}
      {selected ? <section aria-label="Retired Task input version"><h4>Input version {selected.revision} · Project context version {selected.context_revision}</h4><p className="project-context-brief">{selected.project_brief || "No written Project brief."}</p><p className="project-context-brief">{selected.instructions || "No Task-specific instructions."}</p><ul className="project-context-files">{selected.files.map((file) => <li key={file.id}>{file.available ? <a download href={projectContextFileUrl(file.id, { context_id: selected.context_id })}>{file.name}</a> : <span>{file.name} · unavailable</span>}</li>)}</ul><button disabled={busy} onClick={() => void perform(async () => { const preview = await previewTaskInputPrune(selected.id); if (mounted.current) setPrune(preview); })} type="button">Review input removal</button>
        {prune?.input_id === selected.id ? <div className="project-context-confirmation"><p>Remove retained input version {prune.revision}? Shared files remain. This cannot be undone.</p><div className="project-context-actions"><button disabled={busy} onClick={() => void perform(async () => { await confirmTaskInputPrune(prune.input_id, prune.confirmation_id); await refresh(); if (mounted.current) setNotice("Retained Task input removed."); })} type="button">Confirm input removal</button><button disabled={busy} onClick={() => setPrune(null)} type="button">Cancel</button></div></div> : null}</section> : null}
    </div> : null}
  </section>;
}
