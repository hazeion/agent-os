"use client";

import dynamic from "next/dynamic.js";
import { useEffect, useMemo, useRef, useState } from "react";

import type { TaskDependencyMapProps } from "./task-dependency-map";

const TaskDependencyMap = dynamic<TaskDependencyMapProps>(
  () => import("./task-dependency-map"),
  { loading: () => <p aria-live="polite" role="status">Loading the dependency map…</p>, ssr: false },
);

import type { PublicAgent } from "@/lib/bridge-agents";
import {
  createProject,
  createProjectTask,
  readPlanningDependencyMap,
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
  type PublicPlanningDependencyMap,
  type PublicPlanningTaskDependencies,
  type PublicPlanningTaskExecution,
  type PublicPlanningTaskExecutionMutation,
  PublicPlanningError,
} from "@/lib/public-planning";
import {
  confirmPlanningTaskRunOnce,
  previewPlanningTaskRunOnce,
  readPlanningTaskExecution,
  reviewPlanningTaskExecution,
} from "@/lib/public-planning-task-execution";
import { readPlanningTaskDelegation, type PublicPlanningTaskDelegation } from "@/lib/public-planning-task-delegation";
import {
  confirmPlanningTaskDelegation,
  confirmPlanningTaskDelegationAction,
  previewPlanningTaskDelegation,
  previewPlanningTaskDelegationAction,
  readPlanningTaskDelegationOptions,
  recoverPlanningTaskDelegation,
  refreshPlanningTaskDelegation,
  type DelegationAction,
  type PublicPlanningTaskDelegationOptions,
  type PublicPlanningTaskDelegationPreview,
} from "@/lib/public-planning-task-delegation-actions";
import {
  confirmPlanningDeletion,
  previewPlanningDeletion,
  type PlanningDeletionTargetKind,
  type PublicPlanningDeletionPreview,
} from "@/lib/public-planning-deletion";
import {
  readPlanningSearch,
  type PublicPlanningSearch,
  type PublicPlanningSearchResult,
} from "@/lib/public-planning-search";

type LoadState = "loading" | "ready" | "empty" | "unavailable" | "error";
type ProjectVisibility = "active" | "all" | "archived";

function projectsForVisibility(projects: PublicPlanningOverview["projects"], visibility: ProjectVisibility) {
  if (visibility === "all") return projects;
  return projects.filter((project) => visibility === "archived" ? project.status === "archived" : project.status !== "archived");
}

type DelegationRecovery = { confirmationId: string; idempotencyKey: string };

function delegationRecoveryKey(taskId: string) { return `mentat.delegation-recovery.v1.${taskId}`; }
function loadDelegationRecovery(taskId: string): DelegationRecovery | null {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(delegationRecoveryKey(taskId)) ?? "null");
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const record = value as Record<string, unknown>;
    if (typeof record.confirmationId !== "string" || !/^(?:task_delegate|delegation_action)_[0-9a-f]{24}$/u.test(record.confirmationId) || typeof record.idempotencyKey !== "string" || new TextEncoder().encode(record.idempotencyKey).byteLength < 16 || new TextEncoder().encode(record.idempotencyKey).byteLength > 256) return null;
    return { confirmationId: record.confirmationId, idempotencyKey: record.idempotencyKey };
  } catch { return null; }
}
function storeDelegationRecovery(taskId: string, value: DelegationRecovery | null) {
  try {
    if (value) window.localStorage.setItem(delegationRecoveryKey(taskId), JSON.stringify(value));
    else window.localStorage.removeItem(delegationRecoveryKey(taskId));
  } catch { /* Browser persistence is only a recovery convenience. */ }
}

function requestedTask(): { projectId: string | null; taskId: string | null } | null | false {
  const entries = [...new URL(window.location.href).searchParams.entries()];
  if (!entries.length) return null;
  if (entries.length === 1 && entries[0][0] === "task" && /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u.test(entries[0][1])) return { projectId: null, taskId: entries[0][1] };
  if (entries.length === 1 && entries[0][0] === "project" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u.test(entries[0][1])) return { projectId: entries[0][1], taskId: null };
  if (entries.length !== 2 || new Set(entries.map(([key]) => key)).size !== 2) return false;
  const projectId = entries.find(([key]) => key === "project")?.[1];
  const taskId = entries.find(([key]) => key === "task")?.[1];
  if (!projectId || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u.test(projectId) || !taskId || !/^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u.test(taskId)) return false;
  return { projectId, taskId };
}

function planningTimestamp(value: string, timezone?: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: timezone ?? "UTC",
      timeZoneName: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function noteLinkLabel(path: string, title: string | undefined, index: number): string {
  if (title) return title;
  const filename = path.split("/").at(-1)?.replace(/\.md$/iu, "");
  return filename || `Note ${index + 1}`;
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
  const [taskPageRefreshVersion, setTaskPageRefreshVersion] = useState(0);
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
  const [taskExecution, setTaskExecution] = useState<PublicPlanningTaskExecution | null>(null);
  const [executionState, setExecutionState] = useState<LoadState>("loading");
  const [taskDelegation, setTaskDelegation] = useState<PublicPlanningTaskDelegation | null>(null);
  const [delegationState, setDelegationState] = useState<LoadState>("loading");
  const [delegationOptions, setDelegationOptions] = useState<PublicPlanningTaskDelegationOptions | null>(null);
  const [delegationForm, setDelegationForm] = useState(false);
  const [delegationProfile, setDelegationProfile] = useState("");
  const [delegationBoard, setDelegationBoard] = useState("");
  const [delegationWorkspace, setDelegationWorkspace] = useState<"scratch" | "worktree">("scratch");
  const [delegationInstructions, setDelegationInstructions] = useState("");
  const [delegationPreview, setDelegationPreview] = useState<PublicPlanningTaskDelegationPreview | null>(null);
  const [delegationAction, setDelegationAction] = useState<Exclude<DelegationAction, "delegate"> | null>(null);
  const [delegationActionNote, setDelegationActionNote] = useState("");
  const [delegationActionPreview, setDelegationActionPreview] = useState<PublicPlanningTaskDelegationPreview | null>(null);
  const [delegationRecovery, setDelegationRecovery] = useState<DelegationRecovery | null>(null);
  const [runOnceConfirmation, setRunOnceConfirmation] = useState<{ confirmationId: string; idempotencyKey: string; revision: number; taskId: string } | null>(null);
  const [requestChanges, setRequestChanges] = useState(false);
  const [reviewNote, setReviewNote] = useState("");
  const [dependencyMap, setDependencyMap] = useState<PublicPlanningDependencyMap | null>(null);
  const [dependencyMapState, setDependencyMapState] = useState<LoadState>("empty");
  const [dependencyMapVersion, setDependencyMapVersion] = useState(0);
  const [view, setView] = useState<"list" | "board" | "map">("list");
  const [savedView, setSavedView] = useState<"all" | "today" | "waiting" | "review" | "someday" | "completed">("all");
  const [projectVisibility, setProjectVisibility] = useState<ProjectVisibility>("active");
  const [filter, setFilter] = useState("");
  const [planningSearchQuery, setPlanningSearchQuery] = useState("");
  const [planningSearch, setPlanningSearch] = useState<PublicPlanningSearch | null>(null);
  const [planningSearchState, setPlanningSearchState] = useState<"idle" | "loading" | "ready" | "empty" | "unavailable">("idle");
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
  const [deletionPreview, setDeletionPreview] = useState<PublicPlanningDeletionPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const projectInput = useRef<HTMLInputElement>(null);
  const taskInput = useRef<HTMLInputElement>(null);
  const newProjectButton = useRef<HTMLButtonElement>(null);
  const addTaskButton = useRef<HTMLButtonElement>(null);
  const projectSelectionGeneration = useRef(0);
  const projectVisibilityRef = useRef<ProjectVisibility>("active");
  const requestedTaskFocus = useRef<string | null>(null);
  const selectedProjectRef = useRef<string | null>(null);
  // Selection can change while an execution refresh is in flight. Keep the
  // current selection and an epoch outside a render closure so late responses
  // cannot repaint a different Task (or an older read of the same Task).
  const selectedTaskRef = useRef<string | null>(null);
  const taskSelectionGeneration = useRef(0);
  const executionGeneration = useRef(0);
  const delegationGeneration = useRef(0);
  // An ambiguous delegation delivery is an external mutation boundary. Keep the
  // exact receipt outside render state too, so a rapid second click cannot mint
  // a new key before React has repainted the recovery-only presentation.
  const delegationRecoveryRef = useRef<DelegationRecovery | null>(null);
  const taskDetailGeneration = useRef(0);
  const dependencyPickerGeneration = useRef(0);
  const planningSearchGeneration = useRef(0);
  const pendingSearchTaskOpen = useRef<{ projectId: string; taskId: string } | null>(null);
  const requested = useMemo(() => typeof window === "undefined" ? null : requestedTask(), []);

  function selectTaskId(taskId: string | null) {
    if (selectedTaskRef.current !== taskId) {
      selectedTaskRef.current = taskId;
      taskSelectionGeneration.current += 1;
      executionGeneration.current += 1;
      delegationGeneration.current += 1;
      taskDetailGeneration.current += 1;
      // Clear execution presentation in this same selection update. Waiting for
      // the effect below would briefly render the prior Task's controls when
      // two Tasks have the same revision.
      setTaskExecution(null);
      setExecutionState(taskId ? "loading" : "empty");
      setTaskDelegation(null);
      setDelegationState(taskId ? "loading" : "empty");
      setDelegationOptions(null);
      setDelegationForm(false);
      setDelegationPreview(null);
      setDelegationAction(null);
      setDelegationActionPreview(null);
      setDelegationActionNote("");
      const recovery = taskId ? loadDelegationRecovery(taskId) : null;
      delegationRecoveryRef.current = recovery;
      setDelegationRecovery(recovery);
      setRunOnceConfirmation(null);
      setDeletionPreview((current) => current?.target_kind === "task" ? null : current);
      setRequestChanges(false);
      setReviewNote("");
    }
    setSelectedTaskId(taskId);
  }

  async function refreshOverview(preferredProjectId: string | null = null, visibility: ProjectVisibility = projectVisibility) {
    const value = await readPlanningOverview();
    setOverview(value);
    setState(value.projects.length ? "ready" : "empty");
    const requestedProject = requested && typeof requested === "object"
      ? requested.projectId !== null
        ? value.projects.some((item) => item.id === requested.projectId) ? requested.projectId : null
        : null
      : null;
    const visibleProjects = projectsForVisibility(value.projects, visibility);
    setSelectedProjectId((current) => {
      const next = preferredProjectId && visibleProjects.some((item) => item.id === preferredProjectId)
        ? preferredProjectId
        : requestedProject && visibleProjects.some((item) => item.id === requestedProject)
          ? requestedProject
          : current && visibleProjects.some((item) => item.id === current)
            ? current
            : visibleProjects[0]?.id ?? null;
      selectedProjectRef.current = next;
      return next;
    });
    return value;
  }

  function closeTaskForm() {
    setTaskForm(false); setTaskFormProjectId(null); setTaskTitle(""); setTaskAgent(""); setTaskDue("");
  }

  function selectProject(projectId: string) {
    projectSelectionGeneration.current += 1;
    requestedTaskFocus.current = null;
    selectedProjectRef.current = projectId;
    setSelectedProjectId(projectId);
    selectTaskId(null);
    setTaskDetail(null);
    setTaskDependencies(null);
    setDependenciesState("loading");
    setEditingTask(false);
    setDeletionPreview(null);
    closeTaskForm();
  }

  function changeProjectVisibility(visibility: ProjectVisibility) {
    projectVisibilityRef.current = visibility;
    setProjectVisibility(visibility);
  }

  function selectProjectVisibility(visibility: ProjectVisibility) {
    if (visibility === projectVisibility) return;
    changeProjectVisibility(visibility);
    const visibleProjects = projectsForVisibility(overview?.projects ?? [], visibility);
    const next = visibleProjects.some((project) => project.id === selectedProjectId)
      ? selectedProjectId
      : visibleProjects[0]?.id ?? null;
    if (next) selectProject(next);
    else {
      selectedProjectRef.current = null;
      setSelectedProjectId(null);
      selectTaskId(null);
      setTaskDetail(null);
      setTaskDependencies(null);
      setEditingTask(false);
      setDeletionPreview(null);
      closeTaskForm();
    }
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
        const requestedProjectStatus = requestedProject ? planning.projects.find((item) => item.id === requestedProject)?.status : null;
        const currentVisibility = projectVisibilityRef.current;
        const effectiveVisibility = requestedProjectStatus === "archived" && currentVisibility === "active" ? "archived" : currentVisibility;
        if (effectiveVisibility !== currentVisibility) changeProjectVisibility(effectiveVisibility);
        const visibleProjects = projectsForVisibility(planning.projects, effectiveVisibility);
        setSelectedProjectId((current) => {
          const selected = requested && typeof requested === "object" && requested.projectId === null
            ? current && visibleProjects.some((item) => item.id === current) ? current : visibleProjects[0]?.id ?? null
            : requestedProject && visibleProjects.some((item) => item.id === requestedProject) ? requestedProject : visibleProjects[0]?.id ?? null;
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
    if (!requested || requested.projectId !== null || !requested.taskId) return;
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
      selectTaskId(rows.some((task) => task.id === selectedTaskRef.current) ? selectedTaskRef.current : null);
      setTaskCursor(cursor);
      setTasksState(rows.length ? "ready" : "empty");
      const requestedTaskId = requested && typeof requested === "object" && requested.taskId !== null && (requested.projectId === null || requested.projectId === projectId)
        ? requested.taskId
        : null;
      const pendingTaskId = pendingSearchTaskOpen.current?.projectId === projectId ? pendingSearchTaskOpen.current.taskId : null;
      const targetTaskId = pendingTaskId ?? requestedTaskId;
      if (targetTaskId) {
        let target = rows.find((task) => task.id === targetTaskId) ?? null;
        try {
          for (let pageIndex = 1; !target && cursor && pageIndex < 42; pageIndex += 1) {
            const next = await readPlanningTasks(projectId, cursor);
            if (cancelled) return;
            rows = [...rows, ...next.tasks.filter((task) => !rows.some((item) => item.id === task.id))];
            cursor = next.next_cursor;
            target = rows.find((task) => task.id === targetTaskId) ?? null;
            setTasks(rows);
            setTaskCursor(cursor);
          }
        } catch {
          if (!cancelled) setNotice("More Tasks could not be loaded; the verified Tasks shown remain available.");
          return;
        }
        if (target) {
          if (pendingSearchTaskOpen.current?.projectId === projectId && pendingSearchTaskOpen.current.taskId === targetTaskId) pendingSearchTaskOpen.current = null;
          requestedTaskFocus.current = targetTaskId;
          selectTaskId(targetTaskId); setTaskDetail(null); setEditingTask(false);
          setTasks([...rows]);
        }
        else setNotice("The requested Task could not be found in this Project.");
      }
      else if (requested === false) setNotice("The requested Task link is invalid.");
    }).catch(() => { if (!cancelled) setTasksState("unavailable"); });
    return () => { cancelled = true; };
  }, [requested, selectedProjectId, taskPageRefreshVersion]);

  useEffect(() => {
    if (!selectedTaskId) return;
    const taskId = selectedTaskId;
    const generation = ++taskDetailGeneration.current;
    let cancelled = false;
    void readPlanningTaskDetail(taskId).then((result) => { if (!cancelled && generation === taskDetailGeneration.current && selectedTaskRef.current === taskId && result.task.id === taskId) setTaskDetail(result.task); }).catch(() => { if (!cancelled && generation === taskDetailGeneration.current && selectedTaskRef.current === taskId) setNotice("Task details could not be loaded. The Task list remains available."); });
    return () => { cancelled = true; };
  }, [selectedTaskId]);

  useEffect(() => {
    if (!selectedTaskId) return;
    const taskId = selectedTaskId;
    const generation = ++delegationGeneration.current;
    let cancelled = false;
    void readPlanningTaskDelegation(taskId).then((result) => {
      if (cancelled || generation !== delegationGeneration.current || selectedTaskRef.current !== taskId || result.task.id !== taskId) return;
      setTaskDelegation(result); setDelegationState("ready");
    }).catch(() => { if (!cancelled && generation === delegationGeneration.current && selectedTaskRef.current === taskId) setDelegationState("unavailable"); });
    return () => { cancelled = true; };
  }, [selectedTaskId]);

  useEffect(() => {
    if (!selectedTaskId) return;
    const taskId = selectedTaskId;
    const generation = ++executionGeneration.current;
    let cancelled = false;
    void readPlanningTaskExecution(taskId).then((result) => {
      if (cancelled || generation !== executionGeneration.current || selectedTaskRef.current !== taskId || result.task.id !== taskId) return;
      setTaskExecution(result); setExecutionState("ready");
    }).catch(() => { if (!cancelled && generation === executionGeneration.current && selectedTaskRef.current === taskId) setExecutionState("unavailable"); });
    return () => { cancelled = true; };
  }, [selectedTaskId]);

  useEffect(() => {
    if (!selectedProjectId || view !== "map") return;
    const projectId = selectedProjectId;
    const query = filter.trim();
    let cancelled = false;
    void Promise.resolve().then(() => { if (!cancelled) { setDependencyMap(null); setDependencyMapState("loading"); } });
    void readPlanningDependencyMap(projectId, query, savedView).then((result) => {
      if (cancelled || result.project.id !== projectId || selectedProjectRef.current !== projectId) return;
      setDependencyMap(result); setDependencyMapState("ready");
    }).catch(() => { if (!cancelled) setDependencyMapState("unavailable"); });
    return () => { cancelled = true; };
  }, [dependencyMapVersion, filter, savedView, selectedProjectId, view]);

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

  useEffect(() => {
    const query = planningSearchQuery;
    const generation = ++planningSearchGeneration.current;
    if (!query || query.trim() !== query || /\p{C}/u.test(query)) {
      void Promise.resolve().then(() => {
        if (generation !== planningSearchGeneration.current) return;
        setPlanningSearch(null); setPlanningSearchState("idle");
      });
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      if (!cancelled && generation === planningSearchGeneration.current) setPlanningSearchState("loading");
      void readPlanningSearch(query, controller.signal).then((result) => {
      if (cancelled || generation !== planningSearchGeneration.current || result.query !== query) return;
      setPlanningSearch(result);
      setPlanningSearchState(result.projects.length || result.tasks.length ? "ready" : "empty");
      }).catch(() => {
      if (!cancelled && generation === planningSearchGeneration.current) setPlanningSearchState("unavailable");
      });
    }, 180);
    return () => { cancelled = true; window.clearTimeout(timer); controller.abort(); };
  }, [planningSearchQuery]);

  function updatePlanningLocation(projectId: string, taskId: string | null) {
    const location = new URL(window.location.href);
    location.pathname = "/tasks";
    location.search = new URLSearchParams(taskId ? { project: projectId, task: taskId } : { project: projectId }).toString();
    location.hash = "";
    window.history.pushState(null, "", `${location.pathname}${location.search}`);
  }

  async function openPlanningSearchResult(result: PublicPlanningSearchResult) {
    if (busy) return;
    setBusy(true);
    try {
      if (result.type === "project") {
        const current = await readPlanningOverview();
        if (!current.projects.some((project) => project.id === result.id)) { setNotice("That search result is no longer available. Nothing changed."); return; }
        setOverview(current); setState(current.projects.length ? "ready" : "empty");
        changeProjectVisibility("all");
        selectProject(result.id);
        updatePlanningLocation(result.id, null);
        setNotice(`Opened Project ${result.title}.`);
        return;
      }
      const current = await readPlanningOverview();
      const located = await readPlanningTask(result.id);
      if (located.task.id !== result.id || !current.projects.some((project) => project.id === located.project.id)) { setNotice("That search result is no longer available. Nothing changed."); return; }
      setOverview(current); setState(current.projects.length ? "ready" : "empty");
      pendingSearchTaskOpen.current = { projectId: located.project.id, taskId: result.id };
      changeProjectVisibility("all");
      selectProject(located.project.id);
      setTaskPageRefreshVersion((current) => current + 1);
      updatePlanningLocation(located.project.id, result.id);
      setNotice(`Opening Task ${result.title}.`);
    } catch { setNotice("That search result is no longer available. Nothing changed."); }
    finally { setBusy(false); }
  }

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

  function applyDelegationResult(result: PublicPlanningTaskDelegation) {
    if (selectedTaskRef.current !== result.task.id) return;
    setTaskDelegation(result);
    setDelegationState("ready");
    setTasks((current) => current.map((task) => task.id === result.task.id ? { ...task, revision: result.task.revision } : task));
  }

  async function openDelegationForm() {
    if (!selectedTask || busy) return;
    setBusy(true); setNotice("Checking delegation options…");
    try {
      const options = await readPlanningTaskDelegationOptions(selectedTask.id);
      if (selectedTaskRef.current !== selectedTask.id || options.task.revision !== selectedTask.revision) return;
      setDelegationOptions(options);
      if (options.options.available) {
        setDelegationProfile(options.options.profiles[0]?.id ?? "");
        setDelegationBoard(options.options.boards[0]?.id ?? "");
        setDelegationWorkspace(options.options.workspaces[0]);
        setDelegationForm(true);
        setNotice("Choose the Hermes target, then preview the delegation.");
      } else setNotice("Delegation is unavailable for this Task right now.");
    } catch { setNotice("Delegation options are temporarily unavailable."); }
    finally { setBusy(false); }
  }

  async function previewDelegation() {
    if (!selectedTask || !delegationProfile || !delegationBoard || busy) return;
    setBusy(true); setNotice("Preparing delegation preview…");
    try {
      const preview = await previewPlanningTaskDelegation(selectedTask.id, selectedTask.revision, delegationProfile, delegationBoard, delegationWorkspace, delegationInstructions, "");
      if (selectedTaskRef.current !== selectedTask.id || preview.task.revision !== selectedTask.revision) return;
      setDelegationPreview(preview); setNotice("Review the exact delegation before confirming.");
    } catch { setNotice("Delegation preview could not be prepared. Your choices were kept."); }
    finally { setBusy(false); }
  }

  async function confirmDelegation() {
    if (!selectedTask || !delegationPreview || delegationPreview.action !== "delegate" || busy || delegationRecoveryRef.current) return;
    const key = `delegation-${crypto.randomUUID()}`;
    const recovery = { confirmationId: delegationPreview.confirmation_id, idempotencyKey: key };
    delegationRecoveryRef.current = recovery;
    setDelegationRecovery(recovery); storeDelegationRecovery(selectedTask.id, recovery);
    setBusy(true); setNotice("Creating the delegated Task…");
    try {
      const result = await confirmPlanningTaskDelegation(selectedTask.id, delegationPreview.task.revision, delegationProfile, delegationBoard, delegationWorkspace, delegationInstructions, "", delegationPreview.confirmation_id, key);
      applyDelegationResult(result); setDelegationForm(false); setDelegationPreview(null); delegationRecoveryRef.current = null; setDelegationRecovery(null); storeDelegationRecovery(selectedTask.id, null); setNotice(result.duplicate ? "The existing delegation was confirmed." : "Task delegated.");
    } catch (error) {
      setNotice("Delegation delivery is uncertain. Reconcile it before trying anything else.");
      setDelegationPreview({ ...delegationPreview, confirmation_id: delegationPreview.confirmation_id, action: "delegate" });
      void error;
    } finally { setBusy(false); }
  }

  async function previewDelegationAction(action: Exclude<DelegationAction, "delegate">, note: string | null) {
    if (!selectedTask || busy) return;
    setBusy(true); setNotice("Preparing delegation action…");
    try {
      const preview = await previewPlanningTaskDelegationAction(selectedTask.id, selectedTask.revision, action, note);
      if (selectedTaskRef.current !== selectedTask.id || preview.task.revision !== selectedTask.revision) return;
      setDelegationActionPreview(preview); setDelegationAction(action); setNotice("Review the exact action before confirming.");
    } catch { setNotice("That delegation action is not available for the current Task state."); }
    finally { setBusy(false); }
  }

  async function confirmDelegationAction() {
    if (!selectedTask || !delegationAction || !delegationActionPreview || busy || delegationRecoveryRef.current) return;
    const key = `delegation-${crypto.randomUUID()}`;
    const note = ["reply", "request_revision", "mark_blocked"].includes(delegationAction) ? delegationActionNote : null;
    setBusy(true); setNotice("Applying delegation action…");
    const recovery = { confirmationId: delegationActionPreview.confirmation_id, idempotencyKey: key };
    delegationRecoveryRef.current = recovery;
    setDelegationRecovery(recovery); storeDelegationRecovery(selectedTask.id, recovery);
    try {
      const result = await confirmPlanningTaskDelegationAction(selectedTask.id, delegationActionPreview.task.revision, delegationAction, note, delegationActionPreview.confirmation_id, key);
      applyDelegationResult(result); setDelegationAction(null); setDelegationActionPreview(null); setDelegationActionNote(""); delegationRecoveryRef.current = null; setDelegationRecovery(null); storeDelegationRecovery(selectedTask.id, null); setNotice(result.duplicate ? "The existing action was confirmed." : "Delegation updated.");
    } catch { setNotice("Action delivery is uncertain. Reconcile it before trying anything else."); }
    finally { setBusy(false); }
  }

  async function refreshDelegation() {
    if (!selectedTask || busy) return;
    setBusy(true); setNotice("Refreshing delegated work…");
    try { applyDelegationResult(await refreshPlanningTaskDelegation(selectedTask.id, selectedTask.revision)); setNotice("Delegated work refreshed."); }
    catch { setNotice("Delegated work could not be refreshed."); }
    finally { setBusy(false); }
  }

  async function recoverDelegation() {
    if (!selectedTask || !delegationRecovery || busy) return;
    setBusy(true); setNotice("Reconciling the prior delivery without retrying it…");
    try {
      const result = await recoverPlanningTaskDelegation(selectedTask.id, delegationRecovery.confirmationId, delegationRecovery.idempotencyKey);
      applyDelegationResult(result); setDelegationPreview(null); setDelegationActionPreview(null); delegationRecoveryRef.current = null; setDelegationRecovery(null); storeDelegationRecovery(selectedTask.id, null); setNotice(result.recovered ? "Prior delivery reconciled." : "Prior delivery was already confirmed.");
    } catch { setNotice("The prior delivery is still indeterminate; no action was retried."); }
    finally { setBusy(false); }
  }

  async function submitProject() {
    const name = projectName.trim();
    if (!name || busy) return;
    setBusy(true); setNotice("Creating Project…");
    try {
      const created = await createProject(name);
      setProjectName(""); setProjectForm(false);
      changeProjectVisibility("active");
      await refreshOverview(created.id, "active");
      setNotice(`Project ${created.name} created.`);
      window.setTimeout(() => document.querySelector<HTMLElement>(`[data-project-id="${CSS.escape(created.id)}"]`)?.focus(), 0);
    } catch { setNotice("Project could not be created. Your name was kept."); projectInput.current?.focus(); }
    finally { setBusy(false); }
  }

  function invalidateDependencyMap() {
    setDependencyMap(null);
    setDependencyMapState("empty");
    setDependencyMapVersion((current) => current + 1);
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
        selectTaskId(created.id); setTaskDetail(null);
        setTasksState("ready");
        window.setTimeout(() => document.querySelector<HTMLElement>(`[data-planning-task-id="${CSS.escape(created.id)}"]`)?.focus(), 0);
      }
      invalidateDependencyMap();
      setNotice(`Task ${created.title} created.`);
    } catch { setNotice("Task could not be created. Your details were kept."); taskInput.current?.focus(); }
    finally { setBusy(false); }
  }

  function deletionSummary(counts: { artifacts: number; conversations: number; projects: number; runs: number; tasks: number }) {
    const parts = [
      `${counts.projects} Project${counts.projects === 1 ? "" : "s"}`,
      `${counts.tasks} Task${counts.tasks === 1 ? "" : "s"}`,
      `${counts.conversations} Conversation${counts.conversations === 1 ? "" : "s"}`,
      `${counts.runs} Run${counts.runs === 1 ? "" : "s"}`,
      `${counts.artifacts} artifact${counts.artifacts === 1 ? "" : "s"}`,
    ];
    return parts.join(", ");
  }

  function deletionTargetIsSelected(kind: PlanningDeletionTargetKind, targetId: string) {
    return kind === "task" ? selectedTaskRef.current === targetId : selectedProjectRef.current === targetId;
  }

  async function reviewDeletion(kind: PlanningDeletionTargetKind) {
    const target = kind === "task" ? selectedTask : selectedProject;
    if (!target || busy) return;
    const targetId = target.id;
    setBusy(true); setNotice("Preparing the exact deletion preview…"); setDeletionPreview(null);
    try {
      const preview = await previewPlanningDeletion(kind, targetId);
      if (!deletionTargetIsSelected(kind, targetId)) return;
      setDeletionPreview(preview);
      setNotice("Review the affected work before confirming deletion.");
    } catch {
      if (deletionTargetIsSelected(kind, targetId)) setNotice("Deletion could not be safely reviewed. Nothing was removed.");
    } finally { setBusy(false); }
  }

  async function confirmDeletion() {
    if (!deletionPreview || busy || !deletionTargetIsSelected(deletionPreview.target_kind, deletionPreview.target_id)) return;
    const preview = deletionPreview;
    setBusy(true); setNotice("Stopping affected work and verifying deletion…");
    try {
      const result = await confirmPlanningDeletion(preview.target_kind, preview.target_id, preview.confirmation_id);
      if (!deletionTargetIsSelected(preview.target_kind, preview.target_id)) return;
      selectTaskId(null); setTaskDetail(null); setTaskDependencies(null); setEditingTask(false); setDeletionPreview(null); setRenameProject(false);
      await refreshOverview();
      invalidateDependencyMap();
      setNotice(`Deleted ${deletionSummary(result.deletion)}.`);
    } catch {
      if (deletionTargetIsSelected(preview.target_kind, preview.target_id)) setNotice("Deletion was not verified. Nothing was removed; refresh and review it again.");
    } finally { setBusy(false); }
  }

  const selectedProject = overview?.projects.find((item) => item.id === selectedProjectId) ?? null;
  const visibleProjects = projectsForVisibility(overview?.projects ?? [], projectVisibility);
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? null;
  const selectedTaskExecution = taskExecution && selectedTask && taskExecution.task.id === selectedTask.id && taskExecution.task.revision === selectedTask.revision ? taskExecution : null;
  const selectedTaskDelegation = taskDelegation && selectedTask && taskDelegation.task.id === selectedTask.id ? taskDelegation : null;
  const executionOwnsTerminalStages = !!selectedTaskExecution && executionState === "ready" && selectedTaskExecution.execution.attempts.some((attempt) => attempt.state === "dispatched" || attempt.state === "review_ready");
  const hasPlanningMetadata = !!taskDetail && (!!taskDetail.scheduled_block || !!taskDetail.reminders.length || !!taskDetail.calendar_links.length || !!taskDetail.note_links.length);
  const filteredTasks = tasks.filter((task) => {
    const query = filter.trim().toLowerCase();
    if (query && !`${task.title} ${task.description_preview}`.toLowerCase().includes(query)) return false;
    if (savedView === "all") return true;
    if (savedView === "today") return task.planned_for_today;
    if (savedView === "waiting") return task.workflow_stage === "waiting";
    if (savedView === "review") return task.workflow_stage === "review";
    if (savedView === "someday") return task.deferred;
    return task.workflow_stage === "done";
  });
  const dependencyMapGraph = useMemo<TaskDependencyMapProps["graph"] | null>(() => {
    if (!dependencyMap) return null;
    return {
      edge_count: dependencyMap.edge_count,
      edge_total: dependencyMap.edge_total,
      edges: dependencyMap.edges,
      edges_truncated: dependencyMap.edges_truncated,
      external_stub_count: dependencyMap.external_stub_count,
      external_stub_total: dependencyMap.external_stub_total,
      external_stubs: dependencyMap.external_stubs,
      external_stubs_truncated: dependencyMap.external_stubs_truncated,
      node_count: dependencyMap.node_count,
      node_total: dependencyMap.node_total,
      nodes: dependencyMap.nodes,
      nodes_truncated: dependencyMap.nodes_truncated,
      project_id: dependencyMap.project.id,
    };
  }, [dependencyMap]);
  const selectTask = (task: PublicPlanningTaskListItem) => {
    selectTaskId(task.id); setTaskDetail(null); setTaskDependencies(null); setEditingTask(false); setNotice(`Selected Task ${task.title}.`);
  };
  async function selectMapTask(taskId: string) {
    const loaded = tasks.find((task) => task.id === taskId);
    if (loaded) { selectTask(loaded); return; }
    const projectId = selectedProjectId;
    if (!projectId) return;
    const selectionGeneration = taskSelectionGeneration.current;
    try {
      const result = await readPlanningTask(taskId);
      if (selectedProjectRef.current !== projectId || taskSelectionGeneration.current !== selectionGeneration || result.project.id !== projectId) return;
      const task = { ...result.task, description_preview: "" };
      setTasks((current) => current.some((item) => item.id === task.id) ? current : [task, ...current]);
      selectTask(task);
    } catch { if (taskSelectionGeneration.current === selectionGeneration) setNotice("That Task could not be opened. The verified map remains available."); }
  }
  async function editSelected(changes: Record<string, unknown>, success: string): Promise<boolean> {
    if (!selectedTask || busy) return false;
    const taskId = selectedTask.id;
    const selectionGeneration = taskSelectionGeneration.current;
    const isCurrentSelection = () => selectedTaskRef.current === taskId && taskSelectionGeneration.current === selectionGeneration;
    setBusy(true); setNotice("Saving Task…");
    let result: PublicPlanningTaskMutation;
    try {
      result = await updatePlanningTask(taskId, selectedTask.revision, changes);
      setTasks((current) => current.map((task) => task.id === result.task.id ? { ...task, ...result.task } : task));
      invalidateDependencyMap();
    } catch (error) {
      if (error instanceof PublicPlanningError && error.code === "conflict") {
        try {
          const [detailed, relationships] = await Promise.all([readPlanningTaskDetail(taskId), readPlanningTaskDependencies(taskId)]);
          if (!isCurrentSelection()) { setBusy(false); return false; }
          setTaskDetail(detailed.task); setTaskDependencies(relationships); setDependenciesState("ready");
          const preview = detailed.task.description.replace(/\s+/gu, " ").trim();
          setTasks((current) => current.map((task) => task.id === taskId ? { ...task, ...detailed.task, description_preview: preview.length > 280 ? `${preview.slice(0, 279).trimEnd()}…` : preview } : task));
          setNotice("Task changed elsewhere; its latest dependencies are shown. Review and save again.");
        } catch { if (isCurrentSelection()) setNotice("Task changed elsewhere or could not be saved. Refresh the Project and try again."); }
      } else if (isCurrentSelection()) setNotice("Task changed elsewhere or could not be saved. Refresh the Project and try again.");
      setBusy(false); return false;
    }
    try {
      const detailed = await readPlanningTaskDetail(result.task.id);
      if (!isCurrentSelection()) { setBusy(false); return false; }
      setTaskDetail(detailed.task);
      const preview = detailed.task.description.replace(/\s+/gu, " ").trim();
      setTasks((current) => current.map((task) => task.id === result.task.id ? { ...task, description_preview: preview.length > 280 ? `${preview.slice(0, 279).trimEnd()}…` : preview } : task));
      try {
        const relationships = await readPlanningTaskDependencies(result.task.id);
        if (!isCurrentSelection()) { setBusy(false); return false; }
        setTaskDependencies(relationships); setDependenciesState("ready");
      } catch { if (isCurrentSelection()) setDependenciesState("unavailable"); }
      setNotice(success);
    } catch { if (isCurrentSelection()) setNotice("Task saved. Its refreshed details are temporarily unavailable."); }
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
    const taskId = selectedTask?.id;
    const saved = await editSelected({ workflow_stage: stage }, `Task moved to ${stage.replace("_", " ")}.`);
    if (!saved || !taskId || selectedTaskRef.current !== taskId) return;
    try {
      await refreshExecution(taskId);
    } catch {
      if (selectedTaskRef.current === taskId) {
        setTaskExecution(null);
        setExecutionState("unavailable");
      }
    }
  }
  function applyExecutionMutation(result: PublicPlanningTaskExecutionMutation) {
    setTaskExecution({ execution: result.execution, runtime: result.runtime, schema_version: result.schema_version, service: result.service, status: result.status, task: result.task });
    setExecutionState("ready");
    setTasks((current) => current.map((task) => task.id === result.task.id ? { ...task, ...result.task } : task));
  }
  async function refreshExecution(taskId: string) {
    if (selectedTaskRef.current !== taskId) return;
    const generation = ++executionGeneration.current;
    const isCurrent = () => generation === executionGeneration.current && selectedTaskRef.current === taskId;
    const [execution, task] = await Promise.all([readPlanningTaskExecution(taskId), readPlanningTask(taskId)]);
    if (!isCurrent()) return;
    setTaskExecution(execution); setExecutionState("ready");
    setTasks((current) => current.map((item) => item.id === task.task.id ? { ...item, ...task.task } : item));
    const detailGeneration = ++taskDetailGeneration.current;
    try { const detail = await readPlanningTaskDetail(taskId); if (isCurrent() && detailGeneration === taskDetailGeneration.current) setTaskDetail(detail.task); } catch { /* The confirmed Task state remains available from the execution projection. */ }
  }
  async function previewRunOnce() {
    if (!selectedTask || !selectedTaskExecution || busy || !selectedTaskExecution.execution.available || selectedTaskExecution.task.revision !== selectedTask.revision) return;
    const taskId = selectedTask.id;
    const taskRevision = selectedTask.revision;
    const executionEpoch = executionGeneration.current;
    const isCurrent = () => selectedTaskRef.current === taskId && executionGeneration.current === executionEpoch;
    setBusy(true); setNotice("Preparing Run once…");
    try {
      const preview = await previewPlanningTaskRunOnce(taskId, taskRevision);
      if (!isCurrent()) return;
      if (preview.task.id !== taskId) return;
      setRunOnceConfirmation({ confirmationId: preview.confirmation_id, idempotencyKey: crypto.randomUUID(), revision: preview.task.revision, taskId });
      setNotice("Review the exact Task revision, then start this Run once.");
    } catch { if (isCurrent()) setNotice("Run once is unavailable or this Task changed. Refresh and try again."); }
    finally { setBusy(false); }
  }
  async function confirmRunOnce() {
    if (!selectedTask || !selectedTaskExecution || !runOnceConfirmation || busy || selectedTaskExecution.task.id !== selectedTask.id || selectedTask.id !== runOnceConfirmation.taskId || selectedTask.revision !== runOnceConfirmation.revision) return;
    const taskId = selectedTask.id;
    const executionEpoch = executionGeneration.current;
    const isCurrent = () => selectedTaskRef.current === taskId && executionGeneration.current === executionEpoch;
    const isSelected = () => selectedTaskRef.current === taskId;
    setBusy(true); setNotice("Starting Run once…");
    try {
      const result = await confirmPlanningTaskRunOnce(taskId, runOnceConfirmation.revision, runOnceConfirmation.idempotencyKey, runOnceConfirmation.confirmationId);
      if (!isCurrent()) return;
      applyExecutionMutation(result); setRunOnceConfirmation(null);
      try {
        await refreshExecution(taskId);
        if (isSelected()) setNotice("Run once started.");
      } catch {
        if (isSelected()) setNotice("Run once started. Its latest Task details are temporarily unavailable.");
      }
    } catch {
      if (isCurrent()) { setRunOnceConfirmation(null); setNotice("Run once was not started. Refresh the Task before trying again."); }
    }
    finally { setBusy(false); }
  }
  async function reviewExecution(action: "accept" | "request_changes") {
    if (!selectedTask || !selectedTaskExecution || busy || !selectedTaskExecution.execution.review.available || selectedTaskExecution.task.id !== selectedTask.id || selectedTaskExecution.task.revision !== selectedTask.revision) return;
    const taskId = selectedTask.id;
    const executionEpoch = executionGeneration.current;
    const isCurrent = () => selectedTaskRef.current === taskId && executionGeneration.current === executionEpoch;
    const isSelected = () => selectedTaskRef.current === taskId;
    const note = action === "request_changes" ? reviewNote.trim() : null;
    if (action === "request_changes" && !note) return;
    setBusy(true); setNotice(action === "accept" ? "Accepting Task…" : "Requesting changes…");
    try {
      const result = await reviewPlanningTaskExecution(taskId, selectedTask.revision, action, note, crypto.randomUUID());
      if (!isCurrent()) return;
      applyExecutionMutation(result); setRequestChanges(false); setReviewNote("");
      try {
        await refreshExecution(taskId);
        if (isSelected()) setNotice(action === "accept" ? "Task accepted." : "Changes requested; the Task is planned for another Run.");
      } catch {
        if (isSelected()) setNotice(action === "accept" ? "Task accepted. Its latest details are temporarily unavailable." : "Changes requested. Its latest details are temporarily unavailable.");
      }
    } catch {
      if (isCurrent()) setNotice("The Task changed or review is no longer available. Refresh and try again.");
    }
    finally { setBusy(false); }
  }
  async function lifecycle(action: "archive" | "restore") {
    if (!selectedProject || busy) return;
    setBusy(true); setNotice(`${action === "archive" ? "Archiving" : "Restoring"} Project…`);
    try {
      const result = await updatePlanningProject(selectedProject.id, selectedProject.revision, action, null);
      const visibility: ProjectVisibility = action === "archive" ? "archived" : "active";
      changeProjectVisibility(visibility);
      await refreshOverview(result.project.id, visibility);
      setNotice(`Project ${action}d.`);
    }
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
      <div aria-label="Project visibility" className="saved-view-navigation"><p className="console-kicker">Project view</p>{(["active", "all", "archived"] as const).map((visibility) => <button aria-pressed={projectVisibility === visibility} disabled={busy} key={visibility} onClick={() => selectProjectVisibility(visibility)} type="button">{visibility === "all" ? "All Projects" : visibility === "active" ? "Active Projects" : "Archived Projects"}</button>)}</div>
      {state === "loading" ? <p>Loading Projects…</p> : state === "unavailable" || state === "error" ? <p>Projects are temporarily unavailable.</p> : visibleProjects.length ? <ul>{visibleProjects.map((project) => <li key={project.id}><button aria-current={project.id === selectedProjectId ? "true" : undefined} aria-label={`Select ${project.name} Project`} data-project-id={project.id} disabled={busy} onClick={() => selectProject(project.id)} type="button"><strong>{project.name}</strong><span>{project.status}</span></button></li>)}</ul> : overview?.projects.length ? projectVisibility === "archived" ? <section aria-label="Archived Project recovery"><p>No archived Projects.</p><p>Archived Projects can be restored here when needed.</p><button disabled={busy} onClick={() => selectProjectVisibility("active")} type="button">Show active Projects</button></section> : projectVisibility === "active" ? <section aria-label="Archived Project recovery"><p>No active Projects.</p><p>Open Archived Projects to restore one.</p><button disabled={busy} onClick={() => selectProjectVisibility("archived")} type="button">View archived Projects</button></section> : <p>No Projects match this view.</p> : <p>No Projects yet.</p>}
      <div className="saved-view-navigation"><p className="console-kicker">Saved view</p>{(["all", "today", "waiting", "review", "someday", "completed"] as const).map((item) => <button aria-pressed={savedView === item} disabled={busy} key={item} onClick={() => setSavedView(item)} type="button">{item === "all" ? "All tasks" : item}</button>)}</div>
    </nav>
    <div className="project-tasks-pane planning-task-pane">
      <div className="projects-tasks-heading"><div><p className="console-kicker">Tasks</p><h2>{selectedProject?.name ?? "Tasks"}</h2></div><button disabled={busy || !selectedProjectId || selectedProject?.status !== "active"} onClick={() => { setProjectForm(false); setProjectName(""); setTaskFormProjectId(selectedProjectId); setTaskForm(true); window.setTimeout(() => taskInput.current?.focus(), 0); }} ref={addTaskButton} type="button">Add</button></div>
      {taskForm ? <form className="task-create-form" onSubmit={(event) => { event.preventDefault(); void submitTask(); }}><label><span>Title</span><input onChange={(event) => { if ([...event.target.value].length <= 161) setTaskTitle(event.target.value); }} ref={taskInput} value={taskTitle} /></label><label><span>Agent</span><select aria-describedby="task-agent-state" disabled={agentsState === "loading" || agentsState === "empty" || agentsState === "unavailable"} onChange={(event) => setTaskAgent(event.target.value)} value={taskAgent}><option value="">{agentsState === "loading" ? "Loading" : agentsState === "unavailable" ? "Unavailable" : agentsState === "empty" ? "No Agents" : "Unassigned"}</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label><p className="task-agent-state" id="task-agent-state">{agentsState === "unavailable" ? "Agent assignment is unavailable; Create will leave this Task unassigned." : agentsState === "empty" ? "No Agents are available; Create will leave this Task unassigned." : "Assignment is optional."}</p><label><span>Due</span><input onChange={(event) => setTaskDue(event.target.value)} type="date" value={taskDue} /></label><div><button aria-label="Create Task" disabled={busy || !taskTitle.trim() || [...taskTitle.trim()].length > 160} type="submit">Create</button><button aria-label="Cancel Task" disabled={busy} onClick={() => { closeTaskForm(); window.setTimeout(() => addTaskButton.current?.focus(), 0); }} type="button">Cancel</button></div></form> : null}
      <section aria-label="Search Projects and Tasks" className="planning-navigation-search">
        <label><span>Search Projects and Tasks</span><input maxLength={160} onChange={(event) => { if (!/\p{C}/u.test(event.target.value)) setPlanningSearchQuery(event.target.value); }} placeholder="Find a Project or Task" type="search" value={planningSearchQuery} /></label>
        {planningSearchState === "loading" ? <p aria-live="polite" role="status">Searching Projects and Tasks…</p> : null}
        {planningSearchState === "unavailable" ? <p role="status">Search is temporarily unavailable. Your current selection did not change.</p> : null}
        {planningSearchState === "empty" ? <p>No Projects or Tasks match this search.</p> : null}
        {planningSearchState === "ready" && planningSearch ? <div className="planning-navigation-search-results">
          {planningSearch.projects.length ? <section aria-label="Project search results"><h3>Projects</h3><ul>{planningSearch.projects.map((result) => <li key={`project:${result.id}`}><span>{result.title}</span><button aria-label={`Open Project ${result.title}`} disabled={busy} onClick={() => void openPlanningSearchResult(result)} type="button">Open</button></li>)}</ul></section> : null}
          {planningSearch.tasks.length ? <section aria-label="Task search results"><h3>Tasks</h3><ul>{planningSearch.tasks.map((result) => <li key={`task:${result.id}`}><span>{result.title}</span><button aria-label={`Open Task ${result.title}`} disabled={busy} onClick={() => void openPlanningSearchResult(result)} type="button">Open</button></li>)}</ul></section> : null}
          {planningSearch.truncated ? <p>More matching results are available. Refine your search.</p> : null}
        </div> : null}
      </section>
      <div className="planning-workbench-tools"><label><span>Filter</span><input maxLength={160} onChange={(event) => { if (!/\p{C}/u.test(event.target.value)) setFilter(event.target.value); }} placeholder="Find a task" type="search" value={filter} /></label><div aria-label="Display mode" className="planning-mode-toggle"><button aria-pressed={view === "list"} onClick={() => setView("list")} type="button">List</button><button aria-pressed={view === "board"} onClick={() => setView("board")} type="button">Board</button><button aria-pressed={view === "map"} onClick={() => setView("map")} type="button">Map</button></div></div>
      {tasksState === "loading" ? <p>Loading Tasks…</p> : tasksState === "unavailable" || tasksState === "error" ? <p>Tasks are temporarily unavailable.</p> : view === "map" ? dependencyMapState === "loading" ? <p aria-live="polite" role="status">Loading the dependency map…</p> : dependencyMapState === "unavailable" || dependencyMapState === "error" ? <p role="status">The dependency map is temporarily unavailable. List and Board remain available.</p> : dependencyMapGraph ? <TaskDependencyMap graph={dependencyMapGraph} onSelectedTaskIdChange={(taskId) => void selectMapTask(taskId)} selectedTaskId={selectedTaskId} /> : <p role="status">No dependency map is available for this Project.</p> : filteredTasks.length ? view === "list" ? <ul className="project-task-list">{filteredTasks.map(taskCard)}</ul> : <div aria-label="Task board" className="planning-board">{stages.map((stage) => <section key={stage}><h3>{stage.replace("_", " ")}</h3><ul className="project-task-list">{filteredTasks.filter((task) => task.workflow_stage === stage).map(taskCard)}</ul></section>)}</div> : <p>{tasks.length ? "No Tasks match this view." : "No Tasks in this Project."}</p>}
      {taskCursor ? <button className="project-tasks-more" disabled={loadingMore} onClick={() => void loadMoreTasks()} type="button">{loadingMore ? "Loading…" : "More"}</button> : null}
    </div>
    <aside aria-label="Task inspector" className="project-tasks-pane planning-inspector">
      <div className="projects-tasks-heading"><div><p className="console-kicker">Inspector</p><h2>{selectedTask ? "Task details" : "Select a Task"}</h2></div></div>
      {!selectedTask ? <p>Select a Task to review its description, planning details, and lifecycle.</p> : <>
        <p className="planning-description">{(taskDetail?.description ?? selectedTask.description_preview) || "This Task has no description."}</p>
        <dl className="planning-summary"><div><dt>Stage</dt><dd>{selectedTask.workflow_stage.replace("_", " ")}</dd></div><div><dt>Priority</dt><dd>{selectedTask.priority}</dd></div><div><dt>Due</dt><dd>{selectedTask.due_date ?? "Not scheduled"}</dd></div></dl>
        {taskDetail && hasPlanningMetadata ? <section aria-label="Planning details" className="planning-metadata">
          <p className="console-kicker">Planning details</p>
          {taskDetail.scheduled_block ? <dl className="planning-summary"><div><dt>{taskDetail.scheduled_block.label ?? "Schedule"}</dt><dd><time dateTime={taskDetail.scheduled_block.start}>{planningTimestamp(taskDetail.scheduled_block.start, taskDetail.scheduled_block.timezone)}</time> – <time dateTime={taskDetail.scheduled_block.end}>{planningTimestamp(taskDetail.scheduled_block.end, taskDetail.scheduled_block.timezone)}</time></dd></div></dl> : null}
          {taskDetail.reminders.length ? <section aria-label="Browser reminders"><h3>Browser reminders</h3><ul>{taskDetail.reminders.map((reminder) => <li key={reminder.id}><span>{reminder.enabled ? "On" : "Off"}</span><time dateTime={reminder.at}>{planningTimestamp(reminder.at, reminder.timezone)}</time>{reminder.notified_at ? <small>Sent</small> : null}</li>)}</ul></section> : null}
          {taskDetail.calendar_links.length ? <section aria-label="Calendar links"><h3>Calendar links</h3><ul>{taskDetail.calendar_links.map((link, index) => <li key={`${link.calendar_id}:${link.event_id}`}>{link.label ?? `Linked calendar event ${index + 1}`}</li>)}</ul></section> : null}
          {taskDetail.note_links.length ? <section aria-label="Notes"><h3>Notes</h3><ul>{taskDetail.note_links.map((link, index) => <li key={link.path}>{noteLinkLabel(link.path, link.title, index)}</li>)}</ul></section> : null}
        </section> : null}
        <div className="planning-stage-controls"><p className="console-kicker">Move stage</p>{stages.map((stage) => <button aria-pressed={selectedTask.workflow_stage === stage} disabled={busy || selectedTask.workflow_stage === stage || executionOwnsTerminalStages && (stage === "review" || stage === "done")} key={stage} onClick={() => void changeStage(stage)} type="button">{stage.replace("_", " ")}</button>)}{executionOwnsTerminalStages ? <p>Run and review controls own the Review and Done stages until this attempt is resolved.</p> : null}</div>
        <section aria-label="Task execution" className="planning-execution">
          <p className="console-kicker">Execution</p>
          {executionState === "loading" ? <p>Loading execution status…</p> : executionState === "unavailable" || !selectedTaskExecution ? <p>Run once and review controls are temporarily unavailable.</p> : <>
            {selectedTaskExecution.execution.attempts.length ? <ul aria-label="Execution attempts">{selectedTaskExecution.execution.attempts.map((attempt) => <li key={attempt.run_id}><span>{attempt.state.replaceAll("_", " ")} · {attempt.status.replaceAll("_", " ")}</span><time dateTime={attempt.updated_at}>{attempt.completed_at ? "Completed" : "Updated"} {attempt.updated_at}</time>{attempt.partial ? <small>Partial evidence</small> : null}</li>)}</ul> : <p>No Run attempts yet.</p>}
            {selectedTaskExecution.execution.review.available ? <div className="planning-review-actions"><p>This Task is ready for your review.</p><div><button disabled={busy} onClick={() => void reviewExecution("accept")} type="button">Accept</button><button aria-expanded={requestChanges} disabled={busy} onClick={() => setRequestChanges((current) => !current)} type="button">Request changes</button></div>{requestChanges ? <form onSubmit={(event) => { event.preventDefault(); void reviewExecution("request_changes"); }}><label><span>Feedback for changes</span><textarea maxLength={2000} onChange={(event) => setReviewNote(event.target.value)} value={reviewNote} /></label><div><button disabled={busy || !reviewNote.trim()} type="submit">Send change request</button><button disabled={busy} onClick={() => { setRequestChanges(false); setReviewNote(""); }} type="button">Cancel</button></div></form> : null}</div> : selectedTaskExecution.execution.available ? runOnceConfirmation && runOnceConfirmation.taskId === selectedTask.id ? <div className="planning-run-once-confirmation"><p>Start one Run for this exact Task revision?</p><div><button disabled={busy || selectedTask.revision !== runOnceConfirmation.revision} onClick={() => void confirmRunOnce()} type="button">Start Run once</button><button disabled={busy} onClick={() => setRunOnceConfirmation(null)} type="button">Cancel</button></div></div> : <button disabled={busy} onClick={() => void previewRunOnce()} type="button">Run once</button> : <p>Run once is unavailable for this Task.</p>}
          </>}
        </section>
        <section aria-label="Task delegation" className="planning-execution">
          <p className="console-kicker">Delegation</p>
          {delegationRecovery ? <div className="planning-run-once-confirmation"><p>The prior delivery is indeterminate. Reconcile it without sending it again.</p><button disabled={busy} onClick={() => void recoverDelegation()} type="button">Reconcile prior delivery</button></div> : delegationState === "loading" ? <p>Loading delegation status…</p> : delegationState === "unavailable" || !selectedTaskDelegation ? <p>Delegation status is temporarily unavailable.</p> : selectedTaskDelegation.delegation.available === false ? <>
            <p>This Task has not been delegated.</p>
            {!delegationForm ? <button disabled={busy} onClick={() => void openDelegationForm()} type="button">Delegate</button> : delegationOptions?.options.available ? <form className="planning-review-actions" onSubmit={(event) => { event.preventDefault(); void previewDelegation(); }}>
              <label><span>Agent</span><select disabled={busy} onChange={(event) => setDelegationProfile(event.target.value)} value={delegationProfile}>{delegationOptions.options.profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
              <label><span>Board</span><select disabled={busy} onChange={(event) => setDelegationBoard(event.target.value)} value={delegationBoard}>{delegationOptions.options.boards.map((board) => <option key={board.id} value={board.id}>{board.name}</option>)}</select></label>
              <label><span>Workspace</span><select disabled={busy} onChange={(event) => setDelegationWorkspace(event.target.value as "scratch" | "worktree")} value={delegationWorkspace}>{delegationOptions.options.workspaces.map((workspace) => <option key={workspace} value={workspace}>{workspace}</option>)}</select></label>
              <label><span>Instructions (optional)</span><textarea maxLength={8000} onChange={(event) => setDelegationInstructions(event.target.value)} value={delegationInstructions} /></label>
              <div><button disabled={busy || !delegationProfile || !delegationBoard} type="submit">Preview delegation</button><button disabled={busy} onClick={() => { setDelegationForm(false); setDelegationPreview(null); }} type="button">Cancel</button></div>
            </form> : <p>Delegation options are unavailable for this Task.</p>}
            {delegationPreview?.action === "delegate" ? <div className="planning-run-once-confirmation"><p>{delegationPreview.effects.join(" ")}</p><div><button disabled={busy} onClick={() => void confirmDelegation()} type="button">Confirm delegation</button><button disabled={busy} onClick={() => setDelegationPreview(null)} type="button">Back</button></div></div> : null}
          </> : <>
            <dl className="planning-summary"><div><dt>State</dt><dd>{selectedTaskDelegation.delegation.state.replaceAll("_", " ")}</dd></div><div><dt>Sync</dt><dd>{selectedTaskDelegation.delegation.sync_state}</dd></div><div><dt>Review</dt><dd>{selectedTaskDelegation.delegation.review_state.replaceAll("_", " ")}</dd></div><div><dt>Attempts</dt><dd>{selectedTaskDelegation.delegation.attempts}</dd></div><div><dt>Files</dt><dd>{selectedTaskDelegation.delegation.artifact_count}</dd></div>{selectedTaskDelegation.delegation.last_outcome ? <div><dt>Outcome</dt><dd>{selectedTaskDelegation.delegation.last_outcome.replaceAll("_", " ")}</dd></div> : null}</dl>
            {selectedTaskDelegation.delegation.summary ? <p><strong>Summary</strong> {selectedTaskDelegation.delegation.summary}</p> : null}
            {selectedTaskDelegation.delegation.latest_question ? <p><strong>Needs input</strong> {selectedTaskDelegation.delegation.latest_question}</p> : null}
            <div className="planning-review-actions"><button disabled={busy} onClick={() => void refreshDelegation()} type="button">Refresh</button>{selectedTaskDelegation.delegation.state === "ready_for_review" ? <><button disabled={busy} onClick={() => void previewDelegationAction("accept", null)} type="button">Accept</button><button disabled={busy} onClick={() => { setDelegationAction("request_revision"); setDelegationActionNote(""); }} type="button">Request revision</button></> : null}{["needs_input", "blocked", "failed", "cancelled"].includes(selectedTaskDelegation.delegation.state) ? <><button disabled={busy} onClick={() => { setDelegationAction("reply"); setDelegationActionNote(""); }} type="button">Reply</button><button disabled={busy} onClick={() => void previewDelegationAction("retry", null)} type="button">Retry</button></> : null}{selectedTaskDelegation.delegation.state === "running" ? <button disabled={busy} onClick={() => void previewDelegationAction("stop", null)} type="button">Stop</button> : null}{selectedTaskDelegation.delegation.state !== "completed" ? <button disabled={busy} onClick={() => { setDelegationAction("mark_blocked"); setDelegationActionNote(""); }} type="button">Mark blocked</button> : null}</div>
            {delegationAction && ["reply", "request_revision", "mark_blocked"].includes(delegationAction) && !delegationActionPreview ? <form className="planning-review-actions" onSubmit={(event) => { event.preventDefault(); void previewDelegationAction(delegationAction, delegationActionNote); }}><label><span>{delegationAction.replaceAll("_", " ")} note</span><textarea maxLength={8000} onChange={(event) => setDelegationActionNote(event.target.value)} value={delegationActionNote} /></label><div><button disabled={busy || !delegationActionNote.trim()} type="submit">Preview action</button><button disabled={busy} onClick={() => { setDelegationAction(null); setDelegationActionNote(""); }} type="button">Cancel</button></div></form> : null}
            {delegationActionPreview ? <div className="planning-run-once-confirmation"><p>{delegationActionPreview.effects.join(" ")}</p><div><button disabled={busy} onClick={() => void confirmDelegationAction()} type="button">Confirm action</button><button disabled={busy} onClick={() => setDelegationActionPreview(null)} type="button">Back</button></div></div> : null}
          </>}
        </section>
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
        <section aria-label="Task deletion" className="planning-project-lifecycle">
          <p className="console-kicker">Task lifecycle</p>
          {deletionPreview?.target_kind === "task" && deletionPreview.target_id === selectedTask.id ? <div className="planning-run-once-confirmation">
            <p>Delete {deletionSummary(deletionPreview.affected)}. This cannot be undone.</p>
            {deletionPreview.has_active_runs ? <p>Affected active Runs will be stopped and re-read first. If that cannot be verified, nothing is removed.</p> : null}
            <div><button disabled={busy} onClick={() => void confirmDeletion()} type="button">Confirm delete Task</button><button disabled={busy} onClick={() => setDeletionPreview(null)} type="button">Cancel</button></div>
          </div> : <button disabled={busy} onClick={() => void reviewDeletion("task")} type="button">Delete Task</button>}
        </section>
      </>}
      {selectedProject ? <section className="planning-project-lifecycle"><p className="console-kicker">Project lifecycle</p>{renameProject ? <form className="project-create-form" onSubmit={(event) => { event.preventDefault(); void saveProjectName(); }}><label><span>Name</span><input maxLength={120} onChange={(event) => setProjectRename(event.target.value)} value={projectRename} /></label><div><button disabled={busy || !projectRename.trim()} type="submit">Save name</button><button disabled={busy} onClick={() => setRenameProject(false)} type="button">Cancel</button></div></form> : <button disabled={busy} onClick={() => { setProjectRename(selectedProject.name); setRenameProject(true); }} type="button">Rename Project</button>}{selectedProject.status === "archived" ? <button disabled={busy} onClick={() => void lifecycle("restore")} type="button">Restore Project</button> : <button disabled={busy} onClick={() => void lifecycle("archive")} type="button">Archive Project</button>}{deletionPreview?.target_kind === "project" && deletionPreview.target_id === selectedProject.id ? <div className="planning-run-once-confirmation"><p>Delete {deletionSummary(deletionPreview.affected)}. This cannot be undone.</p>{deletionPreview.has_active_runs ? <p>Affected active Runs will be stopped and re-read first. If that cannot be verified, nothing is removed.</p> : null}<div><button disabled={busy} onClick={() => void confirmDeletion()} type="button">Confirm delete Project</button><button disabled={busy} onClick={() => setDeletionPreview(null)} type="button">Cancel</button></div></div> : <button disabled={busy} onClick={() => void reviewDeletion("project")} type="button">Delete Project</button>}</section> : null}
    </aside>
    <p aria-live="polite" className="projects-tasks-notice" role="status">{notice}</p>
  </section>;
}
