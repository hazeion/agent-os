export class ProjectPlanContractError extends Error { constructor() { super("project_plan_contract_invalid"); } }

export type PlanDraftNode = { task_id: string; expected_task_revision: number; agent_id: string; input_version_id: string; after: string[]; segment: number; max_attempts: number; max_wall_seconds: number; max_work_units: number };
export type PlanSavedNode = Omit<PlanDraftNode, "expected_task_revision"> & { task_revision: number };
export type PlanVersionNode = PlanSavedNode & { task_state: "current" | "changed" | "unavailable"; task_title: string | null; agent_state: "current" | "changed" | "unavailable"; agent_name: string | null };
export type PlanProject = { project: { id: string; name: string; revision: number; status: "active" | "paused" | "archived" }; plan_revision: number; current: null | { title: string; nodes: PlanSavedNode[] }; versions: Array<{ id: string; revision: number; title: string; node_count: number; created_at: number }>; stale_reasons: Array<"project_inactive" | "project_changed" | "task_changed" | "dependency_mismatch" | "agent_changed" | "input_changed" | "grant_changed">; dependency_comparison: { missing_from_plan: PlanEdge[]; additional_in_plan: PlanEdge[]; missing_count: number; additional_count: number; truncated: boolean }; execution_available: false };
export type PlanEdge = { task_id: string; prerequisite_id: string };
export type PlanVersion = { id: string; project_id: string; revision: number; project_revision: number; title: string; nodes: PlanVersionNode[]; created_at: number; current: boolean; status: "unapproved" };
export type PlanPublished = { id: string; revision: number; project_id: string; status: "unapproved" };
export type ProjectPlanOperation = "project" | "version" | "publish";
export type ProjectPlanResults = { project: PlanProject; version: PlanVersion; publish: PlanPublished };
export const PROJECT_PLAN_READS = new Set<ProjectPlanOperation>(["project", "version"]);
export const PROJECT_PLAN_JSON_LIMIT = 32 * 1024;

const PROJECT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const AGENT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u;
const INPUT = /^task_input_[0-9a-f]{32}$/u;
const VERSION = /^plan_version_[0-9a-f]{32}$/u;
const STALE = new Set(["project_inactive", "project_changed", "task_changed", "dependency_mismatch", "agent_changed", "input_changed", "grant_changed"]);
const NODE_KEYS = "after,agent_id,input_version_id,max_attempts,max_wall_seconds,max_work_units,segment,task_id,task_revision";
const REQUEST_NODE_KEYS = "after,agent_id,expected_task_revision,input_version_id,max_attempts,max_wall_seconds,max_work_units,segment,task_id";
const VERSION_NODE_KEYS = "after,agent_id,agent_name,agent_state,input_version_id,max_attempts,max_wall_seconds,max_work_units,segment,task_id,task_revision,task_state,task_title";
function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function keys(value: Record<string, unknown>, expected: string): boolean { return Object.keys(value).sort().join(",") === expected; }
function integer(value: unknown, minimum: number, maximum: number): value is number { return Number.isSafeInteger(value) && (value as number) >= minimum && (value as number) <= maximum; }
function title(value: unknown): value is string { return typeof value === "string" && value.trim() === value && !!value && !/\p{C}/u.test(value) && new TextEncoder().encode(value).length <= 120; }

function nodes(value: unknown, saved: boolean): PlanDraftNode[] | PlanSavedNode[] {
  if (!Array.isArray(value) || !integer(value.length, 1, 32)) throw new ProjectPlanContractError();
  const seen = new Set<string>(), segments = new Set<number>(); const positions = new Map<string, number>();
  const result: Array<PlanDraftNode | PlanSavedNode> = [];
  for (const raw of value) {
    if (!record(raw) || !keys(raw, saved ? NODE_KEYS : REQUEST_NODE_KEYS)
      || typeof raw.task_id !== "string" || !TASK.test(raw.task_id) || seen.has(raw.task_id)
      || typeof raw.agent_id !== "string" || !AGENT.test(raw.agent_id)
      || typeof raw.input_version_id !== "string" || !INPUT.test(raw.input_version_id)
      || !integer(raw[saved ? "task_revision" : "expected_task_revision"], 1, Number.MAX_SAFE_INTEGER)
      || !integer(raw.segment, 0, 31) || result.length && raw.segment < result[result.length - 1].segment
      || !integer(raw.max_attempts, 1, 3) || !integer(raw.max_wall_seconds, 60, 86400)
      || !integer(raw.max_work_units, 1, 1000) || !Array.isArray(raw.after) || raw.after.length > 31
      || raw.after.some((id: unknown) => typeof id !== "string" || !positions.has(id) || positions.get(id)! > (raw.segment as number))
      || new Set(raw.after).size !== raw.after.length) throw new ProjectPlanContractError();
    seen.add(raw.task_id); segments.add(raw.segment); positions.set(raw.task_id, raw.segment);
    result.push(structuredClone(raw) as PlanDraftNode | PlanSavedNode);
  }
  if (result[0].segment !== 0 || segments.size !== Math.max(...segments) + 1) throw new ProjectPlanContractError();
  return result as PlanDraftNode[] | PlanSavedNode[];
}

function comparison(value: unknown): PlanProject["dependency_comparison"] {
  if (!record(value) || !keys(value, "additional_count,additional_in_plan,missing_count,missing_from_plan,truncated")
    || !integer(value.missing_count, 0, 3200) || !integer(value.additional_count, 0, 992)
    || typeof value.truncated !== "boolean" || !Array.isArray(value.missing_from_plan) || !Array.isArray(value.additional_in_plan)
    || value.missing_from_plan.length > 128 || value.additional_in_plan.length > 128
    || value.missing_from_plan.length !== Math.min(value.missing_count, 128)
    || value.additional_in_plan.length !== Math.min(value.additional_count, 128)
    || value.truncated !== (value.missing_count > 128 || value.additional_count > 128)) throw new ProjectPlanContractError();
  for (const edge of [...value.missing_from_plan, ...value.additional_in_plan]) {
    if (!record(edge) || !keys(edge, "prerequisite_id,task_id") || typeof edge.task_id !== "string" || !TASK.test(edge.task_id)
      || typeof edge.prerequisite_id !== "string" || !TASK.test(edge.prerequisite_id)) throw new ProjectPlanContractError();
  }
  return structuredClone(value) as PlanProject["dependency_comparison"];
}

export function projectPlanRequest(operation: ProjectPlanOperation, input: unknown): Record<string, unknown> {
  if (!record(input)) throw new ProjectPlanContractError();
  const fields = { project: "project_id", version: "project_id,version_id", publish: "expected_plan_revision,expected_project_revision,nodes,project_id,title" } as const;
  if (!keys(input, fields[operation]) || typeof input.project_id !== "string" || !PROJECT.test(input.project_id)) throw new ProjectPlanContractError();
  if (operation === "version" && (typeof input.version_id !== "string" || !VERSION.test(input.version_id))) throw new ProjectPlanContractError();
  if (operation === "publish") {
    if (!integer(input.expected_plan_revision, 0, 32) || !integer(input.expected_project_revision, 1, Number.MAX_SAFE_INTEGER)
      || !title(input.title)) throw new ProjectPlanContractError();
    nodes(input.nodes, false);
    if (new TextEncoder().encode(JSON.stringify(input)).length > PROJECT_PLAN_JSON_LIMIT) throw new ProjectPlanContractError();
  }
  return structuredClone(input);
}

export function projectPlanResult<K extends ProjectPlanOperation>(operation: K, value: unknown, request: Record<string, unknown>): ProjectPlanResults[K] {
  if (operation === "project") {
    if (!record(value) || !keys(value, "current,dependency_comparison,execution_available,plan_revision,project,stale_reasons,versions")
      || !record(value.project) || !keys(value.project, "id,name,revision,status") || value.project.id !== request.project_id
      || !title(value.project.name) || !integer(value.project.revision, 1, Number.MAX_SAFE_INTEGER)
      || !["active", "paused", "archived"].includes(String(value.project.status))
      || !integer(value.plan_revision, 0, 32) || value.execution_available !== false
      || !Array.isArray(value.versions) || value.versions.length !== value.plan_revision
      || !Array.isArray(value.stale_reasons) || value.stale_reasons.length > 7
      || value.stale_reasons.some((reason: unknown) => typeof reason !== "string" || !STALE.has(reason))
      || new Set(value.stale_reasons).size !== value.stale_reasons.length) throw new ProjectPlanContractError();
    comparison(value.dependency_comparison);
    for (const [index, entry] of value.versions.entries()) {
      if (!record(entry) || !keys(entry, "created_at,id,node_count,revision,title") || typeof entry.id !== "string" || !VERSION.test(entry.id)
        || !integer(entry.revision, 1, 32) || entry.revision !== value.plan_revision - index
        || !title(entry.title) || !integer(entry.node_count, 1, 32)
        || typeof entry.created_at !== "number" || !Number.isFinite(entry.created_at) || entry.created_at <= 0) throw new ProjectPlanContractError();
    }
    if (value.plan_revision === 0 && value.current !== null || value.plan_revision > 0 && (!record(value.current)
      || !keys(value.current, "nodes,title") || !title(value.current.title))) throw new ProjectPlanContractError();
    if (value.current !== null) {
      nodes((value.current as Record<string, unknown>).nodes, true);
      if ((value.current as Record<string, unknown>).title !== (value.versions as Array<{ title: string }>)[0].title) throw new ProjectPlanContractError();
    }
  } else if (operation === "version") {
    if (!record(value) || !keys(value, "created_at,current,id,nodes,project_id,project_revision,revision,status,title")
      || value.id !== request.version_id || value.project_id !== request.project_id
      || !integer(value.revision, 1, 32) || !integer(value.project_revision, 1, Number.MAX_SAFE_INTEGER)
      || !title(value.title) || typeof value.created_at !== "number" || !Number.isFinite(value.created_at) || value.created_at <= 0
      || typeof value.current !== "boolean" || value.status !== "unapproved") throw new ProjectPlanContractError();
    if (!Array.isArray(value.nodes) || value.nodes.length < 1 || value.nodes.length > 32) throw new ProjectPlanContractError();
    const baseNodes = value.nodes.map((raw) => {
      if (!record(raw) || !keys(raw, VERSION_NODE_KEYS)
        || !["current", "changed", "unavailable"].includes(String(raw.task_state))
        || !["current", "changed", "unavailable"].includes(String(raw.agent_state))
        || !(raw.task_title === null || typeof raw.task_title === "string" && !!raw.task_title && raw.task_title.trim() === raw.task_title && !/\p{C}/u.test(raw.task_title) && new TextEncoder().encode(raw.task_title).length <= 160)
        || !(raw.agent_name === null || typeof raw.agent_name === "string" && !!raw.agent_name && raw.agent_name.trim() === raw.agent_name && !/\p{C}/u.test(raw.agent_name) && new TextEncoder().encode(raw.agent_name).length <= 120)
        || (raw.task_state === "current") !== (raw.task_title !== null)
        || (raw.agent_state === "current") !== (raw.agent_name !== null)) throw new ProjectPlanContractError();
      const base = { ...raw };
      delete base.task_state; delete base.task_title; delete base.agent_state; delete base.agent_name;
      return base;
    });
    nodes(baseNodes, true);
  } else if (operation === "publish") {
    if (!record(value) || !keys(value, "id,project_id,revision,status") || value.project_id !== request.project_id
      || typeof value.id !== "string" || !VERSION.test(value.id) || !integer(value.revision, 1, 32)
      || value.revision !== (request.expected_plan_revision as number) + 1 || value.status !== "unapproved") throw new ProjectPlanContractError();
  } else throw new ProjectPlanContractError();
  return structuredClone(value) as ProjectPlanResults[K];
}
