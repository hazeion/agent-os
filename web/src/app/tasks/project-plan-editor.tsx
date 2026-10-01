"use client";

import { useEffect, useRef, useState } from "react";
import type { PublicAgent } from "@/lib/bridge-agents";
import { readPlanningTaskDependencies, readPlanningTasks, type PublicPlanningTaskListItem } from "@/lib/public-planning";
import { readTaskInputs } from "@/lib/public-task-inputs";
import { type PlanDraftNode, type PlanProject, type PlanVersion, projectPlanRequest } from "@/lib/project-plan-contract";
import { projectPlans, PublicProjectPlanError } from "@/lib/public-project-plans";

export type PlanDraft = { projectRevision: number; planRevision: number; title: string; nodes: PlanDraftNode[]; unresolved: boolean };
type Prepared = { taskId: string; title: string; revision: number; agentId: string; inputId: string; exactGrant: boolean };
type Comparison = { fingerprint: string; missing: Array<[string, string]>; additional: Array<[string, string]>; acknowledged: boolean };
type DraftChange = (update: (current: PlanDraft | null) => PlanDraft | null) => void;

function errorMessage(error: unknown): string {
  if (error instanceof PublicProjectPlanError && ["project_changed", "revision_conflict", "context_changed", "task_changed", "input_changed", "grant_changed", "agent_changed"].includes(error.code)) return "The Project, Task, Agent or saved inputs changed. Your draft is preserved; refresh and review it before saving.";
  if (error instanceof PublicProjectPlanError && error.code === "capacity") return "Plan history is full or this plan exceeds a limit. Your draft is preserved.";
  return "Mentat could not verify this plan. Your draft is preserved; refresh before deciding what to do next.";
}
function savedToDraft(version: PlanProject["current"], projectRevision: number, planRevision: number): PlanDraft {
  return { projectRevision, planRevision, title: version?.title ?? "", unresolved: false,
    nodes: version?.nodes.map(({ task_revision, ...node }) => ({ ...node, expected_task_revision: task_revision })) ?? [] };
}
function samePublished(draft: PlanDraft, version: PlanVersion): boolean {
  if (draft.title.trim() !== version.title || draft.nodes.length !== version.nodes.length) return false;
  return draft.nodes.every((node, index) => {
    const saved = version.nodes[index];
    return saved.task_id === node.task_id && saved.task_revision === node.expected_task_revision
      && saved.agent_id === node.agent_id && saved.input_version_id === node.input_version_id
      && saved.segment === node.segment && saved.max_attempts === node.max_attempts
      && saved.max_wall_seconds === node.max_wall_seconds && saved.max_work_units === node.max_work_units
      && saved.after.length === node.after.length && saved.after.every((id, position) => id === node.after[position]);
  });
}
function graphValid(nodes: PlanDraftNode[]): boolean {
  if (!nodes.length || nodes.length > 32 || nodes[0].segment !== 0) return false;
  const seen = new Set<string>(), segments = new Set<number>();
  for (const [index, node] of nodes.entries()) {
    if (seen.has(node.task_id) || !Number.isSafeInteger(node.segment) || node.segment < 0 || node.segment > 31
      || index && node.segment < nodes[index - 1].segment
      || node.after.some((id) => !seen.has(id)) || node.after.some((id) => nodes.find((item) => item.task_id === id)!.segment > node.segment)) return false;
    seen.add(node.task_id); segments.add(node.segment);
  }
  return segments.size === Math.max(...segments) + 1;
}
function compactSegments(nodes: PlanDraftNode[]): PlanDraftNode[] {
  const values = [...new Set(nodes.map((node) => node.segment))].sort((left, right) => left - right);
  return nodes.map((node) => ({ ...node, segment: values.indexOf(node.segment) }));
}

export function ProjectPlanEditor({ projectId, agents, draft, onDraftChange, onOpenTask }: { projectId: string; agents: PublicAgent[]; draft?: PlanDraft | null; onDraftChange: DraftChange; onOpenTask: (taskId: string) => void }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [view, setView] = useState<PlanProject | null>(null), [history, setHistory] = useState<PlanVersion | null>(null);
  const [candidates, setCandidates] = useState<PublicPlanningTaskListItem[]>([]), [nextCursor, setNextCursor] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [prepared, setPrepared] = useState<Record<string, Prepared | null>>({});
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [pendingEdit, setPendingEdit] = useState<{ nodes: PlanDraftNode[]; description: string } | null>(null);
  const [reconciledRevision, setReconciledRevision] = useState<number | null>(null);
  const mounted = useRef(true), locked = useRef(false);
  const published = useRef<{ id: string; revision: number; draft: PlanDraft } | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const titleFor = (taskId: string) => candidates.find((task) => task.id === taskId)?.title ?? taskId;
  const historicalTitleFor = (taskId: string) => {
    const node = history?.nodes.find((item) => item.task_id === taskId);
    return node?.task_state === "current" ? node.task_title : `${taskId} (${node?.task_state ?? "unavailable"})`;
  };
  const agentName = (agentId: string) => agents.find((agent) => agent.id === agentId)?.name ?? `${agentId} (unavailable)`;
  const change = (update: (current: PlanDraft) => PlanDraft) => {
    onDraftChange((current) => current ? update(current) : current);
    setComparison(null); setPendingEdit(null);
  };
  async function perform(action: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setNotice("");
    try { await action(); } catch (error) { if (mounted.current) setNotice(errorMessage(error)); }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  async function refresh() {
    let result: PlanProject;
    try { result = await projectPlans("project", { project_id: projectId }); }
    catch (error) { if (mounted.current) { setView(null); setComparison(null); } throw error; }
    if (!mounted.current) return;
    setView(result); setHistory(null); setComparison(null);
    if (draft?.unresolved) setReconciledRevision(result.plan_revision);
    const receipt = published.current;
    if (receipt && !result.versions.some((item) => item.id === receipt.id)) {
      onDraftChange((current) => current === receipt.draft ? { ...current, unresolved: true } : current);
      setNotice("The save was accepted, but its exact version is not visible yet. Your draft remains; refresh before deciding.");
      return;
    }
    if (receipt) {
      const version = await projectPlans("version", { project_id: projectId, version_id: receipt.id });
      if (!mounted.current) return;
      if (version.revision === receipt.revision && samePublished(receipt.draft, version)) {
        onDraftChange((current) => current === receipt.draft ? null : current);
        setNotice(version.current ? "Plan version saved. It remains unapproved and cannot start Agent work." : "Plan version saved, and a newer version is current. Review the history.");
        published.current = null;
      } else {
        onDraftChange((current) => current === receipt.draft ? { ...current, unresolved: true } : current);
        setNotice("The saved version did not match this draft. Your draft remains for review.");
      }
    }
  }
  async function loadCandidates(cursor: string | null = null) {
    const page = await readPlanningTasks(projectId, cursor);
    if (!mounted.current) return;
    setCandidates((current) => cursor ? [...current, ...page.tasks.filter((item) => !current.some((prior) => prior.id === item.id))] : page.tasks);
    setNextCursor(page.next_cursor);
  }
  async function start() {
    await refresh();
    await loadCandidates();
  }
  function beginEdit() {
    if (!view || view.project.status !== "active") return;
    const next = savedToDraft(view.current, view.project.revision, view.plan_revision);
    onDraftChange(() => next); setPrepared({}); setComparison(null); setHistory(null); setReconciledRevision(null);
  }
  async function taskPreparation(taskId: string): Promise<Prepared | null> {
    const input = await readTaskInputs(taskId);
    const version = input.version;
    if (input.task.project_id !== projectId || input.task.project_status !== "active" || !input.task.assigned_agent_id || !version
      || version.revision !== input.input_revision || version.task_revision !== input.task.revision
      || version.agent_id !== input.task.assigned_agent_id
      || !input.eligible_contexts.some((item) => item.context.id === version.context_id && item.grant_revision === version.grant_revision)) return null;
    return { taskId, title: input.task.title, revision: input.task.revision,
      agentId: input.task.assigned_agent_id, inputId: version.id, exactGrant: true };
  }
  async function addTask(taskId: string) {
    if (!draft || draft.nodes.length >= 32 || draft.nodes.some((item) => item.task_id === taskId)) return;
    const item = await taskPreparation(taskId);
    if (!mounted.current) return;
    setPrepared((current) => ({ ...current, [taskId]: item }));
    if (!item) { setNotice("This Task needs a current Agent assignment, saved inputs and exact access. Open the Task and Prepare inputs first."); return; }
    const last = draft.nodes.at(-1);
    change((current) => ({ ...current, nodes: [...current.nodes, { task_id: taskId,
      expected_task_revision: item.revision, agent_id: item.agentId, input_version_id: item.inputId,
      after: [], segment: last?.segment ?? 0, max_attempts: 1, max_wall_seconds: 900, max_work_units: 100 }] }));
  }
  async function checkTasks() {
    if (!draft) return;
    setPrepared({});
    const next: Record<string, Prepared | null> = {};
    for (const node of draft.nodes) {
      try { next[node.task_id] = await taskPreparation(node.task_id); }
      catch { next[node.task_id] = null; }
    }
    if (mounted.current) { setPrepared(next); setNotice("Task preparation checked. Changed Tasks must be updated explicitly before Save."); }
  }
  function applyCurrentInput(taskId: string) {
    const item = prepared[taskId]; if (!item) return;
    change((current) => ({ ...current, nodes: current.nodes.map((node) => node.task_id === taskId ? {
      ...node, expected_task_revision: item.revision, agent_id: item.agentId, input_version_id: item.inputId,
    } : node) }));
  }
  function stageRemoval(index: number) {
    if (!draft) return;
    const removed = draft.nodes[index], dependent = draft.nodes.filter((node) => node.after.includes(removed.task_id)).length;
    const next = compactSegments(draft.nodes.filter((_, position) => position !== index)
      .map((node) => ({ ...node, after: node.after.filter((id) => id !== removed.task_id) })));
    setPendingEdit({ nodes: next, description: `Remove ${titleFor(removed.task_id)}; remove ${dependent} prerequisite link${dependent === 1 ? "" : "s"} and compact checkpoint numbers.` });
  }
  function stageMove(index: number, delta: -1 | 1) {
    if (!draft) return;
    const target = index + delta;
    if (target < 0 || target >= draft.nodes.length) return;
    const next = [...draft.nodes]; [next[index], next[target]] = [next[target], next[index]];
    if (!graphValid(next)) return;
    setPendingEdit({ nodes: next, description: `Move ${titleFor(draft.nodes[index].task_id)} ${delta < 0 ? "up" : "down"}; dependency links and checkpoint numbers stay unchanged.` });
  }
  function stageCheckpoint(index: number, add: boolean) {
    if (!draft || index === 0) return;
    const node = draft.nodes[index], prior = draft.nodes[index - 1];
    if (add ? node.segment !== prior.segment : node.segment !== prior.segment + 1) return;
    const next = draft.nodes.map((item, position) => position < index ? item : { ...item, segment: item.segment + (add ? 1 : -1) });
    if (!graphValid(next)) return;
    setPendingEdit({ nodes: next, description: `${add ? "Add" : "Remove"} the owner checkpoint before ${titleFor(node.task_id)}; later checkpoint numbers shift.` });
  }
  async function compareDependencies() {
    if (!draft || !draft.nodes.length) return;
    setComparison(null);
    const canonical: Array<[string, string]> = [];
    for (const node of draft.nodes) {
      const result = await readPlanningTaskDependencies(node.task_id);
      if (result.task_revision !== node.expected_task_revision || result.prerequisites_truncated) throw new PublicProjectPlanError("task_changed");
      for (const item of result.prerequisites) canonical.push([node.task_id, item.id]);
    }
    const planned = draft.nodes.flatMap((node) => node.after.map((id): [string, string] => [node.task_id, id]));
    const key = ([taskId, predecessor]: [string, string]) => `${taskId}\0${predecessor}`;
    const canonicalSet = new Set(canonical.map(key)), plannedSet = new Set(planned.map(key));
    if (mounted.current) setComparison({ fingerprint: JSON.stringify(draft.nodes),
      missing: canonical.filter((edge) => !plannedSet.has(key(edge))),
      additional: planned.filter((edge) => !canonicalSet.has(key(edge))), acknowledged: false });
  }
  async function save() {
    if (!draft || !canSave || !view) return;
    const submitted = draft;
    let result;
    try { result = await projectPlans("publish", { project_id: projectId,
      expected_project_revision: submitted.projectRevision, expected_plan_revision: submitted.planRevision,
      title: submitted.title, nodes: submitted.nodes }); }
    catch (error) {
      if (!(error instanceof PublicProjectPlanError) || ["unavailable", "invalid_response"].includes(error.code))
        onDraftChange((current) => current === submitted ? { ...current, unresolved: true } : current);
      throw error;
    }
    const reconciling = { ...submitted, unresolved: true };
    onDraftChange((current) => current === submitted ? reconciling : current);
    published.current = { id: result.id, revision: result.revision, draft: reconciling };
    try { await refresh(); }
    catch { if (mounted.current) { onDraftChange((current) => current === submitted ? { ...current, unresolved: true } : current); setNotice("The plan was accepted, but readback is unavailable. Your draft remains until you refresh and verify it."); } }
  }
  const exact = draft?.nodes.every((node) => { const item = prepared[node.task_id]; return item?.exactGrant && item.revision === node.expected_task_revision
    && item.agentId === node.agent_id && item.inputId === node.input_version_id; }) ?? false;
  let canSave = !!draft && !!view && view.project.status === "active" && !draft.unresolved && !pendingEdit && !busy
    && draft.projectRevision === view.project.revision && draft.planRevision === view.plan_revision && exact
    && !!comparison && comparison.fingerprint === JSON.stringify(draft.nodes)
    && (!comparison.missing.length && !comparison.additional.length || comparison.acknowledged);
  if (canSave) { try { projectPlanRequest("publish", { project_id: projectId, expected_project_revision: draft!.projectRevision,
    expected_plan_revision: draft!.planRevision, title: draft!.title, nodes: draft!.nodes }); } catch { canSave = false; } }
  const shown = candidates.filter((task) => !filter || task.title.toLowerCase().includes(filter.toLowerCase()) || task.id.toLowerCase().includes(filter.toLowerCase()));

  return <section aria-label="Project plan" className="project-context-panel">
    <div className="project-context-heading"><h3>Project plan</h3><button aria-expanded={open} disabled={busy} onClick={() => { setOpen(!open); if (!open && !view) void perform(start); }} type="button">{open ? "Hide plan" : "Open plan"}</button></div>
    {open ? <div className="project-context-body"><p>Prepare a Task order and owner checkpoints. Saving a plan never starts Agents or approves execution.</p><p aria-live="polite" role="status">{busy ? "Checking…" : notice}</p><div className="project-context-actions"><button disabled={busy} onClick={() => void perform(refresh)} type="button">Refresh plan</button></div>
      {view ? <><p>{view.plan_revision ? `Current plan version ${view.plan_revision} · unapproved` : "No saved plan yet."} {view.execution_available ? "" : "Project execution is unavailable."}</p>
        {view.stale_reasons.length ? <p>Review needed: {view.stale_reasons.map((reason) => reason.replaceAll("_", " ")).join(", ")}.</p> : null}
        {view.dependency_comparison.missing_count || view.dependency_comparison.additional_count ? <p>Saved plan differs from Task prerequisites: {view.dependency_comparison.missing_count} missing, {view.dependency_comparison.additional_count} additional.</p> : null}
        {view.versions.length ? <ul>{view.versions.map((item) => <li key={item.id}><button disabled={busy} onClick={() => void perform(async () => { const version = await projectPlans("version", { project_id: projectId, version_id: item.id }); if (mounted.current) setHistory(version); })} type="button">View version {item.revision}</button> · {item.title}</li>)}</ul> : null}
        {history ? <section aria-label="Saved plan version"><h4>{history.title} · version {history.revision}{history.current ? " · current" : ""}</h4><ol>{history.nodes.map((node) => <li key={node.task_id}>{node.task_state === "current" ? node.task_title : `${node.task_id} (${node.task_state})`} ({node.agent_state === "current" ? node.agent_name : `${node.agent_id} (${node.agent_state})`}) · input {node.input_version_id} · checkpoint {node.segment}{node.after.length ? ` · after ${node.after.map(historicalTitleFor).join(", ")}` : ""}</li>)}</ol><p>Unapproved history; this version cannot start work.</p></section> : null}
        {!draft && view.project.status === "active" ? <button disabled={busy} onClick={beginEdit} type="button">{view.current ? "Edit plan" : "Create plan"}</button> : null}
      </> : !busy ? <p>Plan authority is unavailable. Refresh to try again.</p> : null}
      {draft ? <section aria-label="Plan draft" className="project-plan-draft"><p>This is a local draft. Version-1 plans cannot be approved for execution.</p>{draft.unresolved ? <p>A save may have reached Mentat. Refresh the saved plan and choose explicitly before retrying.</p> : null}
        <label>Plan title<input disabled={busy} maxLength={120} onChange={(event) => change((current) => ({ ...current, title: event.target.value }))} value={draft.title} /></label>
        <label>Find a Task in loaded pages<input maxLength={160} onChange={(event) => setFilter(event.target.value)} type="search" value={filter} /></label>
        <ul aria-label="Plan Task candidates">{shown.filter((task) => !draft.nodes.some((node) => node.task_id === task.id)).map((task) => <li key={task.id}><span>{task.title}</span><button disabled={busy || draft.nodes.length >= 32} onClick={() => void perform(() => addTask(task.id))} type="button">Add {task.title}</button></li>)}</ul>
        <div className="project-context-actions"><button disabled={busy} onClick={() => void perform(() => loadCandidates())} type="button">Refresh Task choices</button>{nextCursor ? <button disabled={busy} onClick={() => void perform(() => loadCandidates(nextCursor))} type="button">Load more Project Tasks</button> : null}</div>
        <ol aria-label="Planned Tasks">{draft.nodes.map((node, index) => { const item = prepared[node.task_id]; const matches = item?.revision === node.expected_task_revision && item.agentId === node.agent_id && item.inputId === node.input_version_id;
          const earlier = draft.nodes.slice(0, index);
          return <li key={node.task_id} className="project-plan-node"><h4>{titleFor(node.task_id)}</h4><p>Agent: {agentName(node.agent_id)} · Task revision {node.expected_task_revision} · saved input {node.input_version_id}</p><p>Checkpoint segment {node.segment}{index && node.segment > draft.nodes[index - 1].segment ? " · owner review before this Task" : ""}</p><p>{item === undefined ? "Task preparation has not been checked." : matches ? "Current Task inputs match this plan." : "Task assignment, input or grant changed. Use the current preparation explicitly."}</p><div className="project-context-actions"><button disabled={busy} onClick={() => void perform(async () => { const checked = await taskPreparation(node.task_id); if (mounted.current) setPrepared((current) => ({ ...current, [node.task_id]: checked })); })} type="button">Check Task inputs</button>{item && !matches ? <button disabled={busy} onClick={() => applyCurrentInput(node.task_id)} type="button">Use current Task inputs</button> : null}<button disabled={busy} onClick={() => onOpenTask(node.task_id)} type="button">Open Task</button></div>
            <fieldset><legend>After these planned Tasks</legend>{earlier.map((prior) => <label key={prior.task_id}><input checked={node.after.includes(prior.task_id)} disabled={busy} onChange={(event) => change((current) => ({ ...current, nodes: current.nodes.map((entry) => entry.task_id === node.task_id ? { ...entry, after: event.target.checked ? [...entry.after, prior.task_id] : entry.after.filter((id) => id !== prior.task_id) } : entry) }))} type="checkbox" />{titleFor(prior.task_id)}</label>)}</fieldset>
            <div className="project-plan-limits"><label>Attempts<input disabled={busy} min={1} max={3} onChange={(event) => change((current) => ({ ...current, nodes: current.nodes.map((entry) => entry.task_id === node.task_id ? { ...entry, max_attempts: Number(event.target.value) } : entry) }))} type="number" value={node.max_attempts} /></label><label>Wall time (seconds)<input disabled={busy} min={60} max={86400} onChange={(event) => change((current) => ({ ...current, nodes: current.nodes.map((entry) => entry.task_id === node.task_id ? { ...entry, max_wall_seconds: Number(event.target.value) } : entry) }))} type="number" value={node.max_wall_seconds} /></label><label>Requested work units<input disabled={busy} min={1} max={1000} onChange={(event) => change((current) => ({ ...current, nodes: current.nodes.map((entry) => entry.task_id === node.task_id ? { ...entry, max_work_units: Number(event.target.value) } : entry) }))} type="number" value={node.max_work_units} /></label></div>
            <div className="project-context-actions"><button disabled={busy || index === 0 || !graphValid(draft.nodes.map((entry, position) => position === index - 1 ? draft.nodes[index] : position === index ? draft.nodes[index - 1] : entry))} onClick={() => stageMove(index, -1)} type="button">Move up</button><button disabled={busy || index === draft.nodes.length - 1 || !graphValid(draft.nodes.map((entry, position) => position === index + 1 ? draft.nodes[index] : position === index ? draft.nodes[index + 1] : entry))} onClick={() => stageMove(index, 1)} type="button">Move down</button><button disabled={busy || index === 0 || node.segment !== draft.nodes[index - 1].segment} onClick={() => stageCheckpoint(index, true)} type="button">Add checkpoint before</button><button disabled={busy || index === 0 || node.segment !== draft.nodes[index - 1].segment + 1} onClick={() => stageCheckpoint(index, false)} type="button">Merge checkpoint</button><button disabled={busy} onClick={() => stageRemoval(index)} type="button">Remove Task</button></div>
          </li>; })}</ol>
        {pendingEdit ? <div className="project-context-confirmation"><p>{pendingEdit.description}</p><div className="project-context-actions"><button disabled={busy} onClick={() => { change((current) => ({ ...current, nodes: pendingEdit.nodes })); setPendingEdit(null); }} type="button">Apply plan edit</button><button disabled={busy} onClick={() => setPendingEdit(null)} type="button">Cancel edit</button></div></div> : null}
        <div className="project-context-actions"><button disabled={busy || !draft.nodes.length || !!pendingEdit} onClick={() => void perform(checkTasks)} type="button">Check all Task inputs</button><button disabled={busy || !draft.nodes.length || !exact || !!pendingEdit} onClick={() => void perform(compareDependencies)} type="button">Review Task dependencies</button></div>
        {comparison && comparison.fingerprint === JSON.stringify(draft.nodes) ? <section aria-label="Dependency comparison"><p>Canonical Task prerequisites missing from this plan: {comparison.missing.length}. Extra plan sequencing links: {comparison.additional.length}. Saving does not edit Task prerequisites.</p>{comparison.missing.length ? <ul>{comparison.missing.map(([taskId, predecessor]) => <li key={`${taskId}:${predecessor}`}>{titleFor(taskId)} needs {titleFor(predecessor)}</li>)}</ul> : null}{comparison.additional.length ? <ul>{comparison.additional.map(([taskId, predecessor]) => <li key={`${taskId}:${predecessor}`}>{titleFor(taskId)} follows {titleFor(predecessor)} only in this plan</li>)}</ul> : null}{comparison.missing.length || comparison.additional.length ? <button disabled={busy || comparison.acknowledged} onClick={() => setComparison((current) => current ? { ...current, acknowledged: true } : current)} type="button">I reviewed these differences</button> : <p>Plan and canonical Task prerequisites match.</p>}</section> : null}
        <div className="project-context-actions"><button disabled={!canSave || busy} onClick={() => void perform(save)} type="button">Save plan version</button><button disabled={busy} onClick={() => { onDraftChange(() => null); setComparison(null); setPrepared({}); setReconciledRevision(null); }} type="button">Discard draft</button>
          {draft.unresolved && reconciledRevision !== null && view && view.plan_revision > draft.planRevision && history?.id === view.versions[0]?.id ? <button disabled={busy} onClick={() => { onDraftChange(() => null); setComparison(null); setReconciledRevision(null); }} type="button">Use reviewed saved plan</button> : null}
          {draft.unresolved && reconciledRevision === draft.planRevision && view?.project.revision === draft.projectRevision ? <button disabled={busy} onClick={() => { onDraftChange((current) => current ? { ...current, unresolved: false } : current); setPrepared({}); setComparison(null); setReconciledRevision(null); }} type="button">Retry after review</button> : null}
        </div>
      </section> : null}
    </div> : null}
  </section>;
}
