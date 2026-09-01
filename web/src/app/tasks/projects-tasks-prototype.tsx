"use client";

import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

type Variant = "a" | "b" | "c";
type View = "list" | "board" | "map";
type Stage = "Inbox" | "Planned" | "In progress" | "Waiting" | "Review" | "Done";

type PrototypeTask = {
  agent: string | null;
  condition: "ready" | "blocked" | "active" | "needs input" | "review" | "none";
  dependsOn: string[];
  due: string | null;
  estimate: string;
  id: string;
  projectId: string;
  projectName: string;
  stage: Stage;
  summary: string;
  title: string;
};

const projects = [
  { id: "mentat", name: "Mentat", tone: "#9dce9b" },
  { id: "release", name: "Beta release", tone: "#70a9bd" },
  { id: "research", name: "Research", tone: "#d1ab73" },
];

const initialTasks: PrototypeTask[] = [
  { agent: "Codex Engineer", condition: "active", dependsOn: ["task-schema"], due: "Sep 2", estimate: "3h", id: "task-inspector", projectId: "mentat", projectName: "Mentat", stage: "In progress", summary: "Build the Task inspector and exact-revision edit flow.", title: "Task inspector" },
  { agent: null, condition: "ready", dependsOn: [], due: "Today", estimate: "90m", id: "task-schema", projectId: "mentat", projectName: "Mentat", stage: "Planned", summary: "Move canonical Projects into SQLite and bind Tasks by Project ID.", title: "Project authority migration" },
  { agent: "Hermes Researcher", condition: "review", dependsOn: [], due: "Today", estimate: "2h", id: "task-graph", projectId: "mentat", projectName: "Mentat", stage: "Review", summary: "Validate the bounded dependency map against real planning scenarios.", title: "Dependency map research" },
  { agent: null, condition: "blocked", dependsOn: ["task-inspector", "task-copy"], due: "Sep 4", estimate: "4h", id: "task-board", projectId: "mentat", projectName: "Mentat", stage: "Waiting", summary: "Present Tasks by workflow stage without mixing Run state into planning.", title: "Planning board" },
  { agent: "Codex Engineer", condition: "needs input", dependsOn: ["task-graph"], due: "Sep 5", estimate: "2h", id: "task-copy", projectId: "release", projectName: "Beta release", stage: "Waiting", summary: "Write concise labels for Run once, Delegate, Review, and Request changes.", title: "Work-action language" },
  { agent: null, condition: "none", dependsOn: [], due: null, estimate: "45m", id: "task-mobile", projectId: "release", projectName: "Beta release", stage: "Inbox", summary: "Decide the mobile default between List and Dependencies.", title: "Mobile planning flow" },
  { agent: "Hermes Researcher", condition: "none", dependsOn: [], due: null, estimate: "1h", id: "task-auth", projectId: "research", projectName: "Research", stage: "Planned", summary: "Outline one-owner remote access without changing the current local boundary.", title: "Remote access questions" },
  { agent: null, condition: "none", dependsOn: [], due: "Aug 30", estimate: "30m", id: "task-fixtures", projectId: "mentat", projectName: "Mentat", stage: "Done", summary: "Create public-safe dense fixtures for planning acceptance.", title: "Planning fixtures" },
];

const stageOrder: Stage[] = ["Inbox", "Planned", "In progress", "Waiting", "Review", "Done"];
const variantNames: Record<Variant, string> = { a: "Workbench", b: "Focus", c: "Map room" };

function stageClass(stage: Stage) {
  return `ptp-stage-${stage.toLowerCase().replaceAll(" ", "-")}`;
}

function PrototypeSwitcher({ variant }: { variant: Variant }) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const variants: Variant[] = ["a", "b", "c"];

  function select(next: Variant) {
    const parameters = new URLSearchParams(search.toString());
    parameters.set("variant", next);
    router.replace(`${pathname}?${parameters.toString()}`, { scroll: false });
  }

  function cycle(direction: number) {
    const index = variants.indexOf(variant);
    select(variants[(index + direction + variants.length) % variants.length]);
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select, [contenteditable='true']")) return;
      if (event.key === "ArrowLeft") { event.preventDefault(); cycle(-1); }
      if (event.key === "ArrowRight") { event.preventDefault(); cycle(1); }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  return <nav aria-label="Prototype variants" className="ptp-switcher">
    <button aria-label="Previous prototype" onClick={() => cycle(-1)} type="button">←</button>
    <span><strong>{variant.toUpperCase()}</strong> {variantNames[variant]}</span>
    <button aria-label="Next prototype" onClick={() => cycle(1)} type="button">→</button>
  </nav>;
}

function StatusPill({ task }: { task: PrototypeTask }) {
  return <span className={`ptp-status ${stageClass(task.stage)}`}>{task.condition === "none" ? task.stage : task.condition}</span>;
}

function TaskRow({ selected, task, onSelect }: { selected: boolean; task: PrototypeTask; onSelect: (id: string) => void }) {
  return <button aria-pressed={selected} className="ptp-task-row" onClick={() => onSelect(task.id)} type="button">
    <span className="ptp-task-check" aria-hidden="true">{task.stage === "Done" ? "✓" : ""}</span>
    <span className="ptp-task-copy"><strong>{task.title}</strong><small>{task.projectName} · {task.agent ?? "Unassigned"}</small></span>
    <StatusPill task={task} />
    <span className="ptp-task-due">{task.due ?? "No date"}</span>
  </button>;
}

type SharedProps = {
  onDelete: (scope: "task" | "project") => void;
  onRequestChanges: () => void;
  onSelect: (id: string) => void;
  onSimulateAgentTask: () => void;
  selected: PrototypeTask;
  selectedProject: string;
  setSelectedProject: (id: string) => void;
  setView: (view: View) => void;
  tasks: PrototypeTask[];
  view: View;
};

function ProjectRail({ selected, setSelected }: { selected: string; setSelected: (id: string) => void }) {
  return <aside className="ptp-project-rail" aria-label="Projects and saved views">
    <div className="ptp-rail-heading"><span>Projects</span><button type="button">+</button></div>
    {projects.map((project) => <button aria-current={selected === project.id ? "page" : undefined} key={project.id} onClick={() => setSelected(project.id)} type="button"><i style={{ background: project.tone }} /><span>{project.name}</span><small>{initialTasks.filter((task) => task.projectId === project.id).length}</small></button>)}
    <div className="ptp-rail-heading ptp-saved"><span>Saved views</span></div>
    {[["Today", "4"], ["Waiting", "2"], ["Review", "1"], ["Blocked", "1"], ["Completed", "1"]].map(([label, count]) => <button key={label} type="button"><span>{label}</span><small>{count}</small></button>)}
  </aside>;
}

function TaskInspector({ onDelete, onRequestChanges, onSimulateAgentTask, task }: { onDelete: () => void; onRequestChanges: () => void; onSimulateAgentTask: () => void; task: PrototypeTask }) {
  return <aside className="ptp-inspector" aria-label="Selected Task details">
    <div className="ptp-inspector-heading"><span>{task.projectName}</span><StatusPill task={task} /></div>
    <h2>{task.title}</h2>
    <p>{task.summary}</p>
    <dl><div><dt>Agent</dt><dd>{task.agent ?? "Unassigned"}</dd></div><div><dt>Estimate</dt><dd>{task.estimate}</dd></div><div><dt>Due</dt><dd>{task.due ?? "No date"}</dd></div></dl>
    <section><h3>Checklist</h3><label><input defaultChecked type="checkbox" /> Define safe projection</label><label><input type="checkbox" /> Verify mobile interaction</label></section>
    <section><h3>Dependencies</h3>{task.dependsOn.length ? task.dependsOn.map((id) => <button className="ptp-dependency" key={id} type="button">← {initialTasks.find((item) => item.id === id)?.title ?? id}</button>) : <p>No prerequisites.</p>}<button className="ptp-add-dependency" type="button">+ Add dependency</button></section>
    <section><h3>Work</h3><div className="ptp-actions"><button type="button">Run once</button><button type="button">Delegate</button>{task.stage === "Review" ? <button onClick={onRequestChanges} type="button">Request changes</button> : null}</div></section>
    <section><h3>Prototype actions</h3><div className="ptp-actions"><button onClick={onSimulateAgentTask} type="button">Agent creates prerequisite</button><button className="ptp-danger" onClick={onDelete} type="button">Delete Task</button></div></section>
  </aside>;
}

function TaskList({ onSelect, selected, tasks }: { onSelect: (id: string) => void; selected: string; tasks: PrototypeTask[] }) {
  return <div className="ptp-list" role="list">{tasks.map((task) => <TaskRow key={task.id} onSelect={onSelect} selected={selected === task.id} task={task} />)}</div>;
}

function Board({ onSelect, selected, tasks }: { onSelect: (id: string) => void; selected: string; tasks: PrototypeTask[] }) {
  return <div className="ptp-board">{stageOrder.map((stage) => <section key={stage}><header><h3>{stage}</h3><span>{tasks.filter((task) => task.stage === stage).length}</span></header>{tasks.filter((task) => task.stage === stage).map((task) => <button aria-pressed={selected === task.id} key={task.id} onClick={() => onSelect(task.id)} type="button"><StatusPill task={task} /><strong>{task.title}</strong><small>{task.agent ?? "Unassigned"}</small></button>)}</section>)}</div>;
}

function DependencyMap({ onSelect, selected, tasks }: { onSelect: (id: string) => void; selected: string; tasks: PrototypeTask[] }) {
  const projectIds = new Set(tasks.map((task) => task.id));
  const visible = [...tasks];
  for (const task of tasks) for (const dependency of task.dependsOn) {
    if (!projectIds.has(dependency)) {
      const external = initialTasks.find((item) => item.id === dependency);
      if (external && !visible.some((item) => item.id === external.id)) visible.push(external);
    }
  }
  const nodes: Node[] = visible.map((task, index) => {
    const rank = Math.max(0, stageOrder.indexOf(task.stage));
    return {
      id: task.id,
      data: { label: `${task.title}\n${task.projectName} · ${task.stage}` },
      position: { x: rank * 210, y: (index % 4) * 126 },
      className: `${task.projectId !== tasks[0]?.projectId ? "ptp-node-external" : ""} ${selected === task.id ? "ptp-node-selected" : ""}`,
      style: { background: "#111a1e", border: "1px solid #3b4b50", borderRadius: 10, color: "#eae7dd", fontSize: 12, padding: 10, width: 174, whiteSpace: "pre-line" },
    };
  });
  const visibleIds = new Set(visible.map((task) => task.id));
  const edges: Edge[] = visible.flatMap((task) => task.dependsOn.filter((id) => visibleIds.has(id)).map((dependency) => ({ id: `${dependency}-${task.id}`, source: dependency, target: task.id, markerEnd: { type: MarkerType.ArrowClosed }, style: { stroke: "#75a97b", strokeWidth: 1.5 } })));
  return <div className="ptp-map" aria-label="Visual Task dependency map">
    <ReactFlow edges={edges} fitView nodes={nodes} nodesConnectable={false} nodesDraggable={false} onNodeClick={(_, node) => onSelect(node.id)}>
      <Background color="#28363a" gap={24} />
      <Controls showInteractive={false} />
      <MiniMap pannable={false} zoomable={false} />
    </ReactFlow>
  </div>;
}

function VariantA(props: SharedProps) {
  const projectTasks = props.tasks.filter((task) => task.projectId === props.selectedProject);
  return <div className="ptp-shell ptp-variant-a">
    <ProjectRail selected={props.selectedProject} setSelected={props.setSelectedProject} />
    <main className="ptp-center"><header className="ptp-toolbar"><div><span>Planning workbench</span><h2>{projects.find((item) => item.id === props.selectedProject)?.name}</h2></div><div className="ptp-view-switch">{(["list", "board", "map"] as View[]).map((item) => <button aria-pressed={props.view === item} key={item} onClick={() => props.setView(item)} type="button">{item}</button>)}</div><button className="ptp-new" type="button">New Task</button></header>{props.view === "list" ? <TaskList onSelect={props.onSelect} selected={props.selected.id} tasks={projectTasks} /> : props.view === "board" ? <Board onSelect={props.onSelect} selected={props.selected.id} tasks={projectTasks} /> : <DependencyMap onSelect={props.onSelect} selected={props.selected.id} tasks={projectTasks} />}</main>
    <TaskInspector onDelete={() => props.onDelete("task")} onRequestChanges={props.onRequestChanges} onSimulateAgentTask={props.onSimulateAgentTask} task={props.selected} />
  </div>;
}

function VariantB(props: SharedProps) {
  const focusTasks = props.tasks.filter((task) => task.stage !== "Done").slice(0, 6);
  return <div className="ptp-shell ptp-variant-b">
    <header className="ptp-focus-header"><div><span>Today · Sunday, Aug 31</span><h2>What needs your attention</h2></div><div className="ptp-metrics"><strong>2</strong><span>active</span><strong>1</strong><span>review</span><strong>1</strong><span>blocked</span></div><button type="button">Capture Task</button></header>
    <nav className="ptp-focus-nav" aria-label="Planning filters">{["Today", "Upcoming", "Waiting", "Review", "Completed"].map((item, index) => <button aria-current={index === 0 ? "page" : undefined} key={item} type="button">{item}</button>)}</nav>
    <main className="ptp-focus-list"><h3>Now</h3><TaskList onSelect={props.onSelect} selected={props.selected.id} tasks={focusTasks.slice(0, 3)} /><h3>Next</h3><TaskList onSelect={props.onSelect} selected={props.selected.id} tasks={focusTasks.slice(3)} /></main>
    <div className="ptp-drawer"><TaskInspector onDelete={() => props.onDelete("task")} onRequestChanges={props.onRequestChanges} onSimulateAgentTask={props.onSimulateAgentTask} task={props.selected} /></div>
  </div>;
}

function VariantC(props: SharedProps) {
  const projectTasks = props.tasks.filter((task) => task.projectId === props.selectedProject);
  return <div className="ptp-shell ptp-variant-c">
    <header className="ptp-map-header"><div><span>Dependency map</span><h2>{projects.find((item) => item.id === props.selectedProject)?.name}</h2></div><select aria-label="Project" onChange={(event) => props.setSelectedProject(event.target.value)} value={props.selectedProject}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select><div><button type="button">Fit</button><button type="button">Dependencies</button><button onClick={() => props.onDelete("project")} type="button">Project menu</button></div></header>
    <main className="ptp-map-stage"><DependencyMap onSelect={props.onSelect} selected={props.selected.id} tasks={projectTasks} /></main>
    <aside className="ptp-outline"><header><span>Accessible outline</span><strong>{projectTasks.length} Tasks</strong></header><TaskList onSelect={props.onSelect} selected={props.selected.id} tasks={projectTasks} /></aside>
    <div className="ptp-map-inspector"><TaskInspector onDelete={() => props.onDelete("task")} onRequestChanges={props.onRequestChanges} onSimulateAgentTask={props.onSimulateAgentTask} task={props.selected} /></div>
  </div>;
}

function DeletePreview({ affected, active, onCancel, onConfirm, scope }: { affected: PrototypeTask[]; active: number; onCancel: () => void; onConfirm: () => void; scope: "task" | "project" }) {
  const [acknowledged, setAcknowledged] = useState(false);
  return <div className="ptp-modal-backdrop" role="presentation"><section aria-labelledby="ptp-delete-title" aria-modal="true" className="ptp-modal" role="dialog"><span className="ptp-danger-label">Destructive action</span><h2 id="ptp-delete-title">Delete this {scope} and related work?</h2><p>This cascade crosses Project boundaries and cannot be undone.</p><ul><li><strong>{affected.length}</strong> Tasks</li><li><strong>{Math.max(1, affected.length - 1)}</strong> Conversations</li><li><strong>{affected.length + 2}</strong> Runs and their events</li><li><strong>{active}</strong> active Run{active === 1 ? "" : "s"} must stop first</li></ul><details><summary>Show affected Tasks</summary>{affected.map((task) => <p key={task.id}>{task.projectName} / {task.title}</p>)}</details><label className="ptp-confirm"><input checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} type="checkbox" /> I understand that cross-Project work will be erased.</label><div><button onClick={onCancel} type="button">Cancel</button><button className="ptp-danger" disabled={!acknowledged} onClick={onConfirm} type="button">{active ? "Stop and delete" : "Delete"}</button></div></section></div>;
}

export function ProjectsTasksPrototype({ initialVariant }: { initialVariant: Variant }) {
  const [tasks, setTasks] = useState(initialTasks);
  const [selectedId, setSelectedId] = useState("task-inspector");
  const [selectedProject, setSelectedProject] = useState("mentat");
  const [view, setView] = useState<View>("list");
  const [notice, setNotice] = useState("Prototype state is local to this tab.");
  const [deleteScope, setDeleteScope] = useState<"task" | "project" | null>(null);
  const selected = tasks.find((task) => task.id === selectedId) ?? tasks[0];

  const affected = useMemo(() => {
    if (!deleteScope) return [];
    const roots = deleteScope === "project" ? tasks.filter((task) => task.projectId === selectedProject).map((task) => task.id) : [selected.id];
    const ids = new Set(roots);
    let changed = true;
    while (changed) {
      changed = false;
      for (const task of tasks) if (!ids.has(task.id) && task.dependsOn.some((id) => ids.has(id))) { ids.add(task.id); changed = true; }
    }
    return tasks.filter((task) => ids.has(task.id));
  }, [deleteScope, selected.id, selectedProject, tasks]);

  function requestChanges() {
    setTasks((current) => current.map((task) => task.id === selected.id ? { ...task, condition: "active", stage: "In progress", summary: `${task.summary} Revision requested: tighten the acceptance evidence.` } : task));
    setNotice("Revision instructions preserved. A new attempt is now In progress.");
  }

  function selectTask(id: string) {
    const task = tasks.find((item) => item.id === id);
    setSelectedId(id);
    if (task && initialVariant !== "b") setSelectedProject(task.projectId);
  }

  function simulateAgentTask() {
    const id = `agent-task-${tasks.length + 1}`;
    const created: PrototypeTask = { agent: selected.agent, condition: "ready", dependsOn: [], due: null, estimate: "45m", id, projectId: selected.projectId, projectName: selected.projectName, stage: "Inbox", summary: `Created by ${selected.agent ?? "the assigned Agent"} during ${selected.title}.`, title: "Verify missing prerequisite" };
    setTasks((current) => [...current.map((task) => {
      if (task.id !== selected.id) return task;
      const updated: PrototypeTask = { ...task, condition: "blocked", dependsOn: [...task.dependsOn, id], stage: "Waiting" };
      return updated;
    }), created]);
    setSelectedId(id);
    setNotice("Agent created an operator-owned Inbox Task and linked it as a prerequisite. Nothing started automatically.");
  }

  function confirmDelete() {
    const ids = new Set(affected.map((task) => task.id));
    const next = tasks.filter((task) => !ids.has(task.id));
    setTasks(next);
    setSelectedId(next[0]?.id ?? "");
    setDeleteScope(null);
    setNotice(`Stopped affected work and deleted ${affected.length} Tasks, their Conversations, Runs, events, and artifacts. A content-free receipt remains.`);
  }

  const props: SharedProps = { onDelete: setDeleteScope, onRequestChanges: requestChanges, onSelect: selectTask, onSimulateAgentTask: simulateAgentTask, selected, selectedProject, setSelectedProject, setView, tasks, view };
  return <div className="ptp-prototype">
    <div className="ptp-banner"><strong>Throwaway prototype</strong><span>Question: which workspace makes planning, dependencies, Agent work, and destructive actions easiest to understand?</span></div>
    {initialVariant === "a" ? <VariantA {...props} /> : initialVariant === "b" ? <VariantB {...props} /> : <VariantC {...props} />}
    <details className="ptp-state"><summary>Current prototype state</summary><pre>{JSON.stringify({ selectedTask: selected?.id ?? null, selectedProject, taskCount: tasks.length, view, notice }, null, 2)}</pre></details>
    <p aria-live="polite" className="ptp-notice" role="status">{notice}</p>
    {deleteScope ? <DeletePreview active={affected.filter((task) => task.condition === "active").length} affected={affected} onCancel={() => setDeleteScope(null)} onConfirm={confirmDelete} scope={deleteScope} /> : null}
    <PrototypeSwitcher variant={initialVariant} />
  </div>;
}
