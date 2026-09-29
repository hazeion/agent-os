/** Owner-visible lead selection. A selected lead has no execution authority. */
export type LeadChoice = { id: string; name: string; context_bound: boolean; selection_token: string };
export type ProjectLead = { project_id: string; project_revision: number; revision: number; id: string | null; agent_id: string | null; agent_name: string | null; status: "unassigned" | "unready" | "stale" | "context_bound"; reasons: string[]; proposal_available: false; choices: LeadChoice[]; clear_token: string };
export type LeadOperation = "project" | "select";
export type LeadRequest = { project_id: string } | { project_id: string; agent_id: string | null; expected_project_revision: number; expected_lead_revision: number; selection_token: string };
export class ProjectLeadContractError extends Error { constructor() { super("project_lead_invalid"); } }
const PROJECT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/u;
const AGENT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u;
const ROLE = /^lead_role_[0-9a-f]{32}$/u;
const TOKEN = /^[0-9a-f]{64}$/u;
const REASONS = new Set(["project_inactive", "agent_changed", "context_grant_needed", "context_changed", "grant_changed"]);
function fail(): never { throw new ProjectLeadContractError(); }
function object(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function exact(value: unknown, fields: string): asserts value is Record<string, unknown> { if (!object(value) || Object.keys(value).sort().join(",") !== fields.split(",").sort().join(",")) fail(); }
function integer(value: unknown, low: number, high: number): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= low && value <= high; }
export function projectLeadRequest(operation: LeadOperation, value: unknown): Record<string, unknown> {
  if (operation !== "project" && operation !== "select") fail();
  exact(value, operation === "project" ? "project_id" : "project_id,agent_id,expected_project_revision,expected_lead_revision,selection_token");
  if (typeof value.project_id !== "string" || !PROJECT.test(value.project_id)) fail();
  if (operation === "select" && ((value.agent_id !== null && (typeof value.agent_id !== "string" || !AGENT.test(value.agent_id)))
    || !integer(value.expected_project_revision, 1, Number.MAX_SAFE_INTEGER)
    || !integer(value.expected_lead_revision, 0, 32)
    || typeof value.selection_token !== "string" || !TOKEN.test(value.selection_token))) fail();
  return value;
}
export function projectLeadResult(value: unknown, request: Record<string, unknown>): ProjectLead {
  exact(value, "project_id,project_revision,revision,id,agent_id,agent_name,status,reasons,proposal_available,choices,clear_token");
  if (value.project_id !== request.project_id || !integer(value.project_revision, 1, Number.MAX_SAFE_INTEGER)
    || !integer(value.revision, 0, 32) || (value.id !== null && (typeof value.id !== "string" || !ROLE.test(value.id)))
    || (value.agent_id !== null && (typeof value.agent_id !== "string" || !AGENT.test(value.agent_id)))
    || (value.agent_name !== null && (typeof value.agent_name !== "string" || [...value.agent_name].length > 120))
    || !["unassigned", "unready", "stale", "context_bound"].includes(String(value.status))
    || value.proposal_available !== false || typeof value.clear_token !== "string" || !TOKEN.test(value.clear_token)
    || !Array.isArray(value.reasons) || value.reasons.length > 5 || value.reasons.some((item) => !REASONS.has(item))) fail();
  if (value.status === "unassigned" ? value.agent_id !== null || value.reasons.length !== 0 : value.agent_id === null) fail();
  if (value.status === "context_bound" && value.reasons.length !== 0
    || value.status === "unready" && (value.reasons.length !== 1 || value.reasons[0] !== "context_grant_needed")
    || value.status === "stale" && value.reasons.length === 0) fail();
  if (value.revision === 0 && value.id !== null || value.revision > 0 && value.id === null) fail();
  if (!Array.isArray(value.choices) || value.choices.length > 128) fail();
  for (const item of value.choices) {
    exact(item, "id,name,context_bound,selection_token");
    if (typeof item.id !== "string" || !AGENT.test(item.id) || typeof item.name !== "string"
      || [...item.name].length < 1 || [...item.name].length > 120 || typeof item.context_bound !== "boolean"
      || typeof item.selection_token !== "string" || !TOKEN.test(item.selection_token)) fail();
  }
  if (new Set(value.choices.map((item) => item.id)).size !== value.choices.length) fail();
  if ("expected_lead_revision" in request && (value.revision !== Number(request.expected_lead_revision) + 1 || value.agent_id !== request.agent_id)) fail();
  return value as ProjectLead;
}
