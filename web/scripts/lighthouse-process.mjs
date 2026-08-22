import { spawn, spawnSync } from "node:child_process";

const MAX_CAPTURE_BYTES = 1024 * 1024;

function appendBounded(current, chunk) {
  const combined = current + chunk.toString("utf8");
  if (Buffer.byteLength(combined, "utf8") <= MAX_CAPTURE_BYTES) return combined;
  return combined.slice(-MAX_CAPTURE_BYTES);
}

function missingProcessError(error) {
  return error && typeof error === "object" && error.code === "ESRCH";
}

export function terminateProcessTree(child) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
  if (process.platform === "win32") {
    const result = spawnSync(
      "taskkill",
      ["/pid", String(child.pid), "/T", "/F"],
      {
        encoding: "utf8",
        shell: false,
        windowsHide: true,
      },
    );
    if (!result.error && result.status === 0) return;
    try {
      child.kill("SIGKILL");
    } catch (error) {
      if (!missingProcessError(error)) throw result.error || error;
    }
    return;
  }
  try {
    process.kill(-child.pid, "SIGKILL");
  } catch (error) {
    if (missingProcessError(error)) return;
    try {
      child.kill("SIGKILL");
    } catch (fallbackError) {
      if (!missingProcessError(fallbackError)) throw error;
    }
  }
}

export function runBoundedProcess(command, args, options) {
  const {
    cwd,
    env,
    onClose,
    onSpawn,
    timeoutMs,
  } = options;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1) {
    throw new Error("timeoutMs must be a positive safe integer");
  }

  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      detached: process.platform !== "win32",
      env,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    try {
      onSpawn?.(child);
    } catch (error) {
      terminateProcessTree(child);
      reject(error);
      return;
    }
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let settled = false;

    child.stdout.on("data", (chunk) => {
      stdout = appendBounded(stdout, chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr = appendBounded(stderr, chunk);
    });

    const timeout = setTimeout(() => {
      timedOut = true;
      try {
        terminateProcessTree(child);
      } catch (error) {
        if (!settled) {
          settled = true;
          reject(error);
        }
      }
    }, timeoutMs);
    timeout.unref();

    child.once("error", (error) => {
      clearTimeout(timeout);
      onClose?.(child);
      if (!settled) {
        settled = true;
        reject(error);
      }
    });
    child.once("close", (status, signal) => {
      clearTimeout(timeout);
      onClose?.(child);
      if (settled) return;
      settled = true;
      resolve({
        pid: child.pid,
        signal,
        status,
        stderr,
        stdout,
        timedOut,
      });
    });
  });
}
