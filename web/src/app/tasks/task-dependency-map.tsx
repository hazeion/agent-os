"use client";

import { Handle, Position } from "@xyflow/react";
import type { Edge, Node, NodeProps } from "@xyflow/react";
import { useEffect, useId, useMemo, useState } from "react";

const MAXIMUM_RENDERED_NODES = 128;
const MAXIMUM_RENDERED_EDGES = 256;
const NODE_WIDTH = 208;
const NODE_HEIGHT = 64;
const LAYER_GAP = 72;
const ROW_GAP = 32;
const MAP_PADDING = 28;

export type TaskDependencyMapReference = {
  id: string;
  title: string;
  project_id: string;
  project_name: string;
  workflow_stage: "inbox" | "planned" | "in_progress" | "waiting" | "review" | "done";
  blocked: boolean;
};

export type TaskDependencyMapEdge = {
  from_task_id: string;
  to_task_id: string;
};

/**
 * This is a read-only, bounded presentation projection. It deliberately does
 * not include task descriptions, revisions, or any mutation authority.
 */
export type TaskDependencyMapGraph = {
  project_id: string;
  nodes: readonly TaskDependencyMapReference[];
  external_stubs: readonly TaskDependencyMapReference[];
  edges: readonly TaskDependencyMapEdge[];
  node_count: number;
  node_total: number;
  nodes_truncated: boolean;
  external_stub_count: number;
  external_stub_total: number;
  external_stubs_truncated: boolean;
  edge_count: number;
  edge_total: number;
  edges_truncated: boolean;
};

type MapNode = TaskDependencyMapReference & { external: boolean };

export type TaskDependencyMapLayoutNode = MapNode & {
  x: number;
  y: number;
  layer: number;
};

export type TaskDependencyMapLayout = {
  nodes: readonly TaskDependencyMapLayoutNode[];
  edges: readonly (TaskDependencyMapEdge & { id: string })[];
  width: number;
  height: number;
  omitted_nodes: number;
  omitted_edges: number;
};

function compareText(left: string, right: string) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function stageLabel(stage: TaskDependencyMapReference["workflow_stage"]) {
  return stage.replace(/_/gu, " ");
}

function visibleGraph(graph: TaskDependencyMapGraph) {
  const known = new Map<string, MapNode>();
  const add = (reference: TaskDependencyMapReference, external: boolean) => {
    if (known.size >= MAXIMUM_RENDERED_NODES || known.has(reference.id)) return;
    known.set(reference.id, { ...reference, external });
  };

  [...graph.nodes].sort((left, right) => compareText(left.id, right.id)).forEach((reference) => add(reference, false));
  [...graph.external_stubs].sort((left, right) => compareText(left.id, right.id)).forEach((reference) => add(reference, true));

  const edges: Array<TaskDependencyMapEdge & { id: string }> = [];
  const edgeKeys = new Set<string>();
  [...graph.edges]
    .sort((left, right) => compareText(left.from_task_id, right.from_task_id) || compareText(left.to_task_id, right.to_task_id))
    .forEach((edge) => {
      const id = `${edge.from_task_id}→${edge.to_task_id}`;
      if (edges.length >= MAXIMUM_RENDERED_EDGES || edgeKeys.has(id) || !known.has(edge.from_task_id) || !known.has(edge.to_task_id)) return;
      edgeKeys.add(id);
      edges.push({ ...edge, id });
    });

  return { nodes: [...known.values()], edges };
}

/** A pure, stable left-to-right dependency layout suitable for both renderers. */
export function layoutTaskDependencyMap(graph: TaskDependencyMapGraph): TaskDependencyMapLayout {
  const visible = visibleGraph(graph);
  const nodes = [...visible.nodes].sort((left, right) => compareText(left.id, right.id));
  const incoming = new Map(nodes.map((node) => [node.id, new Set<string>()]));
  const outgoing = new Map(nodes.map((node) => [node.id, new Set<string>()]));

  for (const edge of visible.edges) {
    if (edge.from_task_id === edge.to_task_id) continue;
    incoming.get(edge.to_task_id)?.add(edge.from_task_id);
    outgoing.get(edge.from_task_id)?.add(edge.to_task_id);
  }

  const remaining = new Map(nodes.map((node) => [node.id, incoming.get(node.id)?.size ?? 0]));
  const layers = new Map<string, number>();
  const pending = nodes.filter((node) => remaining.get(node.id) === 0).map((node) => node.id).sort(compareText);

  while (pending.length) {
    const id = pending.shift()!;
    const predecessors = incoming.get(id) ?? new Set<string>();
    layers.set(id, Math.max(0, ...[...predecessors].map((predecessor) => (layers.get(predecessor) ?? -1) + 1)));
    for (const successor of [...(outgoing.get(id) ?? [])].sort(compareText)) {
      const degree = (remaining.get(successor) ?? 1) - 1;
      remaining.set(successor, degree);
      if (degree === 0) pending.push(successor);
    }
    pending.sort(compareText);
  }

  // Canonical task dependencies are acyclic, but preserve a deterministic,
  // useful view rather than failing open if a hostile or stale projection has a cycle.
  for (const node of nodes) {
    if (layers.has(node.id)) continue;
    const predecessorLayers = [...(incoming.get(node.id) ?? [])]
      .map((predecessor) => layers.get(predecessor))
      .filter((layer): layer is number => layer !== undefined);
    layers.set(node.id, predecessorLayers.length ? Math.max(...predecessorLayers) + 1 : 0);
  }

  const byLayer = new Map<number, MapNode[]>();
  for (const node of nodes) {
    const layer = layers.get(node.id) ?? 0;
    const group = byLayer.get(layer) ?? [];
    group.push(node);
    byLayer.set(layer, group);
  }

  const layered = [...byLayer.entries()].sort(([left], [right]) => left - right);
  const layoutNodes: TaskDependencyMapLayoutNode[] = [];
  let tallestLayer = 0;
  for (const [layer, group] of layered) {
    group.sort((left, right) => compareText(left.id, right.id));
    tallestLayer = Math.max(tallestLayer, group.length);
    group.forEach((node, row) => layoutNodes.push({ ...node, layer, x: MAP_PADDING + layer * (NODE_WIDTH + LAYER_GAP), y: MAP_PADDING + row * (NODE_HEIGHT + ROW_GAP) }));
  }

  return {
    nodes: layoutNodes,
    edges: visible.edges,
    width: Math.max(1, layered.length) * (NODE_WIDTH + LAYER_GAP) - LAYER_GAP + MAP_PADDING * 2,
    height: Math.max(1, tallestLayer) * (NODE_HEIGHT + ROW_GAP) - ROW_GAP + MAP_PADDING * 2,
    omitted_nodes: Math.max(0, graph.node_count + graph.external_stub_count - layoutNodes.length),
    omitted_edges: Math.max(0, graph.edge_count - visible.edges.length),
  };
}

type TaskMapNodeData = {
  task: TaskDependencyMapLayoutNode;
};

type FlowRuntime = Pick<typeof import("@xyflow/react"), "Background" | "Controls" | "MarkerType" | "ReactFlow">;

function FlowTaskNode({ data, selected }: NodeProps<Node<TaskMapNodeData>>) {
  const { task } = data;
  return (
    <>
      <Handle isConnectable={false} position={Position.Left} style={{ opacity: 0, pointerEvents: "none" }} type="target" />
      <button
        aria-label={`${task.title}, ${task.external ? "cross-project reference" : "Task"}, ${stageLabel(task.workflow_stage)}${task.blocked ? ", blocked" : ""}`}
        aria-pressed={selected}
        className="nodrag nopan"
        disabled={task.external}
        style={{
          background: task.external ? "#173b39" : "#12342c",
          border: `1px solid ${selected ? "#75d7a4" : task.blocked ? "#e5a24b" : "#326654"}`,
          borderRadius: 8,
          color: "#f4eddc",
          cursor: task.external ? "default" : "pointer",
          display: "block",
          font: "inherit",
          minHeight: NODE_HEIGHT,
          padding: "9px 11px",
          textAlign: "left",
          width: NODE_WIDTH,
        }}
        type="button"
      >
        <span style={{ display: "block", fontSize: 13, fontWeight: 650, lineHeight: 1.25, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{task.title}</span>
        <span style={{ color: "#b8cbbd", display: "block", fontSize: 11, lineHeight: 1.35, marginTop: 5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{task.external ? `${task.project_name} · ` : ""}{stageLabel(task.workflow_stage)}{task.blocked ? " · blocked" : ""}</span>
      </button>
      <Handle isConnectable={false} position={Position.Right} style={{ opacity: 0, pointerEvents: "none" }} type="source" />
    </>
  );
}

const nodeTypes = { task: FlowTaskNode };

function mapSummary(graph: TaskDependencyMapGraph, layout: TaskDependencyMapLayout) {
  const projectNodes = layout.nodes.filter((node) => !node.external).length;
  const externalNodes = layout.nodes.length - projectNodes;
  const details = [`${projectNodes} of ${graph.node_total} project Tasks`, `${externalNodes} of ${graph.external_stub_total} cross-project references`, `${layout.edges.length} of ${graph.edge_total} dependencies`];
  if (graph.nodes_truncated || graph.external_stubs_truncated || graph.edges_truncated || layout.omitted_nodes || layout.omitted_edges) details.push("some items are not shown");
  return details.join(" · ");
}

function useNarrowPresentation(enabled: boolean) {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    if (!enabled || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(max-width: 767px)");
    const update = () => setNarrow(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, [enabled]);
  return narrow;
}

function statusMessage(state: "loading" | "failed", failureMessage?: string) {
  return state === "loading" ? "Loading the dependency map…" : failureMessage ?? "The interactive dependency map is unavailable. Showing the read-only overview instead.";
}

export function TaskDependencyMapStatus({ state, failureMessage }: { state: "loading" | "failed"; failureMessage?: string }) {
  return <p aria-live="polite" role="status">{statusMessage(state, failureMessage)}</p>;
}

function MapDisclosure({ graph, layout }: { graph: TaskDependencyMapGraph; layout: TaskDependencyMapLayout }) {
  return <p aria-live="polite" style={{ color: "#b8cbbd", fontSize: 13, margin: "0 0 10px" }}>{mapSummary(graph, layout)}</p>;
}

// React Flow's packaged stylesheet is intentionally not imported globally.
// These are only the positioning rules this bounded, custom-node map needs.
function TaskDependencyMapStyles() {
  return <style>{`
    .mentat-task-dependency-map__flow { direction: ltr; }
    .mentat-task-dependency-map__flow .react-flow__container { height: 100%; inset: 0; position: absolute; width: 100%; }
    .mentat-task-dependency-map__flow .react-flow__background { pointer-events: none; z-index: -1; }
    .mentat-task-dependency-map__flow .react-flow__pane { touch-action: none; z-index: 1; }
    .mentat-task-dependency-map__flow .react-flow__viewport { pointer-events: none; transform-origin: 0 0; z-index: 2; }
    .mentat-task-dependency-map__flow .react-flow__renderer { height: 100%; width: 100%; z-index: 4; }
    .mentat-task-dependency-map__flow .react-flow__nodes { pointer-events: none; transform-origin: 0 0; }
    .mentat-task-dependency-map__flow .react-flow__node { box-sizing: border-box; pointer-events: all; position: absolute; transform-origin: 0 0; }
    .mentat-task-dependency-map__flow .react-flow__edges { height: 100%; pointer-events: none; position: absolute; width: 100%; }
    .mentat-task-dependency-map__flow .react-flow__edges svg { overflow: visible; position: absolute; }
    .mentat-task-dependency-map__flow .react-flow__edge-path { fill: none; }
    .mentat-task-dependency-map__flow .react-flow__panel { margin: 12px; position: absolute; z-index: 5; }
    .mentat-task-dependency-map__flow .react-flow__panel.bottom { bottom: 0; }
    .mentat-task-dependency-map__flow .react-flow__panel.left { left: 0; }
    .mentat-task-dependency-map__flow .react-flow__controls { background: #12342c; border: 1px solid #326654; display: grid; }
    .mentat-task-dependency-map__flow .react-flow__controls button { background: transparent; border: 0; color: #f4eddc; height: 28px; width: 28px; }
    .mentat-task-dependency-map__flow .react-flow__controls button + button { border-top: 1px solid #326654; }
  `}</style>;
}

/** Source-owned fallback: no third-party canvas or graph runtime is required. */
export function TaskDependencyMapFallback({ graph, selectedTaskId, onSelectedTaskIdChange, failureMessage }: Pick<TaskDependencyMapProps, "graph" | "selectedTaskId" | "onSelectedTaskIdChange" | "failureMessage">) {
  const layout = useMemo(() => layoutTaskDependencyMap(graph), [graph]);
  const positions = useMemo(() => new Map(layout.nodes.map((node) => [node.id, node])), [layout.nodes]);
  const markerId = `task-dependency-arrow-${useId().replace(/:/gu, "")}`;
  return (
    <section aria-label="Task dependency overview">
      {failureMessage ? <TaskDependencyMapStatus failureMessage={failureMessage} state="failed" /> : null}
      <MapDisclosure graph={graph} layout={layout} />
      {!layout.nodes.length ? <p role="status">No dependency map is available for this Project.</p> : (
        <div style={{ maxWidth: "100%", overflowX: "auto" }}>
          <style>{`.mentat-task-dependency-map__fallback-node:focus-visible rect { stroke: #f4eddc; stroke-width: 3px; }`}</style>
          <svg aria-label="Read-only task dependency map" height={layout.height} role="group" style={{ display: "block", minWidth: layout.width }} viewBox={`0 0 ${layout.width} ${layout.height}`} width={layout.width}>
            <defs><marker id={markerId} markerHeight="6" markerWidth="6" orient="auto" refX="5" refY="3"><path d="M0,0 L0,6 L6,3 z" fill="#739b88" /></marker></defs>
            {layout.edges.map((edge) => {
              const from = positions.get(edge.from_task_id);
              const to = positions.get(edge.to_task_id);
              if (!from || !to) return null;
              const startX = from.x + NODE_WIDTH;
              const startY = from.y + NODE_HEIGHT / 2;
              const endX = to.x;
              const endY = to.y + NODE_HEIGHT / 2;
              const middleX = startX + (endX - startX) / 2;
              return <path d={`M ${startX} ${startY} C ${middleX} ${startY}, ${middleX} ${endY}, ${endX} ${endY}`} fill="none" key={edge.id} markerEnd={`url(#${markerId})`} stroke="#739b88" strokeWidth="1.5" />;
            })}
            {layout.nodes.map((node) => <g aria-label={`${node.title}, ${node.external ? "cross-project reference" : "Task"}, ${stageLabel(node.workflow_stage)}${node.blocked ? ", blocked" : ""}`} aria-pressed={node.external ? undefined : selectedTaskId === node.id} className={node.external ? undefined : "mentat-task-dependency-map__fallback-node"} fill={node.external ? "#173b39" : "#12342c"} key={node.id} onClick={() => { if (!node.external) onSelectedTaskIdChange(node.id); }} onKeyDown={(event) => { if (!node.external && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onSelectedTaskIdChange(node.id); } }} role={node.external ? "img" : "button"} style={{ cursor: node.external ? "default" : "pointer" }} tabIndex={node.external ? undefined : 0}>
              <rect height={NODE_HEIGHT} rx="8" stroke={selectedTaskId === node.id ? "#75d7a4" : node.blocked ? "#e5a24b" : "#326654"} width={NODE_WIDTH} x={node.x} y={node.y} />
              <text fill="#f4eddc" fontSize="13" fontWeight="650" x={node.x + 11} y={node.y + 25}>{node.title.length > 25 ? `${node.title.slice(0, 24)}…` : node.title}</text>
              <text fill="#b8cbbd" fontSize="11" x={node.x + 11} y={node.y + 47}>{`${node.external ? `${node.project_name} · ` : ""}${stageLabel(node.workflow_stage)}${node.blocked ? " · blocked" : ""}`.slice(0, 34)}</text>
            </g>)}
          </svg>
        </div>
      )}
    </section>
  );
}

export type TaskDependencyMapProps = {
  graph: TaskDependencyMapGraph;
  selectedTaskId: string | null;
  onSelectedTaskIdChange: (taskId: string) => void;
  /** Use the source-owned overview for narrow or explicitly non-map presentations. */
  presentation?: "map" | "fallback";
  /** Lets the dynamic-import boundary surface a safe failure without replacing the semantic editor. */
  loadState?: "loading" | "ready" | "failed";
  failureMessage?: string;
};

/**
 * Interactive desktop map. Load this component through a client-only dynamic
 * import; its fallback remains available above when the package cannot load.
 */
export default function TaskDependencyMap({ graph, selectedTaskId, onSelectedTaskIdChange, presentation = "map", loadState = "ready", failureMessage }: TaskDependencyMapProps) {
  const layout = useMemo(() => layoutTaskDependencyMap(graph), [graph]);
  const narrow = useNarrowPresentation(presentation === "map" && loadState === "ready");
  const [flowRuntime, setFlowRuntime] = useState<FlowRuntime | null>(null);
  const [runtimeFailed, setRuntimeFailed] = useState(false);
  useEffect(() => {
    if (presentation !== "map" || loadState !== "ready" || !layout.nodes.length) return;
    let cancelled = false;
    void import("@xyflow/react").then((module) => {
      if (!cancelled) setFlowRuntime(module);
    }).catch(() => {
      if (!cancelled) setRuntimeFailed(true);
    });
    return () => { cancelled = true; };
  }, [layout.nodes.length, loadState, presentation]);
  const nodes = useMemo<Array<Node<TaskMapNodeData>>>(() => layout.nodes.map((task) => ({ data: { task }, draggable: false, focusable: false, id: task.id, position: { x: task.x, y: task.y }, selectable: false, selected: task.id === selectedTaskId, sourcePosition: "right" as Position, targetPosition: "left" as Position, type: "task" })), [layout.nodes, selectedTaskId]);
  const edges = useMemo<Array<Edge>>(() => layout.edges.map((edge) => ({ id: edge.id, markerEnd: flowRuntime ? { type: flowRuntime.MarkerType.ArrowClosed, color: "#739b88" } : undefined, source: edge.from_task_id, style: { stroke: "#739b88", strokeWidth: 1.5 }, target: edge.to_task_id, type: "smoothstep" })), [flowRuntime, layout.edges]);
  const unavailableMessage = failureMessage ?? "The interactive dependency map is unavailable. Showing the read-only overview instead.";

  if (loadState === "loading") return <TaskDependencyMapStatus state="loading" />;
  if (loadState === "failed") return <TaskDependencyMapFallback failureMessage={unavailableMessage} graph={graph} onSelectedTaskIdChange={onSelectedTaskIdChange} selectedTaskId={selectedTaskId} />;
  if (presentation === "fallback" || narrow) return <TaskDependencyMapFallback graph={graph} onSelectedTaskIdChange={onSelectedTaskIdChange} selectedTaskId={selectedTaskId} />;
  if (!nodes.length) return <TaskDependencyMapFallback graph={graph} onSelectedTaskIdChange={onSelectedTaskIdChange} selectedTaskId={selectedTaskId} />;
  if (runtimeFailed) return <TaskDependencyMapFallback failureMessage={unavailableMessage} graph={graph} onSelectedTaskIdChange={onSelectedTaskIdChange} selectedTaskId={selectedTaskId} />;
  if (!flowRuntime) return <TaskDependencyMapStatus state="loading" />;

  const Flow = flowRuntime.ReactFlow;
  const Background = flowRuntime.Background;
  const Controls = flowRuntime.Controls;

  return (
    <section aria-label="Interactive task dependency map">
      <MapDisclosure graph={graph} layout={layout} />
      <div style={{ background: "#0d241e", border: "1px solid #326654", borderRadius: 10, height: 520, overflow: "hidden", position: "relative", width: "100%" }}>
        <Flow
          aria-label="Interactive task dependency map"
          className="mentat-task-dependency-map__flow"
          deleteKeyCode={null}
          edges={edges}
          edgesFocusable={false}
          edgesReconnectable={false}
          elementsSelectable={false}
          fitView
          fitViewOptions={{ maxZoom: 1, padding: 0.18 }}
          maxZoom={1.5}
          minZoom={0.25}
          nodes={nodes}
          nodesConnectable={false}
          nodesDraggable={false}
          nodesFocusable={false}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => { if (!node.data.task.external) onSelectedTaskIdChange(node.id); }}
          onlyRenderVisibleElements
          panOnDrag
          proOptions={{ hideAttribution: true }}
          style={{ background: "#0d241e" }}
        >
          <Background color="#23493d" gap={20} size={1} />
          <Controls aria-label="Dependency map controls" showInteractive={false} style={{ boxShadow: "none" }} />
        </Flow>
        <TaskDependencyMapStyles />
      </div>
    </section>
  );
}
