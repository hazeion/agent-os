import assert from "node:assert/strict";
import test from "node:test";

// @ts-expect-error This runtime-only MJS helper intentionally has no declaration file.
import { runBoundedProcess } from "../scripts/lighthouse-process.mjs";

function processExists(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ESRCH";
  }
}

async function waitForExit(pid: number): Promise<void> {
  const deadline = Date.now() + 3000;
  while (processExists(pid) && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  assert.equal(processExists(pid), false, `process ${pid} survived timeout cleanup`);
}

test("bounded process timeout terminates the child process tree", async () => {
  const tracked = new Set<number>();
  const childProgram = [
    'const { spawn } = require("node:child_process");',
    'const descendant = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], { stdio: "ignore" });',
    "console.log(descendant.pid);",
    "setInterval(() => {}, 1000);",
  ].join(" ");
  const result = await runBoundedProcess(
    process.execPath,
    ["-e", childProgram],
    {
      cwd: process.cwd(),
      env: { ...process.env },
      onClose: (child: { pid?: number }) => {
        if (child.pid) tracked.delete(child.pid);
      },
      onSpawn: (child: { pid?: number }) => {
        if (child.pid) tracked.add(child.pid);
      },
      // The full Node suite runs test files concurrently. Give the fixture
      // enough time to start and report its descendant before exercising the
      // timeout path; otherwise an empty stdout string is coerced to PID 0.
      timeoutMs: 2000,
    },
  );

  assert.equal(result.timedOut, true);
  assert.equal(result.signal === "SIGKILL" || process.platform === "win32", true);
  assert.equal(typeof result.pid, "number");
  const descendantPid = Number(result.stdout.trim());
  assert.equal(Number.isSafeInteger(descendantPid), true);
  assert.equal(descendantPid > 0, true);
  assert.deepEqual([...tracked], []);
  await waitForExit(result.pid);
  await waitForExit(descendantPid);
});
