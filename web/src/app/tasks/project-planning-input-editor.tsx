"use client";

import { useEffect, useRef, useState } from "react";
import { projectContextFileUrl } from "@/lib/public-project-context";
import type { ProjectInputEditor, ProjectInputSave, ProjectInputResults } from "@/lib/project-planning-input-contract";
import { projectInputs, PublicProjectInputError } from "@/lib/public-project-planning-inputs";

export type ProjectPlanningInputDraft = { scopeToken: string; selectionToken: string; projectRevision: number; inputRevision: number; leadRoleId: string; leadRevision: number; contextId: string; grantRevision: number; instructions: string; selected: string[]; pending: ProjectInputSave | null };
type DraftChange = (update: (current: ProjectPlanningInputDraft | null) => ProjectPlanningInputDraft | null) => void;

function message(error: unknown, operation: "read" | "save" | "reconcile"): string {
  if (error instanceof PublicProjectInputError) {
    if (["project_changed", "scope_changed", "lead_changed", "context_changed", "revision_conflict", "selection_changed"].includes(error.code)) return "The Project, lead, context, or saved input changed. Your draft is preserved; refresh and review the current state.";
    if (["file_scope", "files_unavailable", "image_limit"].includes(error.code)) return "A selected file is unavailable or exceeds the limit. Review the complete selection.";
    if (error.code === "capacity") return "This Project has reached its saved-input limit. Earlier versions are retained; manual Task planning remains available.";
    if (error.code === "action_conflict") return "This exact save ID was used for different content. Refresh and review before starting a new save.";
  }
  if (operation === "read") return "Mentat could not load Project planning inputs. Your draft is unchanged; refresh to try again.";
  if (operation === "reconcile") return "Mentat could not check the saved action. Your exact request is retained; check again.";
  return "Mentat could not verify the save. Your exact draft and save ID are retained. Check the saved action before retrying.";
}
function fresh(data: ProjectInputEditor): ProjectPlanningInputDraft | null {
  if (!data.save_available || !data.lead.id || !data.context || data.grant_revision === null) return null;
  const same = data.version?.context_id === data.context.id && data.version.lead_role_id === data.lead.id;
  return { scopeToken: data.scope_token, selectionToken: data.selection_token,
    projectRevision: data.project.revision, inputRevision: data.input_revision,
    leadRoleId: data.lead.id, leadRevision: data.lead.revision,
    contextId: data.context.id, grantRevision: data.grant_revision,
    instructions: same ? data.version!.instructions : "",
    selected: same ? data.version!.files.map((file) => file.id) : [], pending: null };
}
function actionId(): string {
  const bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
  return `project_input_action_${[...bytes].map((part) => part.toString(16).padStart(2, "0")).join("")}`;
}

export function ProjectPlanningInputEditor({ projectId, draft: sharedDraft, onDraftChange }: { projectId: string; draft?: ProjectPlanningInputDraft | null; onDraftChange?: DraftChange }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [data, setData] = useState<ProjectInputEditor | null>(null), [localDraft, setLocalDraft] = useState<ProjectPlanningInputDraft | null>(null);
  const mounted = useRef(true), locked = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const draft = onDraftChange ? sharedDraft ?? null : localDraft;
  const changeDraft = onDraftChange ?? setLocalDraft;
  const scopeChanged = !!draft && !!data && draft.scopeToken !== data.scope_token;
  const stale = !!draft && !!data && (scopeChanged || draft.selectionToken !== data.selection_token
    || draft.projectRevision !== data.project.revision || draft.inputRevision !== data.input_revision);
  const instructions = draft?.instructions ?? data?.version?.instructions ?? "";
  const selected = draft?.selected ?? (data && data.version && data.version.context_id === data.context?.id && data.version.lead_role_id === data.lead.id
    ? data.version.files.map((file) => file.id) : []);
  const choices = data?.context?.files ?? [];
  const selectedFiles = selected.map((id) => choices.find((file) => file.id === id));
  const byteCount = new TextEncoder().encode(instructions).length;
  const canSave = !!data?.save_available && !busy && !needsRefresh && !stale && !draft?.pending && !!data.context
    && selected.length <= 8 && selectedFiles.every((file) => file?.available)
    && selectedFiles.filter((file) => file?.kind === "image").length <= 1 && byteCount <= 16 * 1024;

  async function perform(action: () => Promise<void>, operation: "read" | "save" | "reconcile" = "read") {
    if (locked.current) return; locked.current = true; setBusy(true); setNotice("");
    try { await action(); }
    catch (error) { if (mounted.current) setNotice(message(error, operation)); }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  async function refresh(inputId?: string) {
    const result = await projectInputs(inputId ? "version" : "project", inputId
      ? { project_id: projectId, input_id: inputId } : { project_id: projectId });
    if (mounted.current) { setData(result); setNeedsRefresh(false); }
  }
  function change(update: (current: ProjectPlanningInputDraft) => ProjectPlanningInputDraft) {
    changeDraft((current) => { const base = current ?? (data ? fresh(data) : null); return base ? update(base) : current; });
  }
  async function submit(request: ProjectInputSave) {
    let result: ProjectInputResults["publish"];
    try {
      result = await projectInputs("publish", request);
    } catch (error) {
      if (error instanceof PublicProjectInputError && !["unavailable", "invalid_response"].includes(error.code))
        changeDraft((current) => current?.pending?.action_id === request.action_id ? { ...current, pending: null } : current);
      throw error;
    }
    changeDraft((current) => current?.pending?.action_id === request.action_id ? null : current);
    try { await refresh(); }
    catch { if (mounted.current) { setNeedsRefresh(true); setNotice(`Input version ${result.revision} committed, but the current view could not load. Refresh before continuing.`); } return; }
    if (mounted.current) setNotice(result.status === "saved" ? `Saved Project planning input version ${result.revision}. No Agent work was started.`
      : `Save ${result.revision} committed earlier. Review the current Project before continuing.`);
  }
  async function save() {
    if (!data || !canSave || !data.context || !data.lead.id || data.grant_revision === null) return;
    const request: ProjectInputSave = { project_id: projectId, expected_project_revision: data.project.revision,
      lead_role_id: data.lead.id, expected_lead_revision: data.lead.revision,
      context_id: data.context.id, expected_grant_revision: data.grant_revision,
      expected_input_revision: data.input_revision, scope_token: data.scope_token,
      selection_token: data.selection_token, action_id: actionId(), instructions,
      attachment_ids: [...selected] };
    changeDraft((current) => ({ ...(current ?? fresh(data)!), instructions, selected: [...selected], pending: request }));
    await submit(request);
  }
  async function reconcile() {
    if (!draft?.pending) return;
    const request = draft.pending;
    const result = await projectInputs("reconcile", { project_id: projectId, action_id: request.action_id,
      scope_token: request.scope_token });
    if (result.status === "not_found") { if (mounted.current) setNotice("No committed receipt found yet. Keep this exact request and check again, or explicitly retry it."); return; }
    changeDraft((current) => current?.pending?.action_id === request.action_id ? null : current);
    try { await refresh(); }
    catch { if (mounted.current) { setNeedsRefresh(true); setNotice(`Input version ${result.revision} committed, but the current view could not load. Refresh before continuing.`); } return; }
    if (mounted.current) setNotice(`Input version ${result.revision} committed. Review the current Project before another save.`);
  }
  function useCurrent() {
    if (!data || draft?.pending) return;
    const current = fresh(data);
    changeDraft((previous) => !current ? previous : scopeChanged ? current : {
      ...current, instructions: previous?.instructions ?? current.instructions,
      selected: previous?.selected.filter((id) => data.context?.files.some((file) => file.id === id)) ?? current.selected,
    });
    setNotice(scopeChanged ? "Old Project draft discarded. Review the current Project before saving."
      : "Current access loaded. Your draft text is preserved; review the files before saving.");
  }

  return <section className="project-context-panel" aria-label="Project planning inputs">
    <div className="project-context-heading"><h3>Project planning inputs</h3><button type="button" disabled={busy} aria-expanded={open} onClick={() => { setOpen(!open); if (!open && !data) void perform(() => refresh()); }}>{open ? "Hide planning inputs" : "Prepare planning inputs"}</button></div>
    {open ? <div className="project-context-body">
      <p>Review what the Project lead could use to propose a plan. Saving this version does not start an Agent or approve work.</p>
      <p role="status" aria-live="polite">{busy ? "Checking…" : notice}</p>
      <div className="project-context-actions"><button type="button" disabled={busy} onClick={() => void perform(() => refresh())}>Refresh planning inputs</button></div>
      {data ? <>
        {data.lead.status !== "context_bound" ? <p>Select a lead with current Project context access before saving planning inputs.</p> : null}
        {data.input_revision >= 32 ? <p>This Project has 32 retained planning-input versions, the current limit. Manual Task planning remains available.</p> : null}
        {scopeChanged ? <div className="project-context-confirmation"><p>This is a different Project incarnation. The old draft is preserved but cannot be saved here.</p><button type="button" disabled={busy || !!draft?.pending} onClick={useCurrent}>Discard old draft and use current Project</button></div>
          : stale ? <div className="project-context-confirmation"><p>Project access or saved inputs changed. Your draft is preserved. Review current access before saving.</p><button type="button" disabled={busy || !!draft?.pending} onClick={useCurrent}>Use current access</button></div> : null}
        {draft?.pending ? <div className="project-context-confirmation"><p>The last save needs exact readback. Keep this request until Mentat verifies the result.</p><div className="project-context-actions"><button type="button" disabled={busy} onClick={() => void perform(reconcile, "reconcile")}>Check saved action</button><button type="button" disabled={busy} onClick={() => void perform(() => submit(draft.pending!), "save")}>Retry exact save</button></div></div> : null}
        {data.context ? <><p>Current Project context version {data.context.revision}: {data.context.brief || "No written brief."}</p>
          <fieldset disabled={busy || !data.save_available || !!draft?.pending}><legend>Selected files · at most eight, including one image</legend>{choices.map((file) => <div className="project-context-file-choice" key={file.id}><label><input type="checkbox" checked={selected.includes(file.id)} disabled={!file.available} onChange={(event) => change((current) => ({ ...current, selected: event.target.checked ? [...current.selected, file.id] : current.selected.filter((id) => id !== file.id) }))} />{file.name}{!file.available ? " · unavailable" : ""}</label>{file.available ? <a download href={projectContextFileUrl(file.id, { context_id: data.context!.id })}>View file</a> : null}</div>)}</fieldset>
          {selected.filter((id) => !choices.some((file) => file.id === id)).map((id) => <div key={id} className="project-context-file-choice"><label><input type="checkbox" checked onChange={() => change((current) => ({ ...current, selected: current.selected.filter((item) => item !== id) }))} />Previously selected file is unavailable · deselect to continue</label></div>)}</> : null}
        <label>Instructions for the Project lead<textarea rows={5} disabled={busy || !data.save_available || !!draft?.pending} value={instructions} onChange={(event) => change((current) => ({ ...current, instructions: event.target.value }))} /></label>
        <small>{byteCount.toLocaleString()} / 16,384 bytes</small>
        <div className="project-context-actions"><button type="button" disabled={!canSave} onClick={() => void perform(save, "save")}>Save Project input version</button></div>
        <label>Saved input version<select disabled={busy || !data.versions.length} value={data.version?.id ?? ""} onChange={(event) => void perform(() => refresh(event.target.value))}>{!data.versions.length ? <option value="">No saved inputs</option> : data.versions.map((item) => <option key={item.id} value={item.id}>Version {item.revision}{item.revision === data.input_revision ? " · latest" : ""}</option>)}</select></label>
        {data.version ? <section aria-label="Saved Project planning input version"><p>Version {data.version.revision} · Project context version {data.version.context_revision}</p><p className="project-context-brief">{data.version.instructions || "No additional instructions."}</p><ul className="project-context-files">{data.version.files.map((file) => <li key={file.id}>{file.available ? <a download href={projectContextFileUrl(file.id, { context_id: data.version!.context_id })}>{file.name}</a> : <span>{file.name} · unavailable</span>}</li>)}</ul>{!data.version.files.length ? <p>No files selected in this saved version.</p> : null}</section> : null}
        <p>Lead proposals are unavailable until the separate qualified proposal Run and owner review are ready.</p>
      </> : !busy ? <p>Project planning inputs are unavailable. Refresh to try again.</p> : null}
    </div> : null}
  </section>;
}
