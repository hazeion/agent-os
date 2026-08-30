"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";

import {
  readConversationPlanningContext,
  readPlanningTasks,
  updateConversationPlanningContext,
  type PublicConversationPlanningContext,
  type PublicPlanningOverview,
  type PublicPlanningTask,
} from "@/lib/public-planning";
import type { PublicConversation } from "@/lib/bridge-conversations";

export type PlanningSelection = { projectId: string | null; taskId: string | null };

function contextLabel(context: PublicConversationPlanningContext | null): string {
  if (!context?.association) return "No planning context";
  if (context.state === "project_unavailable") return "Project unavailable";
  if (context.state === "task_unavailable") return "Task unavailable";
  if (context.state === "project_mismatch") return "Task moved";
  return context.task ? `${context.project?.name ?? "Project"} · ${context.task.title}` : context.project?.name ?? "Project context";
}

export const ConversationPlanningControls = memo(function ConversationPlanningControls({
  busy,
  context,
  contextState,
  conversationId,
  conversationRevision,
  clearDisabledReason,
  disabledReason,
  onContext,
  onConversation,
  onNotice,
  onRefreshConversation,
  onSelection,
  overview,
  overviewState,
  selection,
}: Readonly<{
  busy: boolean;
  context: PublicConversationPlanningContext | null;
  contextState: "loading" | "ready" | "unavailable" | "error";
  conversationId: string;
  conversationRevision: number;
  clearDisabledReason: string | null;
  disabledReason: string | null;
  onContext: (context: PublicConversationPlanningContext) => void;
  onConversation: (conversation: PublicConversation) => void;
  onNotice: (message: string) => void;
  onRefreshConversation: () => Promise<void>;
  onSelection: (selection: PlanningSelection) => void;
  overview: PublicPlanningOverview | null;
  overviewState: "loading" | "ready" | "unavailable" | "error";
  selection: PlanningSelection;
}>) {
  const [open, setOpen] = useState(false);
  const [mutationBusy, setMutationBusy] = useState(false);
  const [tasks, setTasks] = useState<PublicPlanningTask[]>([]);
  const [tasksState, setTasksState] = useState<"idle" | "loading" | "loading_more" | "ready" | "unavailable" | "error">("idle");
  const [taskCursor, setTaskCursor] = useState<string | null>(null);
  const request = useRef(0);
  const onSelectionRef = useRef(onSelection);
  const canonical = context?.association ?? { project_id: null, task_id: null };
  const changed = selection.projectId !== canonical.project_id || selection.taskId !== canonical.task_id;

  useEffect(() => { onSelectionRef.current = onSelection; }, [onSelection]);

  useEffect(() => {
    if (!selection.projectId) { setTasks([]); setTaskCursor(null); setTasksState("idle"); return; }
    const sequence = request.current + 1;
    request.current = sequence;
    setTasksState("loading");
    setTaskCursor(null);
    void readPlanningTasks(selection.projectId, null).then((page) => {
      if (request.current !== sequence) return;
      const retained = context?.task?.project_id === selection.projectId
        && !page.tasks.some((task) => task.id === context.task?.id)
        ? [...page.tasks, context.task]
        : page.tasks;
      setTasks(retained);
      setTaskCursor(page.next_cursor);
      setTasksState("ready");
    }).catch(() => { if (request.current === sequence) setTasksState("unavailable"); });
    return () => { request.current += 1; };
  }, [context?.task, selection.projectId]);

  async function loadMoreTasks() {
    if (!selection.projectId || !taskCursor || tasksState === "loading_more") return;
    const projectId = selection.projectId;
    const cursor = taskCursor;
    setTasksState("loading_more");
    try {
      const page = await readPlanningTasks(projectId, cursor);
      if (selection.projectId !== projectId) return;
      setTasks((current) => [...current, ...page.tasks.filter((task) => !current.some((item) => item.id === task.id))]);
      setTaskCursor(page.next_cursor);
      setTasksState("ready");
    } catch { setTasksState("unavailable"); }
  }

  const working = busy || mutationBusy || contextState !== "ready";

  async function apply(next: PlanningSelection) {
    if (working || (next.projectId ? disabledReason : clearDisabledReason)) return;
    setMutationBusy(true);
    onNotice(next.projectId ? "Applying the exact planning context…" : "Clearing the exact planning context…");
    try {
      const result = await updateConversationPlanningContext(conversationId, conversationRevision, next.projectId, next.taskId);
      onConversation(result.conversation);
      const updatedContext: PublicConversationPlanningContext = {
        association: result.association,
        conversation_id: result.conversation_id,
        conversation_revision: result.conversation_revision,
        project: result.project,
        runtime: result.runtime,
        schema_version: result.schema_version,
        service: result.service,
        state: result.state,
        status: result.status,
        task: result.task,
      };
      onContext(updatedContext);
      onSelection({ projectId: updatedContext.association?.project_id ?? null, taskId: updatedContext.association?.task_id ?? null });
      setOpen(false);
      onNotice(next.projectId ? "Planning context applied. No Task or Run was changed." : "Planning context cleared. No Task or Run was changed.");
    } catch (error) {
      let refreshed: PublicConversationPlanningContext | null = null;
      const conflict = error && typeof error === "object" && "code" in error && String((error as { code: string }).code).includes("conflict");
      if (conflict) {
        try { await onRefreshConversation(); } catch { /* Preserve staged state and report below. */ }
      }
      try { refreshed = await readConversationPlanningContext(conversationId); } catch { /* Preserve the staged choice. */ }
      if (refreshed) onContext(refreshed);
      onNotice(conflict
        ? "This Conversation changed. Canonical context was refreshed and your staged choice was kept."
        : "Planning context could not be verified. Your staged choice was kept.");
    } finally { setMutationBusy(false); }
  }

  const project = overview?.projects.find((item) => item.id === selection.projectId) ?? null;
  const staleProject = selection.projectId && !project;
  const staleTask = selection.taskId && !tasks.some((task) => task.id === selection.taskId);
  return <details className="composer-planning" onToggle={(event) => setOpen(event.currentTarget.open)} open={open}>
    <summary><span>Planning context</span><strong>{contextState === "loading" ? "Loading…" : contextState === "ready" ? contextLabel(context) : "Unavailable"}</strong></summary>
    <div className="composer-planning-panel">
      {overviewState === "ready" && overview ? <div className="composer-planning-fields">
        <label><span>Project</span><select aria-label="Project planning context" disabled={working || !!disabledReason} onChange={(event) => onSelection({ projectId: event.target.value || null, taskId: null })} value={selection.projectId ?? ""}><option value="">No Project</option>{staleProject ? <option value={selection.projectId ?? ""}>Unavailable Project</option> : null}{overview.projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label><span>Task</span><select aria-label="Task planning context" disabled={working || !!disabledReason || !selection.projectId || !new Set(["ready", "loading_more"]).has(tasksState)} onChange={(event) => onSelection({ projectId: selection.projectId, taskId: event.target.value || null })} value={selection.taskId ?? ""}><option value="">{tasksState === "loading" ? "Loading Tasks…" : "No Task"}</option>{staleTask ? <option value={selection.taskId ?? ""}>Unavailable Task</option> : null}{tasks.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
      </div> : <p className="composer-planning-status">{overviewState === "loading" ? "Loading safe Projects and Tasks…" : "Planning context is temporarily unavailable."}</p>}
      {taskCursor ? <button className="planning-load-more" disabled={working || tasksState === "loading_more"} onClick={() => void loadMoreTasks()} type="button">{tasksState === "loading_more" ? "Loading…" : "More"}</button> : null}
      {project ? <p className="composer-planning-status">Changes apply only after Apply. They never update the Project or Task.</p> : null}
      {context?.association && context.state !== "ready" ? <p className="composer-planning-status">This saved planning reference is stale. Rebind it to an available Project or clear it; no Task content was used.</p> : null}
      {disabledReason ? <p className="composer-planning-status">{disabledReason}</p> : null}
      <div className="composer-planning-actions">
        <button disabled={working || !!disabledReason || !changed || !selection.projectId} onClick={() => void apply(selection)} type="button">{working ? "Applying…" : "Apply"}</button>
        <button disabled={working || !!clearDisabledReason || !context?.association} onClick={() => { onSelection({ projectId: null, taskId: null }); void apply({ projectId: null, taskId: null }); }} type="button">Clear</button>
        <button disabled={working} onClick={() => { onSelection({ projectId: canonical.project_id, taskId: canonical.task_id }); setOpen(false); }} type="button">Cancel</button>
      </div>
    </div>
  </details>;
});

export const PlanningSuggestions = memo(function PlanningSuggestions({
  context,
  draftEmpty,
  onChoose,
}: Readonly<{
  context: PublicConversationPlanningContext | null;
  draftEmpty: boolean;
  onChoose: (text: string) => void;
}>) {
  const suggestions = useMemo(() => {
    if (!draftEmpty || !context?.association || context.state !== "ready") return [];
    const subject = context.task?.title ?? context.project?.name;
    if (!subject) return [];
    const rows = [
      { label: "Plan next steps", text: `Plan the next concrete steps for ${subject}.` },
      { label: "Review status", text: `Review the current status of ${subject} and identify what needs attention.` },
    ];
    if (context.task?.attention_reasons.length) rows.push({ label: "Resolve attention", text: `Help me resolve the attention needed for ${subject}.` });
    return rows.slice(0, 3);
  }, [context, draftEmpty]);
  if (!suggestions.length) return null;
  return <div aria-label="Planning prompt suggestions" className="planning-suggestions">{suggestions.map((item) => <button key={item.label} onClick={() => onChoose(item.text)} type="button">{item.label}</button>)}</div>;
});

export const PlanningAttention = memo(function PlanningAttention({ overview, state }: Readonly<{
  overview: PublicPlanningOverview | null;
  state: "loading" | "ready" | "unavailable" | "error";
}>) {
  const rows = overview?.attention.slice(0, 8) ?? [];
  return <section aria-label="Planning attention" className="planning-attention">
    <div className="planning-attention-heading"><p className="console-kicker">Planning</p><h3>Planning attention</h3></div>
    {state === "loading" ? <p>Loading planning attention…</p> : state !== "ready" ? <p>Planning attention is temporarily unavailable.</p> : rows.length === 0 ? <p>No planning attention right now.</p> : <ul>{rows.map((task, index) => <li key={task.id}><a aria-label={`Open ${task.title}, planning item ${index + 1} in Tasks`} href={`/tasks?project=${encodeURIComponent(task.project_id)}&task=${encodeURIComponent(task.id)}`}><strong>{task.title}</strong><span>{task.attention_reasons.map((reason) => reason.replaceAll("_", " ")).join(" · ") || "Needs attention"}</span>{task.due_date ? <time dateTime={task.due_date}>Due {task.due_date}</time> : null}</a></li>)}</ul>}
    <a className="planning-view-all" href="/tasks">View all Tasks</a>
  </section>;
});
