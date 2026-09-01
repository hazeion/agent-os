"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { PublicAgent } from "@/lib/bridge-agents";
import {
  createProject,
  createProjectTask,
  readPlanningTask,
  readPlanningOverview,
  readPlanningTasks,
  type PublicPlanningOverview,
  type PublicPlanningTaskListItem,
} from "@/lib/public-planning";

type LoadState = "loading" | "ready" | "empty" | "unavailable" | "error";

function requestedTask(): { projectId: string | null; taskId: string } | null | false {
  const entries = [...new URL(window.location.href).searchParams.entries()];
  if (!entries.length) return null;
  if (entries.length === 1 && entries[0][0] === "task" && /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u.test(entries[0][1])) return { projectId: null, taskId: entries[0][1] };
  if (entries.length !== 2 || new Set(entries.map(([key]) => key)).size !== 2) return false;
  const projectId = entries.find(([key]) => key === "project")?.[1];
  const taskId = entries.find(([key]) => key === "task")?.[1];
  if (!projectId || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u.test(projectId) || !taskId || !/^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u.test(taskId)) return false;
  return { projectId, taskId };
}

async function readAgents(): Promise<PublicAgent[]> {
  const response = await fetch("/api/agents", { cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json" } });
  const payload = await response.json() as Record<string, unknown>;
  if (response.status !== 200 || Object.keys(payload).sort().join(",") !== "agents,count,runtime,schema_version,service,status" || payload.schema_version !== 1 || payload.service !== "mentat-local-bridge" || payload.runtime !== "python" || payload.status !== "ready" || !Array.isArray(payload.agents) || payload.agents.length > 128 || payload.count !== payload.agents.length) throw new Error("agents_unavailable");
  const agents = payload.agents as Array<Record<string, unknown>>;
  if (!agents.every((item) => Object.keys(item).sort().join(",") === "capabilities,id,name,runtime_config_id,runtime_type" && typeof item.id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(item.id) && typeof item.name === "string" && item.name.trim() === item.name && item.name.length > 0 && item.name.length <= 120 && typeof item.runtime_config_id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(item.runtime_config_id) && typeof item.runtime_type === "string" && /^[a-z][a-z0-9_-]{0,31}$/u.test(item.runtime_type) && Array.isArray(item.capabilities) && item.capabilities.length <= 64 && item.capabilities.every((capability) => typeof capability === "string" && /^[a-z][a-z0-9_.-]{0,63}$/u.test(capability)))) throw new Error("agents_invalid");
  return agents.map((item) => ({ capabilities: [...item.capabilities as string[]], id: String(item.id), name: String(item.name), runtime_config_id: String(item.runtime_config_id), runtime_type: String(item.runtime_type) }));
}

export function ProjectsTasksWorkspace() {
  const [overview, setOverview] = useState<PublicPlanningOverview | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [tasks, setTasks] = useState<PublicPlanningTaskListItem[]>([]);
  const [tasksState, setTasksState] = useState<LoadState>("loading");
  const [taskCursor, setTaskCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [agents, setAgents] = useState<PublicAgent[]>([]);
  const [agentsState, setAgentsState] = useState<"loading" | "ready" | "empty" | "unavailable">("loading");
  const [projectForm, setProjectForm] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [taskForm, setTaskForm] = useState(false);
  const [taskFormProjectId, setTaskFormProjectId] = useState<string | null>(null);
  const [taskTitle, setTaskTitle] = useState("");
  const [taskAgent, setTaskAgent] = useState("");
  const [taskDue, setTaskDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const projectInput = useRef<HTMLInputElement>(null);
  const taskInput = useRef<HTMLInputElement>(null);
  const newProjectButton = useRef<HTMLButtonElement>(null);
  const addTaskButton = useRef<HTMLButtonElement>(null);
  const projectSelectionGeneration = useRef(0);
  const requestedTaskFocus = useRef<string | null>(null);
  const selectedProjectRef = useRef<string | null>(null);
  const requested = useMemo(() => typeof window === "undefined" ? null : requestedTask(), []);

  async function refreshOverview(preferredProjectId: string | null = null) {
    const value = await readPlanningOverview();
    setOverview(value);
    setState(value.projects.length ? "ready" : "empty");
    const requestedProject = requested && typeof requested === "object"
      ? requested.projectId !== null
        ? value.projects.some((item) => item.id === requested.projectId) ? requested.projectId : null
        : null
      : null;
    setSelectedProjectId((current) => {
      const next = preferredProjectId ?? requestedProject ?? (current && value.projects.some((item) => item.id === current) ? current : value.projects[0]?.id ?? null);
      selectedProjectRef.current = next;
      return next;
    });
  }

  function closeTaskForm() {
    setTaskForm(false); setTaskFormProjectId(null); setTaskTitle(""); setTaskAgent(""); setTaskDue("");
  }

  function selectProject(projectId: string) {
    projectSelectionGeneration.current += 1;
    requestedTaskFocus.current = null;
    selectedProjectRef.current = projectId;
    setSelectedProjectId(projectId);
    closeTaskForm();
  }

  useEffect(() => {
    let cancelled = false;
    void readPlanningOverview().then((planning) => {
        if (cancelled) return;
        setOverview(planning);
        setState(planning.projects.length ? "ready" : "empty");
        const requestedProject = requested && typeof requested === "object"
          ? requested.projectId !== null
            ? planning.projects.some((item) => item.id === requested.projectId) ? requested.projectId : null
            : null
          : null;
        setSelectedProjectId((current) => {
          const selected = requested && typeof requested === "object" && requested.projectId === null
            ? current
            : requestedProject ?? planning.projects[0]?.id ?? null;
          selectedProjectRef.current = selected;
          return selected;
        });
        if (requested && typeof requested === "object" && requested.projectId && !requestedProject) setNotice("The requested Project could not be found.");
    }).catch(() => { if (!cancelled) setState("unavailable"); });
    void readAgents().then((rows) => {
      if (!cancelled) { setAgents(rows); setAgentsState(rows.length ? "ready" : "empty"); }
    }).catch(() => { if (!cancelled) setAgentsState("unavailable"); });
    return () => { cancelled = true; };
  }, [requested]);

  useEffect(() => {
    if (!requested || requested.projectId !== null) return;
    let cancelled = false;
    const selectionGeneration = projectSelectionGeneration.current;
    void readPlanningTask(requested.taskId).then((result) => {
      if (cancelled || projectSelectionGeneration.current !== selectionGeneration) return;
      selectedProjectRef.current = result.project.id;
      setSelectedProjectId(result.project.id);
    }).catch(() => { if (!cancelled) setNotice("The requested Task could not be found."); });
    return () => { cancelled = true; };
  }, [requested]);

  useEffect(() => {
    if (!selectedProjectId) { void Promise.resolve().then(() => { setTasks([]); setTaskCursor(null); setTasksState("empty"); }); return; }
    const projectId = selectedProjectId;
    let cancelled = false;
    void Promise.resolve().then(() => { if (!cancelled) setTasksState("loading"); });
    void readPlanningTasks(projectId, null).then(async (page) => {
      if (cancelled) return;
      let rows = [...page.tasks];
      let cursor = page.next_cursor;
      setTasks(rows);
      setTaskCursor(cursor);
      setTasksState(rows.length ? "ready" : "empty");
      if (requested && typeof requested === "object" && (requested.projectId === null || requested.projectId === projectId)) {
        let target = rows.find((task) => task.id === requested.taskId) ?? null;
        try {
          for (let pageIndex = 1; !target && cursor && pageIndex < 42; pageIndex += 1) {
            const next = await readPlanningTasks(projectId, cursor);
            if (cancelled) return;
            rows = [...rows, ...next.tasks.filter((task) => !rows.some((item) => item.id === task.id))];
            cursor = next.next_cursor;
            target = rows.find((task) => task.id === requested.taskId) ?? null;
            setTasks(rows);
            setTaskCursor(cursor);
          }
        } catch {
          if (!cancelled) setNotice("More Tasks could not be loaded; the verified Tasks shown remain available.");
          return;
        }
        if (target) {
          requestedTaskFocus.current = requested.taskId;
          setTasks([...rows]);
        }
        else setNotice("The requested Task could not be found in this Project.");
      }
      else if (requested === false) setNotice("The requested Task link is invalid.");
    }).catch(() => { if (!cancelled) setTasksState("unavailable"); });
    return () => { cancelled = true; };
  }, [requested, selectedProjectId]);

  useEffect(() => {
    const taskId = requestedTaskFocus.current;
    if (!taskId) return;
    const target = document.querySelector<HTMLElement>(`[data-planning-task-id="${CSS.escape(taskId)}"]`);
    if (!target) return;
    requestedTaskFocus.current = null;
    target.dataset.taskSelected = "true";
    target.focus({ preventScroll: true });
    target.scrollIntoView({ block: "center", behavior: "auto" });
    setNotice(`Opened Task ${target.dataset.taskTitle}.`);
  }, [tasks]);

  async function loadMoreTasks() {
    if (!selectedProjectId || !taskCursor || loadingMore) return;
    const projectId = selectedProjectId;
    setLoadingMore(true);
    try {
      const page = await readPlanningTasks(projectId, taskCursor);
      if (selectedProjectRef.current !== projectId) return;
      setTasks((current) => [...current, ...page.tasks.filter((task) => !current.some((item) => item.id === task.id))]);
      setTaskCursor(page.next_cursor);
      setTasksState("ready");
    } catch { setNotice("More Tasks could not be loaded; the verified Tasks shown remain available."); }
    finally { setLoadingMore(false); }
  }

  async function submitProject() {
    const name = projectName.trim();
    if (!name || busy) return;
    setBusy(true); setNotice("Creating Project…");
    try {
      const created = await createProject(name);
      setProjectName(""); setProjectForm(false);
      await refreshOverview(created.id);
      setNotice(`Project ${created.name} created.`);
      window.setTimeout(() => document.querySelector<HTMLElement>(`[data-project-id="${CSS.escape(created.id)}"]`)?.focus(), 0);
    } catch { setNotice("Project could not be created. Your name was kept."); projectInput.current?.focus(); }
    finally { setBusy(false); }
  }

  async function submitTask() {
    const title = taskTitle.trim();
    if (!taskFormProjectId || taskFormProjectId !== selectedProjectRef.current || !title || busy) return;
    const projectId = taskFormProjectId;
    setBusy(true); setNotice("Creating Task…");
    try {
      const created = await createProjectTask(projectId, title, taskAgent || null, taskDue || null);
      closeTaskForm();
      if (selectedProjectRef.current === projectId) {
        setTasks((current) => [{ ...created, description_preview: "" }, ...current.filter((item) => item.id !== created.id)]);
        setTasksState("ready");
        window.setTimeout(() => document.querySelector<HTMLElement>(`[data-planning-task-id="${CSS.escape(created.id)}"]`)?.focus(), 0);
      }
      setNotice(`Task ${created.title} created.`);
    } catch { setNotice("Task could not be created. Your details were kept."); taskInput.current?.focus(); }
    finally { setBusy(false); }
  }

  const selectedProject = overview?.projects.find((item) => item.id === selectedProjectId) ?? null;
  return <section aria-label="Projects and Tasks" className="projects-tasks-workspace">
    <div className="projects-pane">
      <div className="projects-tasks-heading"><div><p className="console-kicker">Projects</p><h2>Projects</h2></div><button disabled={busy} onClick={() => { closeTaskForm(); setProjectForm(true); window.setTimeout(() => projectInput.current?.focus(), 0); }} ref={newProjectButton} type="button">New</button></div>
      {projectForm ? <form className="project-create-form" onSubmit={(event) => { event.preventDefault(); void submitProject(); }}><label><span>Name</span><input onChange={(event) => { if ([...event.target.value].length <= 121) setProjectName(event.target.value); }} ref={projectInput} value={projectName} /></label><div><button aria-label="Create Project" disabled={busy || !projectName.trim() || [...projectName.trim()].length > 120} type="submit">Create</button><button aria-label="Cancel Project" disabled={busy} onClick={() => { setProjectForm(false); setProjectName(""); window.setTimeout(() => newProjectButton.current?.focus(), 0); }} type="button">Cancel</button></div></form> : null}
      {state === "loading" ? <p>Loading Projects…</p> : state === "unavailable" || state === "error" ? <p>Projects are temporarily unavailable.</p> : overview?.projects.length ? <ul>{overview.projects.map((project) => <li key={project.id}><button aria-current={project.id === selectedProjectId ? "true" : undefined} aria-label={`Select ${project.name} Project`} data-project-id={project.id} disabled={busy} onClick={() => selectProject(project.id)} type="button"><strong>{project.name}</strong><span>{project.status}</span></button></li>)}</ul> : <p>No Projects yet.</p>}
    </div>
    <div className="project-tasks-pane">
      <div className="projects-tasks-heading"><div><p className="console-kicker">Tasks</p><h2>{selectedProject?.name ?? "Tasks"}</h2></div><button disabled={busy || !selectedProjectId || selectedProject?.status !== "active"} onClick={() => { setProjectForm(false); setProjectName(""); setTaskFormProjectId(selectedProjectId); setTaskForm(true); window.setTimeout(() => taskInput.current?.focus(), 0); }} ref={addTaskButton} type="button">Add</button></div>
      {taskForm ? <form className="task-create-form" onSubmit={(event) => { event.preventDefault(); void submitTask(); }}><label><span>Title</span><input onChange={(event) => { if ([...event.target.value].length <= 161) setTaskTitle(event.target.value); }} ref={taskInput} value={taskTitle} /></label><label><span>Agent</span><select aria-describedby="task-agent-state" disabled={agentsState === "loading" || agentsState === "empty" || agentsState === "unavailable"} onChange={(event) => setTaskAgent(event.target.value)} value={taskAgent}><option value="">{agentsState === "loading" ? "Loading" : agentsState === "unavailable" ? "Unavailable" : agentsState === "empty" ? "No Agents" : "Unassigned"}</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label><p className="task-agent-state" id="task-agent-state">{agentsState === "unavailable" ? "Agent assignment is unavailable; Create will leave this Task unassigned." : agentsState === "empty" ? "No Agents are available; Create will leave this Task unassigned." : "Assignment is optional."}</p><label><span>Due</span><input onChange={(event) => setTaskDue(event.target.value)} type="date" value={taskDue} /></label><div><button aria-label="Create Task" disabled={busy || !taskTitle.trim() || [...taskTitle.trim()].length > 160} type="submit">Create</button><button aria-label="Cancel Task" disabled={busy} onClick={() => { closeTaskForm(); window.setTimeout(() => addTaskButton.current?.focus(), 0); }} type="button">Cancel</button></div></form> : null}
      {tasksState === "loading" ? <p>Loading Tasks…</p> : tasksState === "unavailable" || tasksState === "error" ? <p>Tasks are temporarily unavailable.</p> : tasks.length ? <ul className="project-task-list">{tasks.map((task) => <li data-planning-task-id={task.id} data-task-title={task.title} key={task.id} tabIndex={-1}><div><strong>{task.title}</strong>{task.description_preview ? <p>{task.description_preview}</p> : null}<span>{task.status} · {task.priority}</span></div>{task.due_date ? <time dateTime={task.due_date}>Due {task.due_date}</time> : null}</li>)}</ul> : <p>No Tasks in this Project.</p>}
      {taskCursor ? <button className="project-tasks-more" disabled={loadingMore} onClick={() => void loadMoreTasks()} type="button">{loadingMore ? "Loading…" : "More"}</button> : null}
    </div>
    <p aria-live="polite" className="projects-tasks-notice" role="status">{notice}</p>
  </section>;
}
