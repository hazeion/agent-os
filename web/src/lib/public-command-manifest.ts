const MAXIMUM_RESPONSE_BYTES = 16_384;
const READ_TIMEOUT_MILLISECONDS = 5_000;

export type PublicCommandArgument = {
  name: "model" | "guidance";
  required: boolean;
  variadic?: true;
  description: string;
};

export type PublicCommandDefinition = {
  command: "/model" | "/new" | "/steer" | "/help";
  handler:
    | "agent_console.refresh_models"
    | "agent_console.new_session"
    | "agent_console.steer_active_run"
    | "agent_console.show_help";
  arguments: PublicCommandArgument[];
  description: string;
  safety: "read_only" | "local_state" | "remote_control";
};

export type PublicCommandManifest = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  source: "mentat";
  capabilities: {
    "commands.manifest.read": true;
    "commands.external_source": false;
    "commands.hermes_cli_passthrough": false;
  };
  commands: PublicCommandDefinition[];
};

export class PublicCommandManifestError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.code = code;
    this.name = "PublicCommandManifestError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: string): boolean {
  return Object.keys(value).sort().join(",") === expected;
}

function validFailure(value: unknown, status: string): boolean {
  return record(value)
    && exactKeys(value, "schema_version,status")
    && value.schema_version === 1
    && value.status === status;
}

const EXPECTED_COMMANDS = [
  {
    arguments: [{
      description: "Optional active-provider model to select for review.",
      name: "model",
      required: false,
    }],
    command: "/model",
    description: "Refresh current provider models",
    handler: "agent_console.refresh_models",
    safety: "read_only",
  },
  {
    arguments: [],
    command: "/new",
    description: "Start a new Hermes session",
    handler: "agent_console.new_session",
    safety: "local_state",
  },
  {
    arguments: [{
      description: "Text guidance for the active remote Hermes run.",
      name: "guidance",
      required: true,
      variadic: true,
    }],
    command: "/steer",
    description: "Guide the active remote Hermes run",
    handler: "agent_console.steer_active_run",
    safety: "remote_control",
  },
  {
    arguments: [],
    command: "/help",
    description: "Show dashboard commands",
    handler: "agent_console.show_help",
    safety: "read_only",
  },
] as const;

function validArgument(value: unknown, expected: (typeof EXPECTED_COMMANDS)[number]["arguments"][number]): boolean {
  if (!record(value)) return false;
  const expectedKeys = "variadic" in expected
    ? "description,name,required,variadic"
    : "description,name,required";
  if (!exactKeys(value, expectedKeys)) return false;
  return Object.entries(expected).every(([key, item]) => value[key] === item);
}

export function parseCommandManifest(value: unknown): PublicCommandManifest {
  if (!record(value) || !exactKeys(value, "capabilities,commands,runtime,schema_version,service,source,status")) {
    throw new PublicCommandManifestError("response_invalid");
  }
  const capabilities = value.capabilities;
  const commands = value.commands;
  if (
    value.schema_version !== 1
    || value.service !== "mentat-local-bridge"
    || value.runtime !== "python"
    || value.status !== "ready"
    || value.source !== "mentat"
    || !record(capabilities)
    || !exactKeys(capabilities, "commands.external_source,commands.hermes_cli_passthrough,commands.manifest.read")
    || capabilities["commands.manifest.read"] !== true
    || capabilities["commands.external_source"] !== false
    || capabilities["commands.hermes_cli_passthrough"] !== false
    || !Array.isArray(commands)
    || commands.length !== EXPECTED_COMMANDS.length
  ) throw new PublicCommandManifestError("response_invalid");
  for (const [index, expected] of EXPECTED_COMMANDS.entries()) {
    const command = commands[index];
    if (
      !record(command)
      || !exactKeys(command, "arguments,command,description,handler,safety")
      || command.command !== expected.command
      || command.handler !== expected.handler
      || command.description !== expected.description
      || command.safety !== expected.safety
      || !Array.isArray(command.arguments)
      || command.arguments.length !== expected.arguments.length
      || !command.arguments.every((argument, argumentIndex) => validArgument(argument, expected.arguments[argumentIndex]!))
    ) throw new PublicCommandManifestError("response_invalid");
  }
  return structuredClone(value) as PublicCommandManifest;
}

async function boundedJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_RESPONSE_BYTES)) {
    throw new PublicCommandManifestError("response_invalid");
  }
  if (!response.body) throw new PublicCommandManifestError("response_invalid");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      total += next.value.byteLength;
      if (total > MAXIMUM_RESPONSE_BYTES) {
        await reader.cancel();
        throw new PublicCommandManifestError("response_invalid");
      }
      chunks.push(next.value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
  } catch {
    throw new PublicCommandManifestError("response_invalid");
  }
}

export async function fetchCommandManifest(): Promise<PublicCommandManifest> {
  try {
    const response = await fetch("/api/agent-console/commands", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      redirect: "error",
      signal: AbortSignal.timeout(READ_TIMEOUT_MILLISECONDS),
    });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
      throw new PublicCommandManifestError("response_invalid");
    }
    const payload = await boundedJson(response);
    if (response.status === 200) return parseCommandManifest(payload);
    if (response.status === 503 && validFailure(payload, "unavailable")) {
      throw new PublicCommandManifestError("unavailable");
    }
    throw new PublicCommandManifestError("response_invalid");
  } catch (error) {
    if (error instanceof PublicCommandManifestError) throw error;
    throw new PublicCommandManifestError("unavailable");
  }
}
