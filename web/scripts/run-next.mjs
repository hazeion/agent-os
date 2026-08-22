import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const allowedCommands = new Set(["build", "dev"]);
const command = process.argv[2] ?? "";
if (!allowedCommands.has(command)) {
  throw new Error("run-next requires the fixed build or dev command");
}

const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const nextCli = resolve(projectRoot, "node_modules", "next", "dist", "bin", "next");
const result = spawnSync(
  process.execPath,
  [nextCli, command, ...process.argv.slice(3)],
  {
    cwd: projectRoot,
    env: {
      ...process.env,
      NEXT_TELEMETRY_DISABLED: "1",
      ...(command === "build" ? { MENTAT_STATIC_FOUNDATION: "1" } : {}),
    },
    shell: false,
    stdio: "inherit",
  },
);

if (result.error) throw result.error;
process.exit(result.status ?? 1);
