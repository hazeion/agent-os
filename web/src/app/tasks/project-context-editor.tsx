"use client";

import { useEffect, useRef, useState } from "react";
import type { ContextEditor, ContextFile, ContextVersion, GrantPreview, PrunePreview } from "@/lib/project-context-contract";
import { ProjectContextClientError, projectContextFileUrl, projectFileBase64, readOrChangeProjectContext as capability } from "@/lib/public-project-context";

export type ProjectContextDraft = { brief: string; selected: string[] };
type DraftChange = (update: (draft: ProjectContextDraft | null) => ProjectContextDraft | null) => void;
type Agent = { id: string; name: string };
function errorMessage(error: unknown): string {
  if (error instanceof ProjectContextClientError) {
    if (["stale", "project_changed", "staging_changed", "revision_conflict"].includes(error.code)) return "This Project changed. Refresh, review the latest version, and try again. Your draft is preserved.";
    if (error.code === "capacity") return "The file or saved-context limit was reached. Remove unused files or eligible history, then try again.";
    if (error.code === "file_unavailable") return "A selected file is unavailable. Review your files before continuing.";
  }
  return "The change could not be verified. Your draft is preserved. Refresh to check the saved state before trying again.";
}
function FileLinks({ files, target }: { files: ContextFile[]; target: { project_id: string } | { context_id: string } }) {
  return <ul className="project-context-files">{files.map((file) => <li key={file.id}>{file.available ? <a href={projectContextFileUrl(file.id, target)} download>{file.name}</a> : <span>{file.name} · unavailable</span>}<small>{Math.ceil(file.byte_size / 1024)} KB</small></li>)}</ul>;
}

export function ProjectContextEditor({ projectId, agents, draft: sharedDraft, onDraftChange }: { projectId: string; agents: Agent[]; draft?: ProjectContextDraft | null; onDraftChange?: DraftChange }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ContextEditor | null>(null);
  const [localDraft, setLocalDraft] = useState<ProjectContextDraft | null>(null);
  const draft = onDraftChange ? sharedDraft : localDraft;
  const changeDraft = onDraftChange ?? setLocalDraft;
  const brief = draft?.brief ?? data?.current?.brief ?? "";
  const selected = draft?.selected ?? data?.current?.files.map((file) => file.id) ?? [];
  function setBrief(value: string) { changeDraft((previous) => ({ brief: value, selected: previous?.selected ?? selected })); }
  function setSelected(update: (ids: string[]) => string[]) { changeDraft((previous) => ({ brief: previous?.brief ?? brief, selected: update(previous?.selected ?? selected) })); }
  const [view, setView] = useState<ContextVersion | null>(null);
  const [agent, setAgent] = useState("");
  const [grant, setGrant] = useState<GrantPreview | null>(null);
  const [prune, setPrune] = useState<PrunePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const locked = useRef(false); const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function refresh() {
    const next = await capability("project", { project_id: projectId });
    if (!mounted.current) return;
    setData(next); setGrant(null); setPrune(null); setView(next.current);
  }
  async function perform(action: () => Promise<void>) {
    if (locked.current) return; locked.current = true; setBusy(true); setNotice("");
    try { await action(); } catch (error) { if (mounted.current) { setGrant(null); setPrune(null); setNotice(errorMessage(error)); } }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  async function publish() {
    if (!data) return;
    await capability("publish", { project_id: projectId, expected_project_revision: data.project.revision, expected_revision: data.current?.revision ?? 0, brief, attachment_ids: selected, expected_staged_ids: data.staged.map((file) => file.id) });
    changeDraft((previous) => previous && (previous.brief !== brief || previous.selected.join() !== selected.join()) ? previous : null);
    await refresh(); if (mounted.current) setNotice("Saved a new context version. Existing Agent permissions still point to their approved versions.");
  }
  async function upload(file: File) {
    if (!data) return;
    const result = await capability("upload", { project_id: projectId, expected_project_revision: data.project.revision, name: file.name, content_type: file.type, content_base64: await projectFileBase64(file) });
    setSelected((ids) => [...new Set([...ids, result.file.id])]);
    if (!mounted.current) return;
    await refresh();
    if (mounted.current) setNotice("File staged. Publish a version to retain it. Unpublished uploads expire after two hours.");
  }
  async function discard(attachmentId: string) {
    if (!data) return;
    await capability("discard", { project_id: projectId, expected_project_revision: data.project.revision, attachment_id: attachmentId });
    setSelected((ids) => ids.filter((id) => id !== attachmentId));
    await refresh();
  }
  function selectFile(id: string, checked: boolean) { setSelected((ids) => checked ? [...ids, id] : ids.filter((item) => item !== id)); }
  function discardFile(id: string) { void perform(() => discard(id)); }
  const choices = [...(data?.current?.files ?? []), ...(data?.staged ?? [])].filter((file, index, files) => files.findIndex((item) => item.id === file.id) === index);
  const editable = data?.project.status === "active";
  const byteCount = new TextEncoder().encode(brief).length;
  return <section className="project-context-panel" aria-label="Project context">
    <div className="project-context-heading"><h3>Project context</h3><button type="button" disabled={busy} aria-expanded={open} onClick={() => { setOpen(!open); if (!open && !data) void perform(() => refresh()); }}>{open ? "Hide context" : "Open context"}</button></div>
    {open ? <div className="project-context-body">
      <p>Save goals, constraints and reference files. Give each Agent access to a specific saved version.</p>
      <p role="status" aria-live="polite">{busy ? "Working…" : notice}</p>
      <div className="project-context-actions"><button type="button" disabled={busy} onClick={() => void perform(() => refresh())}>Refresh context</button></div>
      {data ? <>
        {!editable ? <p>This Project is {data.project.status}. Restore it to active before publishing context.</p> : null}
        <label>Goals and constraints<textarea rows={6} disabled={busy || !editable} value={brief} onChange={(event) => { setBrief(event.target.value); setGrant(null); }} /></label>
        <small>{byteCount.toLocaleString()} / 16,384 bytes</small>
        <fieldset disabled={busy || !editable}><legend>Files for the next version</legend>
          {choices.length ? choices.map((file) => <div className="project-context-file-choice" key={file.id}><label><input type="checkbox" checked={selected.includes(file.id)} onChange={(event) => selectFile(file.id, event.target.checked)} />{file.name}{!file.available ? " · unavailable" : ""}</label>{data.staged.some((item) => item.id === file.id) ? <button type="button" onClick={() => discardFile(file.id)}>Discard upload</button> : null}</div>) : <p>No files selected.</p>}
          {selected.filter((id) => !choices.some((file) => file.id === id)).map((id) => <div key={id} className="project-context-file-choice"><label><input type="checkbox" checked onChange={() => { setSelected((ids) => ids.filter((item) => item !== id)); }} />Unavailable file from your draft · deselect to continue</label></div>)}
          <label>Add reference file<input type="file" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void perform(() => upload(file)); }} /></label>
          <small>Text up to 2 MB; PNG, JPEG, GIF or WebP up to 10 MB. Up to 16 files per version.</small>
        </fieldset>
        <div className="project-context-actions"><button type="button" disabled={busy || !editable || byteCount > 16384 || selected.length > 16 || selected.some((id) => !choices.find((file) => file.id === id)?.available)} onClick={() => void perform(publish)}>Publish context version</button></div>
        <label>Saved version<select disabled={busy || !data.versions.length} value={view?.id ?? ""} onChange={(event) => { const id = event.target.value; void perform(async () => { const result = await capability("version", { context_id: id }); if (mounted.current) { setView(result); setGrant(null); setPrune(null); } }); }}>{!data.versions.length ? <option value="">No saved versions</option> : data.versions.map((version) => <option key={version.id} value={version.id}>Version {version.revision}{version.id === data.current?.id ? " · current" : ""}</option>)}</select></label>
        {view ? <section aria-label="Saved context version"><h4>Version {view.revision}</h4><p className="project-context-brief">{view.brief || "No written brief."}</p><FileLinks files={view.files} target={{ context_id: view.id }} />
          <div className="project-context-actions"><button type="button" disabled={busy || !!view.prune_blocked} onClick={() => void perform(async () => { const result = await capability("prune-preview", { context_id: view.id }); if (mounted.current) { setPrune(result); setGrant(null); } })}>Review removal</button></div>
          {view.prune_blocked ? <small>{view.prune_blocked === "current_version" ? "The current version must be retained." : view.prune_blocked === "task_input" ? "Retained Task inputs still reference this version." : "Revoke Agent access before removing this version."}</small> : null}
          {prune ? <div className="project-context-confirmation"><p>Remove version {prune.revision} from saved history? Files shared with other versions or Runs will remain. This cannot be undone.</p><div className="project-context-actions"><button type="button" disabled={busy} onClick={() => void perform(async () => { await capability("prune-confirm", { context_id: prune.context_id, confirmation_id: prune.confirmation_id, confirmed: true }); await refresh(); })}>Confirm removal</button><button type="button" disabled={busy} onClick={() => setPrune(null)}>Cancel</button></div></div> : null}
          <h4>Agent access</h4><p>Approval covers only this saved version. It does not start work. Revoking access prevents future use; it cannot remove context already delivered to an Agent.</p>
          <label>Agent<select disabled={busy || !editable} value={agent} onChange={(event) => { setAgent(event.target.value); setGrant(null); }}><option value="">Choose an Agent</option>{agents.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <div className="project-context-actions"><button type="button" disabled={busy || !editable || !agent || view.files.some((file) => !file.available)} onClick={() => void perform(async () => { const result = await capability("grant-preview", { project_id: projectId, context_id: view.id, agent_id: agent }); if (mounted.current) { setGrant(result); setPrune(null); } })}>Review Agent access</button></div>
          {grant ? <div className="project-context-confirmation" aria-label="Agent access preview"><p>Allow {grant.agent_name} to use version {grant.context_revision}?</p><p className="project-context-brief">{grant.brief || "No written brief."}</p><FileLinks files={grant.files} target={{ context_id: grant.context_id }} /><div className="project-context-actions"><button type="button" disabled={busy} onClick={() => void perform(async () => { await capability("grant-confirm", { project_id: projectId, context_id: grant.context_id, agent_id: grant.agent_id, confirmation_id: grant.confirmation_id, confirmed: true }); await refresh(); if (mounted.current) setNotice("Agent access approved for the reviewed version."); })}>Approve access</button><button type="button" disabled={busy} onClick={() => setGrant(null)}>Cancel</button></div></div> : null}
        </section> : null}
        <ul className="project-context-grants">{data.grants.map((item) => <li key={item.agent_id}><span>{agents.find((candidate) => candidate.id === item.agent_id)?.name ?? "Agent"} · {item.state}{item.context_id ? ` · version ${data.versions.find((version) => version.id === item.context_id)?.revision ?? "unavailable"}` : ""}</span>{item.state === "active" && item.context_id ? <button type="button" disabled={busy} onClick={() => void perform(async () => { await capability("revoke", { project_id: projectId, context_id: item.context_id, agent_id: item.agent_id, expected_revision: item.revision }); await refresh(); if (mounted.current) setNotice("Agent access revoked."); })}>Revoke access</button> : null}</li>)}</ul>
      </> : !busy ? <p>Context is unavailable. Use Refresh context to try again.</p> : null}
    </div> : null}
  </section>;
}

export function RetiredProjectContextHistory() {
  const [open, setOpen] = useState(false); const [versions, setVersions] = useState<Array<{ id: string; revision: number; summary: string }>>([]);
  const [view, setView] = useState<ContextVersion | null>(null); const [prune, setPrune] = useState<PrunePreview | null>(null);
  const [busy, setBusy] = useState(false); const [notice, setNotice] = useState(""); const locked = useRef(false); const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function perform(action: () => Promise<void>) { if (locked.current) return; locked.current = true; setBusy(true); setNotice(""); try { await action(); } catch (error) { if (mounted.current) { setPrune(null); setNotice(errorMessage(error)); } } finally { locked.current = false; if (mounted.current) setBusy(false); } }
  async function refresh() { const result = await capability("history", {}); if (mounted.current) { setVersions(result.versions); setView(null); setPrune(null); } }
  return <section className="project-context-panel" aria-label="Retained Project history"><button type="button" disabled={busy} aria-expanded={open} onClick={() => { setOpen(!open); if (!open) void perform(refresh); }}>Retained Project history</button>{open ? <div className="project-context-body"><p>Context kept after a Project was deleted. These versions are not attached to any current Project.</p><p role="status">{busy ? "Loading…" : notice}</p><button type="button" disabled={busy} onClick={() => void perform(refresh)}>Refresh history</button><ul>{versions.map((item) => <li key={item.id}><span>Version {item.revision} · {item.summary}</span><button type="button" disabled={busy} onClick={() => void perform(async () => { const result = await capability("version", { context_id: item.id }); if (mounted.current) { setView(result); setPrune(null); } })}>View saved version</button></li>)}</ul>{!busy && !versions.length ? <p>No retained history.</p> : null}{view ? <section><h4>Version {view.revision}</h4><p className="project-context-brief">{view.brief}</p><FileLinks files={view.files} target={{ context_id: view.id }} /><button type="button" disabled={busy || !!view.prune_blocked} onClick={() => void perform(async () => { const result = await capability("prune-preview", { context_id: view.id }); if (mounted.current) setPrune(result); })}>Review removal</button>{prune ? <div className="project-context-confirmation"><p>Remove version {prune.revision}? Shared files remain. This cannot be undone.</p><div className="project-context-actions"><button type="button" disabled={busy} onClick={() => void perform(async () => { await capability("prune-confirm", { context_id: prune.context_id, confirmation_id: prune.confirmation_id, confirmed: true }); await refresh(); })}>Confirm removal</button><button type="button" disabled={busy} onClick={() => setPrune(null)}>Cancel</button></div></div> : null}</section> : null}</div> : null}</section>;
}
