"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { PublicAgent } from "@/lib/bridge-agents";
import {
  createProject,
  createProjectTask,
  readPlanningTask,
  readPlanningTaskDependencies,
  readPlanningTaskDetail,
  readPlanningDependencyPicker,
  readPlanningOverview,
  readPlanningTasks,
  updatePlanningProject,
  updatePlanningTask,
  type PublicPlanningOverview,
  type PublicPlanningTask,
  type PublicPlanningTaskDetail,
  type PublicPlanningTaskListItem,
  type PublicPlanningTaskMutation,
  type PublicPlanningDependencyReference,
  type PublicPlanningTaskDependencies,
  PublicPlanningError,
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
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [taskDetail, setTaskDetail] = useState<PublicPlanningTaskDetail | null>(null);
  const [taskDependencies, setTaskDependencies] = useState<PublicPlanningTaskDependencies | null>(null);
  const [dependenciesState, setDependenciesState] = useState<LoadState>("loading");
  const [view, setView] = useState<"list" | "board">("list");
  const [savedView, setSavedView] = useState<"all" | "today" | "waiting" | "review" | "someday" | "completed">("all");
  const [filter, setFilter] = useState("");
  const [editingTask, setEditingTask] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editPriority, setEditPriority] = useState<PublicPlanningTask["priority"]>("medium");
  const [editDue, setEditDue] = useState("");
  const [editToday, setEditToday] = useState(false);
  const [editDescription, setEditDescription] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editEstimate, setEditEstimate] = useState("");
  const [editRecurrence, setEditRecurrence] = useState<"" | "daily" | "weekly" | "monthly" | "yearly">("");
  const [editSubtasks, setEditSubtasks] = useState<PublicPlanningTaskDetail["subtasks"]>([]);
  const [editAgent, setEditAgent] = useState("");
  const [editDependencies, setEditDependencies] = useState<PublicPlanningDependencyReference[]>([]);
  const [dependencyQuery, setDependencyQuery] = useState("");
  const [dependencyCandidates, setDependencyCandidates] = useState<PublicPlanningDependencyReference[]>([]);
  const [dependencyCursor, setDependencyCursor] = useState<string | null>(null);
  const [dependencyPickerState, setDependencyPickerState] = useState<LoadState>("empty");
  const [renameProject, setRenameProject] = useState(false);
  const [projectRename, setProjectRename] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const projectInput = useRef<HTMLInputElement>(null);
  const taskInput = useRef<HTMLInputElement>(null);
  const newProjectButton = useRef<HTMLButtonElement>(null);
  const addTaskButton = useRef<HTMLButtonElement>(null);
  const projectSelectionGeneration = useRef(0);
  const requestedTaskFocus = useRef<string | null>(null);
  const selectedProjectRef = useRef<string | null>(null);
  const dependencyPickerGeneration = useRef(0);
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
    setSelectedTaskId(null);
    setTaskDetail(null);
    setTaskDependencies(null);
    setDependenciesState("loading");
    setEditingTask(false);
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
      setSelectedTaskId((current) => rows.some((task) => task.id === current) ? current : null);
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
          setSelectedTaskId(requested.taskId); setTaskDetail(null); setEditingTask(false);
          setTasks([...rows]);
        }
        else setNotice("The requested Task could not be found in this Project.");
      }
      else if (requested === false) setNotice("The requested Task link is invalid.");
    }).catch(() => { if (!cancelled) setTasksState("unavailable"); });
    return () => { cancelled = true; };
  }, [requested, selectedProjectId]);

  useEffect(() => {
    if (!selectedTaskId) return;
    let cancelled = false;
    void readPlanningTaskDetail(selectedTaskId).then((result) => { if (!cancelled && result.task.id === selectedTaskId) setTaskDetail(result.task); }).catch(() => { if (!cancelled) setNotice("Task details could not be loaded. The Task list remains available."); });
    return () => { cancelled = true; };
  }, [selectedTaskId]);

  useEffect(() => {
    if (!selectedTaskId) return;
    let cancelled = false;
    void Promise.resolve().then(() => { if (!cancelled) { setDependenciesState("loading"); setTaskDependencies(null); } });
    void readPlanningTaskDependencies(selectedTaskId).then((result) => {
      if (cancelled || result.task_id !== selectedTaskId) return;
      setTaskDependencies(result); setDependenciesState("ready");
    }).catch(() => { if (!cancelled) setDependenciesState("unavailable"); });
    return () => { cancelled = true; };
  }, [selectedTaskId]);

  useEffect(() => {
    const generation = ++dependencyPickerGeneration.current;
    if (!editingTask || !selectedTaskId || dependenciesState !== "ready") return;
    let cancelled = false;
    void Promise.resolve().then(() => { if (!cancelled) { setDependencyPickerState("loading"); setDependencyCandidates([]); setDependencyCursor(null); } });
    void readPlanningDependencyPicker(selectedTaskId, dependencyQuery).then((result) => {
      if (cancelled || generation !== dependencyPickerGeneration.current || result.task_id !== selectedTaskId || result.query !== dependencyQuery) return;
      setDependencyCandidates(result.candidates); setDependencyCursor(result.next_cursor); setDependencyPickerState(result.candidates.length ? "ready" : "empty");
    }).catch(() => { if (!cancelled) setDependencyPickerState("unavailable"); });
    return () => { cancelled = true; };
  }, [dependencyQuery, dependenciesState, editingTask, selectedTaskId]);

  useEffect(() => {
    const taskId = requestedTaskFocus.current;
    if (!taskId) return;
    const target = document.querySelector<HTMLElement>(`[data-planning-task-id="${CSS.escape(taskId)}"] > button`);
    if (!target) return;
    requestedTaskFocus.current = null;
    target.focus({ preventScroll: true });
    target.scrollIntoView({ block: "center", behavior: "auto" });
    setNotice(`Opened Task ${target.parentElement?.dataset.taskTitle ?? ""}.`);
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
        setSelectedTaskId(created.id); setTaskDetail(null);
        setTasksState("ready");
        window.setTimeout(() => document.querySelector<HTMLElement>(`[data-planning-task-id="${CSS.escape(created.id)}"]`)?.focus(), 0);
      }
      setNotice(`Task ${created.title} created.`);
    } catch { setNotice("Task could not be created. Your details were kept."); taskInput.current?.focus(); }
    finally { setBusy(false); }
  }

  const selectedProject = overview?.projects.find((item) => item.id === selectedProjectId) ?? null;
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? null;
  const filteredTasks = tasks.filter((task) => {
    const query = filter.trim().toLocaleLowerCase();
    if (query && !`${task.title} ${task.description_preview}`.toLocaleLowerCase().includes(query)) return false;
    if (savedView === "all") return true;
    if (savedView === "today") return task.planned_for_today;
    if (savedView === "waiting") return task.workflow_stage === "waiting";
    if (savedView === "review") return task.workflow_stage === "review";
    if (savedView === "someday") return task.deferred;
    return task.workflow_stage === "done";
  });
  const selectTask = (task: PublicPlanningTaskListItem) => {
    setSelectedTaskId(task.id); setTaskDetail(null); setTaskDependencies(null); setEditingTask(false); setNotice(`Selected Task ${task.title}.`);
  };
  async function editSelected(changes: Record<string, unknown>, success: string): Promise<boolean> {
    if (!selectedTask || busy) return false;
    setBusy(true); setNotice("Saving Task…");
    let result: PublicPlanningTaskMutation;
    try {
      result = await updatePlanningTask(selectedTask.id, selectedTask.revision, changes);
      setTasks((current) => current.map((task) => task.id === result.task.id ? { ...task, ...result.task } : task));
    } catch (error) {
      if (error instanceof PublicPlanningError && error.code === "conflict") {
        try {
          const [detailed, relationships] = await Promise.all([readPlanningTaskDetail(selectedTask.id), readPlanningTaskDependencies(selectedTask.id)]);
          setTaskDetail(detailed.task); setTaskDependencies(relationships); setDependenciesState("ready");
          const preview = detailed.task.description.replace(/\s+/gu, " ").trim();
          setTasks((current) => current.map((task) => task.id === selectedTask.id ? { ...task, ...detailed.task, description_preview: preview.length > 280 ? `${preview.slice(0, 279).trimEnd()}…` : preview } : task));
          setNotice("Task changed elsewhere; its latest dependencies are shown. Review and save again.");
        } catch { setNotice("Task changed elsewhere or could not be saved. Refresh the Project and try again."); }
      } else setNotice("Task changed elsewhere or could not be saved. Refresh the Project and try again.");
      setBusy(false); return false;
    }
    try {
      const detailed = await readPlanningTaskDetail(result.task.id);
      setTaskDetail(detailed.task);
      const preview = detailed.task.description.replace(/\s+/gu, " ").trim();
      setTasks((current) => current.map((task) => task.id === result.task.id ? { ...task, description_preview: preview.length > 280 ? `${preview.slice(0, 279).trimEnd()}…` : preview } : task));
      try {
        const relationships = await readPlanningTaskDependencies(result.task.id);
        setTaskDependencies(relationships); setDependenciesState("ready");
      } catch { setDependenciesState("unavailable"); }
      setNotice(success);
    } catch { setNotice("Task saved. Its refreshed details are temporarily unavailable."); }
    setBusy(false);
    return true;
  }
  async function saveTaskDetails() {
    if (!selectedTask || !editTitle.trim()) return;
    const existingRecurrence = taskDetail?.recurrence ?? null;
    const recurrenceChange = editRecurrence === (existingRecurrence?.frequency ?? "") ? undefined : editRecurrence ? { frequency: editRecurrence, interval: 1 } : null;
    const saved = await editSelected({ title: editTitle.trim(), description: editDescription, priority: editPriority, due_date: editDue || null, planned_for_today: editToday, tags: editTags.split(",").map((tag) => tag.trim()).filter(Boolean), estimated_minutes: editEstimate ? Number(editEstimate) : null, ...(recurrenceChange === undefined ? {} : { recurrence: recurrenceChange }), subtasks: editSubtasks, assigned_agent_id: editAgent || null, ...(dependenciesState === "ready" ? { depends_on: editDependencies.map((dependency) => dependency.id) } : {}) }, "Task details saved.");
    if (saved) setEditingTask(false);
  }
  async function loadMoreDependencyCandidates() {
    if (!selectedTaskId || !dependencyCursor || dependencyPickerState === "loading") return;
    const taskId = selectedTaskId;
    const query = dependencyQuery;
    const cursor = dependencyCursor;
    const generation = dependencyPickerGeneration.current;
    setDependencyPickerState("loading");
    try {
      const page = await readPlanningDependencyPicker(taskId, query, cursor);
      if (generation !== dependencyPickerGeneration.current || page.task_id !== taskId || page.query !== query) return;
      setDependencyCandidates((current) => [...current, ...page.candidates.filter((candidate) => !current.some((item) => item.id === candidate.id))]);
      setDependencyCursor(page.next_cursor); setDependencyPickerState("ready");
    } catch {
      if (generation === dependencyPickerGeneration.current) setDependencyPickerState("unavailable");
    }
  }
  function dependencyText(dependency: PublicPlanningDependencyReference) {
    return `${dependency.title} · Project: ${dependency.project_name} · ${dependency.workflow_stage.replace("_", " ")}${dependency.blocked ? " · blocked" : ""}`;
  }
  async function changeStage(stage: PublicPlanningTask["workflow_stage"]) {
    await editSelected({ workflow_stage: stage }, `Task moved to ${stage.replace("_", " ")}.`);
  }
  async function lifecycle(action: "archive" | "restore") {
    if (!selectedProject || busy) return;
    setBusy(true); setNotice(`${action === "archive" ? "Archiving" : "Restoring"} Project…`);
    try { const result = await updatePlanningProject(selectedProject.id, selectedProject.revision, action, null); await refreshOverview(result.project.id); setNotice(`Project ${action}d.`); }
    catch { setNotice("Project changed elsewhere or could not be updated."); }
    finally { setBusy(false); }
  }
  async function saveProjectName() {
    if (!selectedProject || !projectRename.trim() || busy) return;
    setBusy(true); setNotice("Renaming Project…");
    try { const result = await updatePlanningProject(selectedProject.id, selectedProject.revision, "rename", projectRename.trim()); setRenameProject(false); await refreshOverview(result.project.id); setNotice("Project renamed."); }
    catch { setNotice("Project changed elsewhere or could not be renamed."); }
    finally { setBusy(false); }
  }
  const taskCard = (task: PublicPlanningTaskListItem) => <li className="planning-task-card" data-planning-task-id={task.id} data-task-selected={task.id === selectedTaskId ? "true" : undefined} data-task-title={task.title} key={task.id} tabIndex={-1}>
    <button aria-pressed={task.id === selectedTaskId} data-planning-task-id={task.id} disabled={busy} onClick={() => selectTask(task)} type="button"><span><strong>{task.title}</strong>{task.description_preview ? <small>{task.description_preview}</small> : <small>No description</small>}<em>{task.workflow_stage.replace("_", " ")} · {task.priority}{task.planned_for_today ? " · today" : ""}</em></span>{task.due_date ? <time dateTime={task.due_date}>Due {task.due_date}</time> : null}</button>
  </li>;
  const stages: PublicPlanningTask["workflow_stage"][] = ["inbox", "planned", "in_progress", "waiting", "review", "done"];
  return <section aria-label="Projects and Tasks" className="projects-tasks-workspace planning-workbench">
    <nav aria-label="Project and saved view navigation" className="projects-pane planning-navigation">
      <div className="projects-tasks-heading"><div><p className="console-kicker">Projects</p><h2>Projects</h2></div><button disabled={busy} onClick={() => { closeTaskForm(); setProjectForm(true); window.setTimeout(() => projectInput.current?.focus(), 0); }} ref={newProjectButton} type="button">New</button></div>
      {projectForm ? <form className="project-create-form" onSubmit={(event) => { event.preventDefault(); void submitProject(); }}><label><span>Name</span><input onChange={(event) => { if ([...event.target.value].length <= 121) setProjectName(event.target.value); }} ref={projectInput} value={projectName} /></label><div><button aria-label="Create Project" disabled={busy || !projectName.trim() || [...projectName.trim()].length > 120} type="submit">Create</button><button aria-label="Cancel Project" disabled={busy} onClick={() => { setProjectForm(false); setProjectName(""); window.setTimeout(() => newProjectButton.current?.focus(), 0); }} type="button">Cancel</button></div></form> : null}
      {state === "loading" ? <p>Loading Projects…</p> : state === "unavailable" || state === "error" ? <p>Projects are temporarily unavailable.</p> : overview?.projects.length ? <ul>{overview.projects.map((project) => <li key={project.id}><button aria-current={project.id === selectedProjectId ? "true" : undefined} aria-label={`Select ${project.name} Project`} data-project-id={project.id} disabled={busy} onClick={() => selectProject(project.id)} type="button"><strong>{project.name}</strong><span>{project.status}</span></button></li>)}</ul> : <p>No Projects yet.</p>}
      <div className="saved-view-navigation"><p className="console-kicker">Saved view</p>{(["all", "today", "waiting", "review", "someday", "completed"] as const).map((item) => <button aria-pressed={savedView === item} disabled={busy} key={item} onClick={() => setSavedView(item)} type="button">{item === "all" ? "All tasks" : item}</button>)}</div>
    </nav>
    <div className="project-tasks-pane planning-task-pane">
      <div className="projects-tasks-heading"><div><p className="console-kicker">Tasks</p><h2>{selectedProject?.name ?? "Tasks"}</h2></div><button disabled={busy || !selectedProjectId || selectedProject?.status !== "active"} onClick={() => { setProjectForm(false); setProjectName(""); setTaskFormProjectId(selectedProjectId); setTaskForm(true); window.setTimeout(() => taskInput.current?.focus(), 0); }} ref={addTaskButton} type="button">Add</button></div>
      {taskForm ? <form className="task-create-form" onSubmit={(event) => { event.preventDefault(); void submitTask(); }}><label><span>Title</span><input onChange={(event) => { if ([...event.target.value].length <= 161) setTaskTitle(event.target.value); }} ref={taskInput} value={taskTitle} /></label><label><span>Agent</span><select aria-describedby="task-agent-state" disabled={agentsState === "loading" || agentsState === "empty" || agentsState === "unavailable"} onChange={(event) => setTaskAgent(event.target.value)} value={taskAgent}><option value="">{agentsState === "loading" ? "Loading" : agentsState === "unavailable" ? "Unavailable" : agentsState === "empty" ? "No Agents" : "Unassigned"}</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label><p className="task-agent-state" id="task-agent-state">{agentsState === "unavailable" ? "Agent assignment is unavailable; Create will leave this Task unassigned." : agentsState === "empty" ? "No Agents are available; Create will leave this Task unassigned." : "Assignment is optional."}</p><label><span>Due</span><input onChange={(event) => setTaskDue(event.target.value)} type="date" value={taskDue} /></label><div><button aria-label="Create Task" disabled={busy || !taskTitle.trim() || [...taskTitle.trim()].length > 160} type="submit">Create</button><button aria-label="Cancel Task" disabled={busy} onClick={() => { closeTaskForm(); window.setTimeout(() => addTaskButton.current?.focus(), 0); }} type="button">Cancel</button></div></form> : null}
      <div className="planning-workbench-tools"><label><span>Filter</span><input onChange={(event) => setFilter(event.target.value)} placeholder="Find a task" type="search" value={filter} /></label><div aria-label="Display mode" className="planning-mode-toggle"><button aria-pressed={view === "list"} onClick={() => setView("list")} type="button">List</button><button aria-pressed={view === "board"} onClick={() => setView("board")} type="button">Board</button></div></div>
      {tasksState === "loading" ? <p>Loading Tasks…</p> : tasksState === "unavailable" || tasksState === "error" ? <p>Tasks are temporarily unavailable.</p> : filteredTasks.length ? view === "list" ? <ul className="project-task-list">{filteredTasks.map(taskCard)}</ul> : <div aria-label="Task board" className="planning-board">{stages.map((stage) => <section key={stage}><h3>{stage.replace("_", " ")}</h3><ul className="project-task-list">{filteredTasks.filter((task) => task.workflow_stage === stage).map(taskCard)}</ul></section>)}</div> : <p>{tasks.length ? "No Tasks match this view." : "No Tasks in this Project."}</p>}
      {taskCursor ? <button className="project-tasks-more" disabled={loadingMore} onClick={() => void loadMoreTasks()} type="button">{loadingMore ? "Loading…" : "More"}</button> : null}
    </div>
    <aside aria-label="Task inspector" className="project-tasks-pane planning-inspector">
      <div className="projects-tasks-heading"><div><p className="console-kicker">Inspector</p><h2>{selectedTask ? "Task details" : "Select a Task"}</h2></div></div>
      {!selectedTask ? <p>Select a Task to review its description, planning details, and lifecycle.</p> : <>
        <p className="planning-description">{(taskDetail?.description ?? selectedTask.description_preview) || "This Task has no description."}</p>
        <dl className="planning-summary"><div><dt>Stage</dt><dd>{selectedTask.workflow_stage.replace("_", " ")}</dd></div><div><dt>Priority</dt><dd>{selectedTask.priority}</dd></div><div><dt>Due</dt><dd>{selectedTask.due_date ?? "Not scheduled"}</dd></div></dl>
        <div className="planning-stage-controls"><p className="console-kicker">Move stage</p>{stages.map((stage) => <button aria-pressed={selectedTask.workflow_stage === stage} disabled={busy || selectedTask.workflow_stage === stage} key={stage} onClick={() => void changeStage(stage)} type="button">{stage.replace("_", " ")}</button>)}</div>
        {editingTask && taskDetail ? <form className="task-create-form planning-edit-form" onSubmit={(event) => { event.preventDefault(); void saveTaskDetails(); }}>
          <label><span>Title</span><input maxLength={160} onChange={(event) => setEditTitle(event.target.value)} value={editTitle} /></label>
          <label className="planning-full-field"><span>Description</span><textarea maxLength={4000} onChange={(event) => setEditDescription(event.target.value)} value={editDescription} /></label>
          <label><span>Priority</span><select onChange={(event) => setEditPriority(event.target.value as PublicPlanningTask["priority"])} value={editPriority}><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
          <label><span>Due</span><input onChange={(event) => setEditDue(event.target.value)} type="date" value={editDue} /></label>
          <label><span>Estimate (minutes)</span><input max="10080" min="1" onChange={(event) => setEditEstimate(event.target.value)} type="number" value={editEstimate} /></label>
          <label><span>Recurrence</span><select onChange={(event) => setEditRecurrence(event.target.value as typeof editRecurrence)} value={editRecurrence}><option value="">None</option><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="yearly">Yearly</option></select></label>
          <label className="planning-full-field"><span>Tags (comma separated)</span><input onChange={(event) => setEditTags(event.target.value)} value={editTags} /></label>
          <label className="planning-full-field"><span>Assigned Agent</span><select disabled={agentsState !== "ready"} onChange={(event) => setEditAgent(event.target.value)} value={editAgent}><option value="">Unassigned</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
          <fieldset className="planning-dependencies"><legend>Dependencies</legend>
            <section><h3>Prerequisites ({taskDependencies?.prerequisite_count ?? 0})</h3>{dependenciesState === "unavailable" ? <p>Dependencies are temporarily unavailable.</p> : editDependencies.length ? <ul>{editDependencies.map((dependency) => <li key={dependency.id}><span>{dependencyText(dependency)}</span><button aria-label={`Remove prerequisite ${dependency.title}`} disabled={busy || dependenciesState !== "ready"} onClick={() => setEditDependencies((current) => current.filter((item) => item.id !== dependency.id))} type="button">Remove</button></li>)}</ul> : <p>No prerequisites.</p>}{taskDependencies?.prerequisites_truncated ? <p>Some prerequisites are not shown.</p> : null}</section>
            <label><span>Find a prerequisite</span><input disabled={busy || dependenciesState !== "ready"} maxLength={160} onChange={(event) => setDependencyQuery(event.target.value.trim())} placeholder="Search Tasks" type="search" value={dependencyQuery} /></label>
            {editDependencies.length >= 100 ? <p>Maximum of 100 prerequisites reached. Remove one before adding another.</p> : null}
            {dependencyPickerState === "loading" ? <p>Finding Tasks…</p> : dependencyPickerState === "unavailable" ? <p>Task choices are temporarily unavailable.</p> : dependencyCandidates.length ? <ul aria-label="Prerequisite choices" className="planning-dependency-picker">{dependencyCandidates.map((candidate) => <li key={candidate.id}><span>{dependencyText(candidate)}</span><button aria-label={`Add prerequisite ${candidate.title}`} disabled={busy || editDependencies.length >= 100 || editDependencies.some((item) => item.id === candidate.id)} onClick={() => setEditDependencies((current) => current.length >= 100 || current.some((item) => item.id === candidate.id) ? current : [...current, candidate])} type="button">Add</button></li>)}</ul> : <p>No matching Tasks.</p>}
            {dependencyCursor ? <button disabled={busy || dependencyPickerState === "loading"} onClick={() => void loadMoreDependencyCandidates()} type="button">More Task choices</button> : null}
            <section><h3>Dependents ({taskDependencies?.dependent_count ?? 0})</h3>{taskDependencies?.dependents.length ? <ul>{taskDependencies.dependents.map((dependency) => <li key={dependency.id}>{dependencyText(dependency)}</li>)}</ul> : <p>No Tasks depend on this Task.</p>}{taskDependencies?.dependents_truncated ? <p>Some dependents are not shown.</p> : null}</section>
          </fieldset>
          <div className="planning-checklist"><span>Checklist</span>{editSubtasks.map((item, index) => <label key={item.id}><input checked={item.completed} onChange={(event) => setEditSubtasks((current) => current.map((entry, position) => position === index ? { ...entry, completed: event.target.checked } : entry))} type="checkbox" />{item.title}<button onClick={() => setEditSubtasks((current) => current.filter((_, position) => position !== index))} type="button">Remove</button></label>)}<button onClick={() => setEditSubtasks((current) => [...current, { id: `check_${crypto.randomUUID().replaceAll("-", "")}`, title: "New checklist item", completed: false, rank: current.length }])} type="button">Add checklist item</button></div>
          <label className="planning-checkbox"><input checked={editToday} onChange={(event) => setEditToday(event.target.checked)} type="checkbox" />Today</label><div><button disabled={busy || !editTitle.trim()} type="submit">Save details</button><button disabled={busy} onClick={() => setEditingTask(false)} type="button">Cancel</button></div>
        </form> : <button disabled={busy || !taskDetail || dependenciesState === "loading"} onClick={() => { if (!taskDetail) return; setEditTitle(taskDetail.title); setEditDescription(taskDetail.description); setEditPriority(taskDetail.priority); setEditDue(taskDetail.due_date ?? ""); setEditToday(taskDetail.planned_for_today); setEditTags(taskDetail.tags.join(", ")); setEditEstimate(taskDetail.estimated_minutes?.toString() ?? ""); setEditRecurrence(taskDetail.recurrence?.frequency ?? ""); setEditSubtasks(taskDetail.subtasks); setEditAgent(taskDetail.assigned_agent_id ?? ""); setEditDependencies(taskDependencies?.prerequisites ?? []); setDependencyQuery(""); setDependencyCandidates([]); setDependencyCursor(null); setEditingTask(true); }} type="button">{taskDetail && dependenciesState !== "loading" ? "Edit details" : "Loading details…"}</button>}
      </>}
      {selectedProject ? <section className="planning-project-lifecycle"><p className="console-kicker">Project lifecycle</p>{renameProject ? <form className="project-create-form" onSubmit={(event) => { event.preventDefault(); void saveProjectName(); }}><label><span>Name</span><input maxLength={120} onChange={(event) => setProjectRename(event.target.value)} value={projectRename} /></label><div><button disabled={busy || !projectRename.trim()} type="submit">Save name</button><button disabled={busy} onClick={() => setRenameProject(false)} type="button">Cancel</button></div></form> : <button disabled={busy} onClick={() => { setProjectRename(selectedProject.name); setRenameProject(true); }} type="button">Rename Project</button>}{selectedProject.status === "archived" ? <button disabled={busy} onClick={() => void lifecycle("restore")} type="button">Restore Project</button> : <button disabled={busy} onClick={() => void lifecycle("archive")} type="button">Archive Project</button>}</section> : null}
    </aside>
    <p aria-live="polite" className="projects-tasks-notice" role="status">{notice}</p>
  </section>;
}
