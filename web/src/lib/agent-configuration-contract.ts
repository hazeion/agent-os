/** Public Agent configuration validation, without server transport or authority. */
export type PublicAgentConfiguration = {
  schema_version: 1;
  agent_id: string;
  runtime_type: string;
  state: "ready" | "read_only" | "unavailable";
  mutable: boolean;
  active_run: boolean;
  current: { provider: string | null; model: string | null; effort: "runtime_default" };
  providers: Array<{ id: string; name: string; current: boolean; models: string[] }>;
  efforts: [{ id: "runtime_default"; name: "Runtime default" }];
  explanation: string;
};

export type PublicAgentConfigurationPayload = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  configuration: PublicAgentConfiguration;
};

export type PublicAgentConfigurationPreview = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  action: "configure";
  agent_id: string;
  requires_confirmation: true;
  confirmation_id: string;
  current: { provider: string | null; model: string | null };
  target: { provider: string; provider_name: string; model: string; effort: "runtime_default" };
  message: string;
};

export type PublicAgentConfigurationResult = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  action: "configure";
  agent_id: string;
  configuration: PublicAgentConfiguration;
  message: string;
};

function opaqueId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(value);
}

function text(value: unknown, maximum: number): value is string {
  return typeof value === "string"
    && value.length > 0
    && [...value].length <= maximum
    && value.trim() === value
    && !value.includes("\0");
}

export function validAgentConfiguration(value: unknown): value is PublicAgentConfiguration {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const configuration = value as Record<string, unknown>;
  const current = configuration.current;
  const providers = configuration.providers;
  const efforts = configuration.efforts;
  return Object.keys(configuration).sort().join(",") === "active_run,agent_id,current,efforts,explanation,mutable,providers,runtime_type,schema_version,state"
    && configuration.schema_version === 1
    && opaqueId(configuration.agent_id)
    && typeof configuration.runtime_type === "string"
    && /^[a-z][a-z0-9_-]{0,31}$/u.test(configuration.runtime_type)
    && ["ready", "read_only", "unavailable"].includes(String(configuration.state))
    && typeof configuration.mutable === "boolean"
    && configuration.mutable === (configuration.state === "ready")
    && typeof configuration.active_run === "boolean"
    && !!current && typeof current === "object" && !Array.isArray(current)
    && Object.keys(current).sort().join(",") === "effort,model,provider"
    && ((current as Record<string, unknown>).provider === null || text((current as Record<string, unknown>).provider, 120))
    && ((current as Record<string, unknown>).model === null || text((current as Record<string, unknown>).model, 160))
    && (current as Record<string, unknown>).effort === "runtime_default"
    && Array.isArray(providers) && providers.length <= 32
    && providers.every((provider) => {
      if (!provider || typeof provider !== "object" || Array.isArray(provider)) return false;
      const row = provider as Record<string, unknown>;
      return Object.keys(row).sort().join(",") === "current,id,models,name"
        && text(row.id, 120) && text(row.name, 160)
        && typeof row.current === "boolean"
        && Array.isArray(row.models) && row.models.length <= 256
        && row.models.every((model) => text(model, 160))
        && new Set(row.models).size === row.models.length;
    })
    && new Set(providers.map((provider) => (provider as Record<string, unknown>).id)).size === providers.length
    && Array.isArray(efforts) && efforts.length === 1
    && !!efforts[0] && typeof efforts[0] === "object" && !Array.isArray(efforts[0])
    && Object.keys(efforts[0] as Record<string, unknown>).sort().join(",") === "id,name"
    && (efforts[0] as Record<string, unknown>).id === "runtime_default"
    && (efforts[0] as Record<string, unknown>).name === "Runtime default"
    && typeof configuration.explanation === "string"
    && configuration.explanation.length <= 300 && !configuration.explanation.includes("\0");
}

export function validAgentConfigurationPayload(value: unknown): value is PublicAgentConfigurationPayload {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  return Object.keys(payload).sort().join(",") === "configuration,runtime,schema_version,service,status"
    && payload.schema_version === 1 && payload.service === "mentat-local-bridge"
    && payload.runtime === "python" && payload.status === "ready"
    && validAgentConfiguration(payload.configuration);
}

export function validAgentConfigurationPreview(value: unknown): value is PublicAgentConfigurationPreview {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  const current = payload.current;
  const target = payload.target;
  return Object.keys(payload).sort().join(",") === "action,agent_id,confirmation_id,current,message,requires_confirmation,runtime,schema_version,service,status,target"
    && payload.schema_version === 1 && payload.service === "mentat-local-bridge"
    && payload.runtime === "python" && payload.status === "ready"
    && payload.action === "configure" && opaqueId(payload.agent_id)
    && payload.requires_confirmation === true && text(payload.confirmation_id, 80)
    && !!current && typeof current === "object" && !Array.isArray(current)
    && Object.keys(current).sort().join(",") === "model,provider"
    && ((current as Record<string, unknown>).provider === null || text((current as Record<string, unknown>).provider, 120))
    && ((current as Record<string, unknown>).model === null || text((current as Record<string, unknown>).model, 160))
    && !!target && typeof target === "object" && !Array.isArray(target)
    && Object.keys(target).sort().join(",") === "effort,model,provider,provider_name"
    && text((target as Record<string, unknown>).provider, 120)
    && text((target as Record<string, unknown>).provider_name, 160)
    && text((target as Record<string, unknown>).model, 160)
    && (target as Record<string, unknown>).effort === "runtime_default"
    && text(payload.message, 300);
}

export function validAgentConfigurationResult(value: unknown): value is PublicAgentConfigurationResult {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  return Object.keys(payload).sort().join(",") === "action,agent_id,configuration,message,runtime,schema_version,service,status"
    && payload.schema_version === 1 && payload.service === "mentat-local-bridge"
    && payload.runtime === "python" && payload.status === "ready"
    && payload.action === "configure" && opaqueId(payload.agent_id)
    && validAgentConfiguration(payload.configuration)
    && (payload.configuration as PublicAgentConfiguration).agent_id === payload.agent_id
    && text(payload.message, 300);
}
