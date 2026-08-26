import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { killAll, launch as launchChrome } from "chrome-launcher";

import {
  runBoundedProcess,
  terminateProcessTree,
} from "./lighthouse-process.mjs";

const CATEGORY_IDS = ["performance", "accessibility", "best-practices", "seo"];
const RUNS_PER_MODE = 3;
const AUDIT_ATTEMPTS = 2;
const configuredMinimumPerformance = process.env.MENTAT_LIGHTHOUSE_MIN_PERFORMANCE ?? "100";
const minimumPerformanceScore = Number(configuredMinimumPerformance);
if (!Number.isInteger(minimumPerformanceScore) || minimumPerformanceScore < 95 || minimumPerformanceScore > 100) {
  throw new Error("MENTAT_LIGHTHOUSE_MIN_PERFORMANCE must be an integer between 95 and 100");
}
const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const lighthouseCli = resolve(projectRoot, "node_modules", "lighthouse", "cli", "index.js");
const chromeVersionFile = resolve(projectRoot, "..", ".chrome-for-testing-version");
const expectedChromeVersion = readFileSync(chromeVersionFile, "utf8").trim();
const baseUrl = new URL(
  process.env.MENTAT_WEB_BASE_URL || "http://127.0.0.1:8890",
);
const normalizedBaseHostname = baseUrl.hostname.toLowerCase().replace(/^\[|\]$/gu, "");

if (
  baseUrl.protocol !== "http:"
  || !new Set(["127.0.0.1", "::1", "localhost"]).has(normalizedBaseHostname)
  || !baseUrl.port
  || baseUrl.pathname !== "/"
  || baseUrl.search
  || baseUrl.hash
) {
  throw new Error("MENTAT_WEB_BASE_URL must be an explicit loopback HTTP origin");
}
if (!existsSync(lighthouseCli)) {
  throw new Error("The locked Lighthouse CLI is missing; run npm ci first");
}
if (!/^\d+\.\d+\.\d+\.\d+$/u.test(expectedChromeVersion)) {
  throw new Error("The Chrome for Testing version pin must be an exact stable version");
}

const configuredChromePath = process.env.CHROME_PATH?.trim() ?? "";
if (!configuredChromePath || !isAbsolute(configuredChromePath) || !existsSync(configuredChromePath)) {
  throw new Error("CHROME_PATH must be an explicit absolute path to pinned Chrome for Testing");
}
const chromePath = configuredChromePath;

const configuredFailurePath = process.env.MENTAT_LIGHTHOUSE_FAILURE_PATH?.trim() ?? "";
const failureEvidencePath = configuredFailurePath ? resolve(configuredFailurePath) : null;
if (
  failureEvidencePath
  && (!isAbsolute(configuredFailurePath) || basename(failureEvidencePath) !== "mentat-lighthouse-failure.json")
) {
  throw new Error(
    "MENTAT_LIGHTHOUSE_FAILURE_PATH must be an absolute mentat-lighthouse-failure.json path",
  );
}

const activeAuditChildren = new Set();
const activeReportDirectories = new Set();
const runtimeState = {
  activeRun: null,
  chromeVersion: null,
  results: { desktop: [], mobile: [] },
};

function cleanupActiveResources() {
  for (const child of activeAuditChildren) {
    try {
      terminateProcessTree(child);
    } catch {
      // Continue so owned Chrome and report directories are still withdrawn.
    }
  }
  activeAuditChildren.clear();
  killAll();
  for (const reportDirectory of activeReportDirectories) {
    rmSync(reportDirectory, {
      force: true,
      maxRetries: 5,
      recursive: true,
      retryDelay: 200,
    });
  }
  activeReportDirectories.clear();
}

let handlingSignal = false;
function handleSignal(signal) {
  if (handlingSignal) return;
  handlingSignal = true;
  let evidenceError;
  try {
    writeFailureEvidence(runtimeState, new Error(`Lighthouse gate interrupted by ${signal}`));
  } catch (error) {
    evidenceError = error;
  }
  cleanupActiveResources();
  if (evidenceError) console.error(`Could not write Lighthouse failure evidence: ${evidenceError}`);
  process.exit(signal === "SIGINT" ? 130 : 143);
}

process.once("SIGINT", () => handleSignal("SIGINT"));
process.once("SIGTERM", () => handleSignal("SIGTERM"));
process.once("exit", cleanupActiveResources);

function trackedProcessOptions(timeoutMs) {
  return {
    cwd: projectRoot,
    env: { ...process.env, CHROME_PATH: chromePath },
    onClose: (child) => activeAuditChildren.delete(child),
    onSpawn: (child) => activeAuditChildren.add(child),
    timeoutMs,
  };
}

async function verifyChromeVersion() {
  const result = await runBoundedProcess(
    chromePath,
    ["--version"],
    trackedProcessOptions(10000),
  );
  if (result.timedOut || result.status !== 0) {
    throw new Error("Pinned Chrome for Testing version probe failed");
  }
  const reported = `${result.stdout}\n${result.stderr}`.trim().replace(/\s+/gu, " ");
  const actualVersion = reported.match(/\b\d+\.\d+\.\d+\.\d+\b/u)?.[0] ?? "";
  if (actualVersion !== expectedChromeVersion) {
    throw new Error(
      `Chrome for Testing ${expectedChromeVersion} is required; received ${actualVersion || "unknown"}`,
    );
  }
  return actualVersion;
}

function numericAudit(lhr, id) {
  const value = lhr.audits[id]?.numericValue;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Lighthouse did not return numeric audit ${id}`);
  }
  return value;
}

function transferredBytes(lhr) {
  const items = lhr.audits["resource-summary"]?.details?.items;
  if (!Array.isArray(items)) return null;
  const total = items.find((item) => item.resourceType === "total")?.transferSize;
  return typeof total === "number" && Number.isFinite(total) ? total : null;
}

function summarize(lhr, mode, run) {
  if (lhr.runtimeError) {
    throw new Error(`Lighthouse runtime error: ${lhr.runtimeError.code || "unknown"}`);
  }
  if (lhr.finalUrl !== baseUrl.href) {
    throw new Error(`Lighthouse navigated to an unexpected URL: ${lhr.finalUrl}`);
  }
  const scores = Object.fromEntries(CATEGORY_IDS.map((categoryId) => {
    const score = lhr.categories[categoryId]?.score;
    if (typeof score !== "number" || !Number.isFinite(score)) {
      throw new Error(`Lighthouse did not return category ${categoryId}`);
    }
    return [categoryId, Math.round(score * 100)];
  }));
  const summary = {
    run,
    scores,
    fcp_ms: numericAudit(lhr, "first-contentful-paint"),
    lcp_ms: numericAudit(lhr, "largest-contentful-paint"),
    tbt_ms: numericAudit(lhr, "total-blocking-time"),
    cls: numericAudit(lhr, "cumulative-layout-shift"),
    transfer_bytes: transferredBytes(lhr),
  };
  return summary;
}

function medianScore(scores) {
  if (scores.length !== RUNS_PER_MODE) {
    throw new Error(`Expected ${RUNS_PER_MODE} Lighthouse scores; received ${scores.length}`);
  }
  const orderedScores = [...scores].sort((left, right) => left - right);
  return orderedScores[Math.floor(orderedScores.length / 2)];
}

function validateModeResults(mode, results) {
  const failedCategories = results.flatMap((result) => Object.entries(result.scores)
    .filter(([categoryId, score]) => categoryId !== "performance" && score < 100)
    .map(([categoryId, score]) => `run ${result.run} ${categoryId}=${score}`));
  if (failedCategories.length) {
    throw new Error(
      `${mode} runs missed the required non-performance category scores: `
      + `${failedCategories.join(", ")}; results=${JSON.stringify(results)}`,
    );
  }
  const performanceScores = results.map((result) => result.scores.performance);
  const performanceMedian = medianScore(performanceScores);
  if (performanceMedian < minimumPerformanceScore) {
    throw new Error(
      `${mode} median performance score ${performanceMedian} missed the minimum `
      + `${minimumPerformanceScore}; runs=${performanceScores.join(", ")}; `
      + `results=${JSON.stringify(results)}`,
    );
  }
  return performanceMedian;
}

function modeArguments(mode) {
  if (mode === "desktop") {
    return ["--preset=desktop", "--throttling-method=provided"];
  }
  return [
    "--form-factor=mobile",
    "--throttling-method=simulate",
    "--screenEmulation.mobile=true",
    "--screenEmulation.width=390",
    "--screenEmulation.height=844",
    "--screenEmulation.deviceScaleFactor=1",
  ];
}

async function runAuditAttempt(mode, run, reportDirectory) {
  const reportPath = resolve(reportDirectory, `${mode}-${run}.json`);
  let ownedChrome;
  try {
    try {
      ownedChrome = await launchChrome({
        chromePath,
        chromeFlags: [
          "--headless",
          "--no-sandbox",
          "--disable-gpu",
          "--disable-dev-shm-usage",
        ],
        handleSIGINT: false,
        logLevel: "silent",
      });
    } catch (error) {
      const cleanupErrors = killAll();
      if (cleanupErrors.length) {
        throw new AggregateError(
          [error, ...cleanupErrors],
          "Chrome launch failed and cleanup was incomplete",
        );
      }
      throw error;
    }
    const result = await runBoundedProcess(
      process.execPath,
      [
        lighthouseCli,
        baseUrl.href,
        "--output=json",
        `--output-path=${reportPath}`,
        `--only-categories=${CATEGORY_IDS.join(",")}`,
        "--max-wait-for-load=45000",
        `--port=${ownedChrome.port}`,
        "--hostname=127.0.0.1",
        "--no-enable-error-reporting",
        "--quiet",
        ...modeArguments(mode),
      ],
      trackedProcessOptions(120000),
    );
    if (result.timedOut) {
      throw new Error(`${mode} run ${run} exceeded the 120-second process timeout`);
    }
    if (result.status !== 0) {
      const diagnostic = `${result.stdout || ""}\n${result.stderr || ""}`.trim().slice(-2000);
      throw new Error(`${mode} run ${run} failed with exit ${result.status}: ${diagnostic}`);
    }
    const lhr = JSON.parse(readFileSync(reportPath, "utf8"));
    return {
      lighthouse_version: lhr.lighthouseVersion,
      ...summarize(lhr, mode, run),
    };
  } finally {
    ownedChrome?.kill();
  }
}

function isTransientTraceFailure(error) {
  return error instanceof Error && /\bNO_NAVSTART\b/u.test(error.message);
}

async function runAudit(mode, run, reportDirectory) {
  for (let attempt = 1; attempt <= AUDIT_ATTEMPTS; attempt += 1) {
    try {
      return await runAuditAttempt(mode, run, reportDirectory);
    } catch (error) {
      if (attempt === AUDIT_ATTEMPTS || !isTransientTraceFailure(error)) throw error;
      console.warn(`${mode} run ${run} encountered transient NO_NAVSTART; retrying once`);
    }
  }
  throw new Error(`${mode} run ${run} exhausted Lighthouse attempts`);
}

function writeFailureEvidence(state, error) {
  if (!failureEvidencePath) return;
  writeFileSync(
    failureEvidencePath,
    `${JSON.stringify({
      artifact_schema: 1,
      ok: false,
      url: baseUrl.href,
      expected_chrome_version: expectedChromeVersion,
      reported_chrome_version: state.chromeVersion,
      active_run: state.activeRun,
      completed_results: state.results,
      error: String(error?.stack || error?.message || error).slice(0, 4000),
    }, null, 2)}\n`,
    { encoding: "utf8", mode: 0o600 },
  );
}

async function main() {
  if (failureEvidencePath) rmSync(failureEvidencePath, { force: true });
  let reportDirectory;
  try {
    runtimeState.chromeVersion = await verifyChromeVersion();
    reportDirectory = mkdtempSync(join(tmpdir(), "mentat-lighthouse-"));
    activeReportDirectories.add(reportDirectory);
    for (const mode of Object.keys(runtimeState.results)) {
      for (let run = 1; run <= RUNS_PER_MODE; run += 1) {
        runtimeState.activeRun = { mode, run };
        runtimeState.results[mode].push(await runAudit(mode, run, reportDirectory));
      }
    }
    runtimeState.activeRun = null;
    const performanceMedians = Object.fromEntries(
      Object.entries(runtimeState.results).map(([mode, results]) => [
        mode,
        validateModeResults(mode, results),
      ]),
    );
    console.log(JSON.stringify({
      ok: true,
      url: baseUrl.href,
      chrome_version: runtimeState.chromeVersion,
      minimum_performance_score: minimumPerformanceScore,
      performance_medians: performanceMedians,
      runs_per_mode: RUNS_PER_MODE,
      results: runtimeState.results,
    }, null, 2));
  } catch (error) {
    writeFailureEvidence(runtimeState, error);
    throw error;
  } finally {
    if (reportDirectory) {
      rmSync(reportDirectory, {
        force: true,
        maxRetries: 5,
        recursive: true,
        retryDelay: 200,
      });
      activeReportDirectories.delete(reportDirectory);
    }
  }
}

try {
  await main();
} catch (error) {
  console.error(error.stack || error.message);
  process.exit(1);
}
