export type AgentSetupAction = "check" | "preview" | "confirm";
export type SetupAgent = { id: string; name: string };
export type SetupState = "available" | "already_configured" | "hermes_missing" | "hermes_unconfigured" | "remote_selected" | "registry_full" | "unavailable";
type Envelope = { schema_version: 1; runtime: "python"; service: "mentat-local-bridge"; status: "ready" };
export type AgentSetupResult = Envelope & ({ state: SetupState; agent: SetupAgent | null } | { name: string; confirmation_id: string } | { agent: SetupAgent });
export const validSetupName = (value: unknown): value is string => typeof value === "string" && [...value].length >= 1 && [...value].length <= 120 && value.trim() === value && !/\p{C}/u.test(value);
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const keys = (value: Record<string, unknown>, expected: string) => Object.keys(value).sort().join(",") === expected;
export function validAgentSetupBody(action: AgentSetupAction, value: unknown): value is Record<string, unknown> {
  if (!record(value)) return false;
  if (action === "check") return keys(value, "");
  if (!validSetupName(value.name)) return false;
  if (action === "preview") return keys(value, "name");
  return keys(value, "confirmation_id,confirmed,name") && value.confirmed === true && typeof value.confirmation_id === "string" && /^[0-9a-f]{64}$/u.test(value.confirmation_id);
}
export function parseAgentSetupResult(action: AgentSetupAction, value: unknown, name?: unknown): AgentSetupResult {
  const invalid = () => { throw new Error("agent_setup_response_invalid"); };
  if (!record(value) || value.schema_version !== 1 || value.runtime !== "python" || value.service !== "mentat-local-bridge" || value.status !== "ready") return invalid();
  if (action === "preview") {
    if (!keys(value, "confirmation_id,name,runtime,schema_version,service,status") || !validSetupName(value.name) || value.name !== name || typeof value.confirmation_id !== "string" || !/^[0-9a-f]{64}$/u.test(value.confirmation_id)) return invalid();
  } else {
    const agent = value.agent;
    if (agent !== null && (!record(agent) || !keys(agent, "id,name") || typeof agent.id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(agent.id) || !validSetupName(agent.name))) return invalid();
    if (action === "check") {
      if (!keys(value, "agent,runtime,schema_version,service,state,status") || typeof value.state !== "string" || !["available", "already_configured", "hermes_missing", "hermes_unconfigured", "remote_selected", "registry_full", "unavailable"].includes(value.state) || (value.state === "already_configured") !== (agent !== null)) return invalid();
    } else if (!keys(value, "agent,runtime,schema_version,service,status") || !record(agent) || agent.name !== name) return invalid();
  }
  return structuredClone(value) as AgentSetupResult;
}
