import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import vm from "node:vm";

import { SHELL_ROUTES } from "../src/lib/shell-routes.ts";

const webRoot = resolve(import.meta.dirname, "..");

function source(path: string): string {
  return readFileSync(resolve(webRoot, path), "utf8");
}

function runPreferencePreload(stored: string | null, systemHigh: boolean) {
  const dataset: Record<string, string> = {};
  const preloader = source("public/preference-preload.js");
  vm.runInNewContext(preloader, {
    document: { documentElement: { dataset } },
    window: {
      localStorage: { getItem: () => stored },
      matchMedia: () => ({ matches: systemHigh }),
    },
  });
  return dataset;
}

test("the Emerald shell exposes exactly the approved migration routes", () => {
  assert.deepEqual(
    SHELL_ROUTES.map(({ href, label }) => ({ href, label })),
    [
      { href: "/", label: "Home" },
      { href: "/agents", label: "Agents" },
      { href: "/tasks", label: "Tasks" },
      { href: "/runs", label: "Runs" },
    ],
  );

  const routeSources = new Map([
    ["/", source("src/app/page.tsx")],
    ["/agents", source("src/app/agents/page.tsx")],
    ["/tasks", source("src/app/tasks/page.tsx")],
    ["/runs", source("src/app/runs/page.tsx")],
  ]);
  for (const [href, page] of routeSources) {
    assert.match(page, new RegExp(`<AppShell route=["']${href}["']>`));
  }
  assert.match(routeSources.get("/agents") ?? "", /data-agents-root/);
  assert.match(routeSources.get("/agents") ?? "", /Loading canonical Agents/);
  assert.match(routeSources.get("/tasks") ?? "", /data-tasks-root/);
  assert.match(routeSources.get("/tasks") ?? "", /Loading current Tasks/);
  assert.match(routeSources.get("/runs") ?? "", /data-runs-root/);
  assert.match(routeSources.get("/runs") ?? "", /Loading current Runs/);
  assert.match(routeSources.get("/runs") ?? "", /aria-live="polite" className="runs-summary"/);
});

test("contrast preference is applied before paint with safe system fallback", () => {
  assert.deepEqual(runPreferencePreload(null, false), {
    uiShell: "emerald",
    contrastPreference: "system",
    contrast: "standard",
  });
  assert.deepEqual(runPreferencePreload(null, true), {
    uiShell: "emerald",
    contrastPreference: "system",
    contrast: "high",
  });
  assert.deepEqual(runPreferencePreload("high", false), {
    uiShell: "emerald",
    contrastPreference: "high",
    contrast: "high",
  });
  assert.deepEqual(runPreferencePreload("invalid", true), {
    uiShell: "emerald",
    contrastPreference: "system",
    contrast: "high",
  });
});

test("responsive shell contracts retain the completed Emerald tokens", () => {
  const css = source("src/app/globals.css");
  const shell = source("src/app/app-shell.tsx");
  for (const token of [
    "--canvas: #070d11",
    "--panel: #0f151a",
    "--text-primary: #eae7dd",
    "--accent: #9dce9b",
    "--sidebar-width: 216px",
    "--utility-height: 64px",
  ]) {
    assert.match(css, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&")));
  }
  assert.match(css, /max-width: 1199px[\s\S]*min-width: 901px/);
  assert.match(css, /--sidebar-width: 76px/);
  assert.match(css, /@media \(max-width: 900px\)/);
  assert.match(css, /@media \(max-width: 900px\)[\s\S]*\.dashboard-grid \{\s*grid-template-columns: 1fr/);
  assert.match(css, /@media \(max-width: 640px\)[\s\S]*\.main-content \{\s*padding-inline: 12px/);
  assert.match(css, /:root\[data-nav-open\] \.sidebar/);
  assert.match(css, /@media \(max-width: 520px\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.sidebar \{[\s\S]*overflow-y: auto/);
  assert.match(css, /\.icon-button \{[\s\S]*width: 44px;[\s\S]*height: 44px/);
  assert.match(
    css,
    /@media \(max-width: 900px\)[\s\S]*\.brand,\s*\.contrast-control,\s*\.contrast-control select \{\s*min-height: 44px/,
  );
  assert.doesNotMatch(css, /\.contrast-control select \{[^}]*outline:\s*0/su);
  assert.match(shell, /from "next\/link"/);
  assert.match(shell, /<Link[\s\S]*data-nav-link/);
  assert.match(shell, /className="brand" data-nav-link href="\/"/);
  assert.match(shell, /aria-label=\{item\.label\}/);
  assert.match(css, /\.primary-nav \{[\s\S]*overflow-y: auto/);
  assert.match(css, /\.nav-tooltip \{[\s\S]*position: fixed/);
  assert.doesNotMatch(css, /\.nav-link::after/);
  assert.match(shell, /data-nav-tooltip hidden/);
  assert.match(css, /@media \(max-width: 900px\)[\s\S]*\.sidebar \{[\s\S]*visibility: hidden/);
  assert.match(css, /:root\[data-nav-open\] \.sidebar \{[\s\S]*visibility: visible/);
  assert.ok(statSync(resolve(webRoot, "public/mentat-mark-emerald.png")).size < 25_000);
});

test("the small runtime enhances the shell without exposing bridge authority", () => {
  const runtime = source("public/shell-runtime.js");
  assert.match(runtime, /fetch\("\/api\/bridge\/health"/);
  assert.match(runtime, /fetch\("\/api\/agents"/);
  assert.match(runtime, /fetch\("\/api\/tasks"/);
  assert.match(runtime, /Promise\.allSettled\(\[load\("\/api\/runs"\), load\("\/api\/agents"\)\]\)/);
  assert.match(runtime, /data-agents-refresh/);
  assert.match(runtime, /data-tasks-refresh/);
  assert.match(runtime, /data-runs-refresh/);
  assert.ok(runtime.includes("`${agent.id}\\0${agent.runtime_type}`"));
  assert.ok(runtime.includes("indexedAgents.get(`${run.agent_id}\\0${run.runtime_type}`)"));
  assert.ok(runtime.includes("agent?.name || (run.agent_id ? `Agent ${run.agent_id}` : `Run ${run.id}`)"));
  assert.match(runtime, /card\.setAttribute\("aria-labelledby", heading\.id\)/);
  assert.match(runtime, /`Open timeline for \$\{runLabel\}`/);
  assert.match(runtime, /`Send message to \$\{runLabel\}`/);
  assert.match(runtime, /`Respond to \$\{runLabel\}`/);
  assert.match(runtime, /`Stop run for \$\{runLabel\}`/);
  assert.match(runtime, /readableRunStatus/);
  assert.match(runtime, /textContent = agent\.name/);
  assert.match(runtime, /Stopping asks the selected runtime to cancel this active Run\./);
  assert.doesNotMatch(runtime, /Stopping asks Hermes/);
  assert.doesNotMatch(runtime, /MENTAT_BRIDGE_TOKEN|X-Mentat-Bridge-Token|local path/);
  assert.match(runtime, /AbortSignal\.timeout\(3500\)/);
  assert.match(runtime, /mobileNavigation = window\.matchMedia\("\(max-width: 900px\)"\)/);
  assert.match(runtime, /workspace\.inert = true/);
  assert.match(runtime, /event\.key === "Escape"/);
  assert.match(runtime, /full: "Python unavailable", compact: "Offline"/);
  assert.match(runtime, /focusTarget = mobileNavigation\.matches \? openButton : currentNavigationLink/);
  assert.match(runtime, /document\.addEventListener\("click"/);
  assert.match(runtime, /compactNavigation = window\.matchMedia/);
  assert.match(runtime, /showNavigationTooltip/);
  assert.match(runtime, /document\.addEventListener\("focusin", \(event\) => \{\s*if \(!runtimeStarted\) return/);
  assert.match(runtime, /document\.addEventListener\("pointerover", \(event\) => \{\s*if \(!runtimeStarted\) return/);
  assert.match(runtime, /document\.addEventListener\("scroll", \(event\) => \{\s*if \(!runtimeStarted\) return/);
  assert.match(runtime, /sidebar\?\.contains\(event\.target\) && focusedNavigationLink/);
  assert.match(runtime, /root\.dataset\.shellRuntime = "ready"/);
  assert.match(runtime, /new MutationObserver\(synchronizeShell\)/);
  assert.match(runtime, /mentat:shell-hydrated/);
  assert.match(runtime, /frameworkRuntime[\s\S]*window\.addEventListener/);
  assert.match(source("src/app/app-shell.tsx"), /<select aria-label="Contrast"/);
  assert.doesNotMatch(source("src/app/app-shell.tsx"), /data-mentat-shell-runtime/);
  assert.match(source("src/app/layout.tsx"), /data-mentat-preference-preload/);
  assert.match(source("src/app/layout.tsx"), /data-mentat-shell-runtime/);
  assert.match(source("src/app/layout.tsx"), /<ShellRuntimeSignal \/>/);
  assert.match(source("src/app/shell-runtime-signal.tsx"), /useEffect/);
  assert.match(source("src/app/shell-runtime-signal.tsx"), /mentat:shell-hydrated/);
});

test("production emits four script-light static routes", () => {
  const config = source("next.config.ts");
  const compiler = source("scripts/prepare-standalone.mjs");
  for (const destination of [
    "/shell/home.html",
    "/shell/agents.html",
    "/shell/tasks.html",
    "/shell/runs.html",
  ]) {
    assert.ok(config.includes(`destination: "${destination}"`));
  }
  assert.match(compiler, /scripts\.length !== 2/);
  assert.match(compiler, /"\/preference-preload\.js", "\/shell-runtime\.js"/);
  assert.match(compiler, /shell\.includes\("self\.__next_f"\)/);
  assert.match(compiler, /failed its no-hydration contract/);
  assert.match(config, /developmentRuntime = process\.env\.NODE_ENV === "development"/);
  assert.match(config, /agentRules: false/);
  assert.match(config, /developmentRuntime[\s\S]*script-src 'self' 'unsafe-inline' 'unsafe-eval'/);
  assert.match(config, /staticShell[\s\S]*\? "script-src 'self'"/);
});
