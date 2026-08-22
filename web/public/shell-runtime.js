const root = document.documentElement;
const storageKey = "mentat-contrast-v1";
const contrastMedia = window.matchMedia("(prefers-contrast: more)");
const mobileNavigation = window.matchMedia("(max-width: 900px)");
const compactNavigation = window.matchMedia("(min-width: 901px) and (max-width: 1199px)");
const supportedContrast = new Set(["system", "standard", "high"]);

let bridgeRequest = 0;
let bridgeState = "checking";
let agentsRequest = 0;
let agentsAbortController = null;
let tasksRequest = 0;
let tasksAbortController = null;
let runsRequest = 0;
let runsAbortController = null;
let activeRunTimeline = null;
let activeRunStop = null;
let activeRunMessage = null;
let activeRunResponse = null;
let renderedRuns = new Map();
let pendingRunsSummaryNotice = "";
let navigationOwnsFocus = false;
let observedPath = "";
let runtimeStarted = false;

function storedContrast() {
  try {
    const value = window.localStorage.getItem(storageKey);
    return value === "standard" || value === "high" ? value : "system";
  } catch {
    return "system";
  }
}

function applyContrast(preference) {
  const safePreference = preference === "standard" || preference === "high" ? preference : "system";
  root.dataset.contrastPreference = safePreference;
  root.dataset.contrast = safePreference === "high" || (safePreference === "system" && contrastMedia.matches)
    ? "high"
    : "standard";

  document.querySelectorAll("[data-contrast-select]").forEach((select) => {
    if (select instanceof HTMLSelectElement && select.value !== safePreference) {
      select.value = safePreference;
    }
  });
}

function shellElements() {
  const shell = document.querySelector(".app-shell");
  return {
    shell,
    sidebar: shell?.querySelector(".sidebar"),
    currentNavigationLink: shell?.querySelector('[data-nav-link][aria-current="page"]'),
    workspace: shell?.querySelector("[data-workspace]"),
    openButton: shell?.querySelector("[data-nav-open]"),
    closeButton: shell?.querySelector("[data-nav-close]"),
    backdrop: shell?.querySelector("[data-nav-backdrop]"),
  };
}

function setSidebarAvailability(isOpen) {
  const { sidebar } = shellElements();
  if (!(sidebar instanceof HTMLElement)) return;
  const unavailable = mobileNavigation.matches && !isOpen;
  sidebar.inert = unavailable;
  sidebar.setAttribute("aria-hidden", unavailable ? "true" : "false");
}

function closeNavigation(returnFocus = true) {
  const { openButton, workspace, backdrop } = shellElements();
  delete root.dataset.navOpen;
  openButton?.setAttribute("aria-expanded", "false");
  if (backdrop instanceof HTMLButtonElement) backdrop.hidden = true;
  if (workspace instanceof HTMLElement) workspace.inert = false;
  setSidebarAvailability(false);
  if (returnFocus && openButton instanceof HTMLElement && mobileNavigation.matches) {
    openButton.focus();
  }
}

function openNavigation() {
  if (!mobileNavigation.matches) return;
  const { openButton, closeButton, workspace, backdrop } = shellElements();
  root.dataset.navOpen = "true";
  openButton?.setAttribute("aria-expanded", "true");
  if (backdrop instanceof HTMLButtonElement) backdrop.hidden = false;
  if (workspace instanceof HTMLElement) workspace.inert = true;
  setSidebarAvailability(true);
  if (closeButton instanceof HTMLElement) closeButton.focus();
}

function hideNavigationTooltip() {
  const tooltip = document.querySelector("[data-nav-tooltip]");
  if (tooltip instanceof HTMLElement) tooltip.hidden = true;
}

function showNavigationTooltip(link) {
  if (!(link instanceof HTMLElement) || !link.matches(".nav-link") || !compactNavigation.matches) {
    hideNavigationTooltip();
    return;
  }
  const tooltip = document.querySelector("[data-nav-tooltip]");
  const label = link.dataset.tooltip || link.getAttribute("aria-label") || "";
  if (!(tooltip instanceof HTMLElement) || !label) return;

  tooltip.textContent = label;
  tooltip.hidden = false;
  const linkRect = link.getBoundingClientRect();
  const sidebarRect = link.closest(".sidebar")?.getBoundingClientRect();
  const tooltipRect = tooltip.getBoundingClientRect();
  const preferredLeft = Math.max(linkRect.right + 10, (sidebarRect?.right || 0) + 8);
  const left = Math.min(
    preferredLeft,
    Math.max(8, window.innerWidth - tooltipRect.width - 8),
  );
  const top = Math.min(
    Math.max(8, linkRect.top + ((linkRect.height - tooltipRect.height) / 2)),
    Math.max(8, window.innerHeight - tooltipRect.height - 8),
  );
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function applyBridgeState() {
  const statusText = bridgeState === "ready"
    ? { full: "Python ready", compact: "Ready" }
    : bridgeState === "unavailable"
      ? { full: "Python unavailable", compact: "Offline" }
      : { full: "Checking Python", compact: "Check" };

  document.querySelectorAll("[data-bridge-status]").forEach((status) => {
    if (status.getAttribute("data-state") !== bridgeState) {
      status.setAttribute("data-state", bridgeState);
    }
    const full = status.querySelector("[data-bridge-status-text]");
    const compact = status.querySelector("[data-bridge-status-compact]");
    if (full && full.textContent !== statusText.full) full.textContent = statusText.full;
    if (compact && compact.textContent !== statusText.compact) compact.textContent = statusText.compact;
  });
}

async function refreshBridgeStatus() {
  const request = ++bridgeRequest;
  try {
    const response = await fetch("/api/bridge/health", {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(3500),
    });
    const payload = await response.json();
    if (!response.ok || payload?.status !== "ready" || typeof payload?.mentat_version !== "string") {
      throw new Error("bridge_unavailable");
    }
    if (request !== bridgeRequest) return;
    bridgeState = "ready";
  } catch {
    if (request !== bridgeRequest) return;
    bridgeState = "unavailable";
  }
  applyBridgeState();
}

function agentsElements() {
  const rootElement = document.querySelector("[data-agents-root]");
  if (!(rootElement instanceof HTMLElement)) return null;
  const summary = rootElement.querySelector("[data-agents-summary]");
  const list = rootElement.querySelector("[data-agents-list]");
  const refresh = rootElement.querySelector("[data-agents-refresh]");
  if (!(summary instanceof HTMLElement) || !(list instanceof HTMLElement) || !(refresh instanceof HTMLButtonElement)) {
    return null;
  }
  return { list, refresh, rootElement, summary };
}

function agentIsSafe(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keys = Object.keys(value).sort().join(",");
  if (keys !== "capabilities,id,name,runtime_config_id,runtime_type") return false;
  return (
    typeof value.id === "string"
    && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value.id)
    && typeof value.name === "string"
    && value.name.trim() === value.name
    && value.name.length > 0
    && value.name.length <= 120
    && !value.name.includes("\0")
    && typeof value.runtime_type === "string"
    && /^[a-z][a-z0-9_-]{0,31}$/.test(value.runtime_type)
    && typeof value.runtime_config_id === "string"
    && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value.runtime_config_id)
    && Array.isArray(value.capabilities)
    && value.capabilities.length <= 64
    && value.capabilities.every((capability) => (
      typeof capability === "string" && /^[a-z][a-z0-9_.-]{0,63}$/.test(capability)
    ))
    && value.capabilities.every((capability, index, capabilities) => (
      index === 0 || capabilities[index - 1] < capability
    ))
  );
}

function readAgentsPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  if (payload.schema_version !== 1 || payload.status !== "ready" || !Array.isArray(payload.agents)) {
    return null;
  }
  if (!Number.isInteger(payload.count) || payload.count !== payload.agents.length || payload.count > 128) {
    return null;
  }
  if (!payload.agents.every(agentIsSafe)) return null;
  if (new Set(payload.agents.map((agent) => agent.id)).size !== payload.agents.length) return null;
  return payload.agents;
}

function writeAgentField(card, label, value) {
  const field = document.createElement("div");
  field.className = "agent-field";
  const name = document.createElement("dt");
  name.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = value;
  field.append(name, detail);
  card.append(field);
}

function renderAgents(agents) {
  const elements = agentsElements();
  if (!elements) return;
  elements.list.replaceChildren();
  for (const agent of agents) {
    const card = document.createElement("article");
    card.className = "agent-card";
    const heading = document.createElement("h3");
    heading.textContent = agent.name;
    const fields = document.createElement("dl");
    fields.className = "agent-fields";
    writeAgentField(fields, "Mentat ID", agent.id);
    writeAgentField(fields, "Runtime", agent.runtime_type);
    writeAgentField(fields, "Runtime config", agent.runtime_config_id);
    card.append(heading, fields);

    const capabilityLabel = document.createElement("p");
    capabilityLabel.className = "agent-capability-label";
    capabilityLabel.textContent = "Declared capabilities";
    const capabilities = document.createElement("ul");
    capabilities.className = "agent-capabilities";
    if (agent.capabilities.length === 0) {
      const capability = document.createElement("li");
      capability.textContent = "None declared";
      capabilities.append(capability);
    } else {
      for (const capabilityName of agent.capabilities) {
        const capability = document.createElement("li");
        capability.textContent = capabilityName;
        capabilities.append(capability);
      }
    }
    card.append(capabilityLabel, capabilities);
    elements.list.append(card);
  }
}

function applyAgentsState(state, detail, agents = null) {
  const elements = agentsElements();
  if (!elements) return;
  elements.rootElement.dataset.agentsState = state;
  elements.rootElement.setAttribute("aria-busy", state === "loading" ? "true" : "false");
  elements.summary.textContent = detail;
  elements.refresh.disabled = state === "loading";
  if (Array.isArray(agents)) {
    renderAgents(agents);
  } else {
    elements.list.replaceChildren();
  }
}

function clearAgentRequest() {
  agentsRequest += 1;
  agentsAbortController?.abort();
  agentsAbortController = null;
}

async function refreshAgents() {
  const elements = agentsElements();
  if (!elements) return;
  clearAgentRequest();
  const request = agentsRequest;
  agentsAbortController = new AbortController();
  applyAgentsState("loading", "Loading canonical Agents…");
  try {
    const response = await fetch("/api/agents", {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: agentsAbortController.signal,
    });
    const payload = await response.json();
    if (request !== agentsRequest) return;
    if (response.status === 200) {
      const agents = readAgentsPayload(payload);
      if (!agents) throw new Error("agents_response_invalid");
      applyAgentsState(
        agents.length === 0 ? "empty" : "ready",
        agents.length === 0 ? "No canonical Agents yet." : `${agents.length} canonical Agent${agents.length === 1 ? "" : "s"}.`,
        agents,
      );
      return;
    }
    if (response.status === 501 && payload?.schema_version === 1 && payload?.status === "unsupported") {
      applyAgentsState("unsupported", "This Python bridge does not support Agent data yet.");
      return;
    }
    if (response.status === 503 && payload?.schema_version === 1 && payload?.status === "unavailable") {
      applyAgentsState("unavailable", "Agent data is temporarily unavailable. Check the Python connection and retry.");
      return;
    }
    throw new Error("agents_response_invalid");
  } catch {
    if (request !== agentsRequest) return;
    applyAgentsState("error", "Mentat could not safely read Agent data. Try again.");
  } finally {
    if (request === agentsRequest) agentsAbortController = null;
  }
}

function tasksElements() {
  const rootElement = document.querySelector("[data-tasks-root]");
  if (!(rootElement instanceof HTMLElement)) return null;
  const summary = rootElement.querySelector("[data-tasks-summary]");
  const list = rootElement.querySelector("[data-tasks-list]");
  const refresh = rootElement.querySelector("[data-tasks-refresh]");
  return summary instanceof HTMLElement && list instanceof HTMLElement && refresh instanceof HTMLButtonElement ? { rootElement, summary, list, refresh } : null;
}
function taskIsSafe(task) {
  return task && typeof task === "object" && !Array.isArray(task)
    && Object.keys(task).sort().join(",") === "due_date,id,needs_attention,priority,project,review_required,status,tags,title,updated_at"
    && typeof task.id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/.test(task.id)
    && typeof task.title === "string" && task.title.trim() === task.title && task.title.length > 0 && task.title.length <= 160
    && typeof task.project === "string" && task.project.trim() === task.project && task.project.length > 0 && task.project.length <= 120
    && ["todo", "in progress", "waiting", "needs attention", "completed"].includes(task.status)
    && ["high", "medium", "low"].includes(task.priority)
    && (task.due_date === null || typeof task.due_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(task.due_date))
    && Array.isArray(task.tags) && task.tags.length <= 64 && task.tags.every((tag) => typeof tag === "string" && tag.trim() === tag && tag.length > 0 && tag.length <= 48)
    && new Set(task.tags).size === task.tags.length && typeof task.needs_attention === "boolean" && typeof task.review_required === "boolean" && typeof task.updated_at === "string";
}
function readTasksPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload) || payload.schema_version !== 1 || payload.status !== "ready" || !Array.isArray(payload.tasks) || !Number.isInteger(payload.count) || payload.count !== payload.tasks.length || payload.count > 2048 || !payload.tasks.every(taskIsSafe)) return null;
  return new Set(payload.tasks.map((task) => task.id)).size === payload.tasks.length ? payload.tasks : null;
}
function renderTasks(tasks) {
  const elements = tasksElements(); if (!elements) return; elements.list.replaceChildren();
  for (const task of tasks) {
    const card = document.createElement("article"); card.className = "task-card";
    const header = document.createElement("div"); header.className = "task-card-header";
    const content = document.createElement("div"); const title = document.createElement("h3"); title.textContent = task.title;
    const meta = document.createElement("p"); meta.className = "task-card-meta"; meta.textContent = `${task.project} · ${task.priority}${task.due_date ? ` · Due ${task.due_date}` : ""}`;
    const safeFields = document.createElement("p"); safeFields.className = "task-card-meta"; safeFields.textContent = `ID ${task.id} · Updated ${task.updated_at}${task.needs_attention ? " · Needs attention" : ""}${task.review_required ? " · Review required" : ""}`;
    content.append(title, meta, safeFields); const status = document.createElement("p"); status.className = "task-status"; status.textContent = task.status; header.append(content, status); card.append(header);
    if (task.tags.length) { const tags = document.createElement("ul"); tags.className = "task-tags"; for (const tag of task.tags) { const item = document.createElement("li"); item.textContent = tag; tags.append(item); } card.append(tags); }
    elements.list.append(card);
  }
}
function applyTasksState(state, detail, tasks = null) {
  const elements = tasksElements(); if (!elements) return; elements.rootElement.dataset.tasksState = state; elements.rootElement.setAttribute("aria-busy", state === "loading" ? "true" : "false"); elements.summary.textContent = detail; elements.refresh.disabled = state === "loading"; if (Array.isArray(tasks)) renderTasks(tasks); else elements.list.replaceChildren();
}
function clearTaskRequest() { tasksRequest += 1; tasksAbortController?.abort(); tasksAbortController = null; }
async function refreshTasks() {
  if (!tasksElements()) return; clearTaskRequest(); const request = tasksRequest; tasksAbortController = new AbortController(); applyTasksState("loading", "Loading current Tasks…");
  try { const response = await fetch("/api/tasks", { cache: "no-store", headers: { Accept: "application/json" }, signal: tasksAbortController.signal }); const payload = await response.json(); if (request !== tasksRequest) return;
    if (response.status === 200) { const tasks = readTasksPayload(payload); if (!tasks) throw new Error("tasks_response_invalid"); applyTasksState(tasks.length ? "ready" : "empty", tasks.length ? `${tasks.length} current Task${tasks.length === 1 ? "" : "s"}.` : "No current Tasks yet.", tasks); return; }
    if (response.status === 501 && payload?.schema_version === 1 && payload?.status === "unsupported") { applyTasksState("unsupported", "This Python bridge does not support Task data yet."); return; }
    if (response.status === 503 && payload?.schema_version === 1 && payload?.status === "unavailable") { applyTasksState("unavailable", "Task data is temporarily unavailable. Check the Python connection and retry."); return; }
    throw new Error("tasks_response_invalid");
  } catch { if (request === tasksRequest) applyTasksState("error", "Mentat could not safely read Task data. Try again."); } finally { if (request === tasksRequest) tasksAbortController = null; }
}

function runsElements() {
  const rootElement = document.querySelector("[data-runs-root]"); if (!(rootElement instanceof HTMLElement)) return null;
  const summary = rootElement.querySelector("[data-runs-summary]"), list = rootElement.querySelector("[data-runs-list]"), refresh = rootElement.querySelector("[data-runs-refresh]");
  return summary instanceof HTMLElement && list instanceof HTMLElement && refresh instanceof HTMLButtonElement ? { rootElement, summary, list, refresh } : null;
}
function runIsSafe(run) {
  const timestamp = (value) => typeof value === "string" && value.length > 0 && value.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && !Number.isNaN(Date.parse(value));
  return run && typeof run === "object" && !Array.isArray(run)
    && Object.keys(run).sort().join(",") === "agent_id,completed_at,created_at,dispatch_state,id,partial,runtime_type,source,started_at,status,task_id,timeline_truncated,updated_at"
    && typeof run.id === "string" && /^run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}$/.test(run.id)
    && typeof run.source === "string" && /^[a-z][a-z0-9_.-]{0,63}$/.test(run.source)
    && (run.task_id === null || typeof run.task_id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/.test(run.task_id))
    && (run.agent_id === null || typeof run.agent_id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(run.agent_id))
    && typeof run.runtime_type === "string" && /^[a-z][a-z0-9_-]{0,31}$/.test(run.runtime_type)
    && ["reserved", "queued", "submitting", "starting", "running", "cancelling", "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown", "completed", "failed", "cancelled", "stopped", "interrupted"].includes(run.status)
    && ["legacy", "reserved", "submitting", "accepted", "rejected", "unknown"].includes(run.dispatch_state)
    && typeof run.partial === "boolean" && typeof run.timeline_truncated === "boolean" && timestamp(run.created_at) && timestamp(run.updated_at)
    && (run.started_at === null || timestamp(run.started_at)) && (run.completed_at === null || timestamp(run.completed_at));
}
function readRunsPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload) || Object.keys(payload).sort().join(",") !== "count,runs,runtime,schema_version,service,status" || payload.schema_version !== 1 || payload.service !== "mentat-local-bridge" || payload.runtime !== "python" || payload.status !== "ready" || !Array.isArray(payload.runs) || !Number.isInteger(payload.count) || payload.count !== payload.runs.length || payload.count > 50 || !payload.runs.every(runIsSafe)) return null;
  return new Set(payload.runs.map((run) => run.id)).size === payload.runs.length ? payload.runs : null;
}
function readableRunStatus(value) { return value.split(/[._]/).map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" "); }
function renderRuns(runs) {
  const elements = runsElements(); if (!elements) return; closeActiveRunTimeline({ restoreFocus: false }); closeActiveRunStop({ restoreFocus: false }); closeActiveRunMessage({ restoreFocus: false }); closeActiveRunResponse({ restoreFocus: false }); renderedRuns = new Map(runs.map((run) => [run.id, run])); elements.list.replaceChildren();
  for (const run of runs) {
    const card = document.createElement("article"); card.className = "run-card"; card.dataset.runId = run.id;
    const header = document.createElement("div"); header.className = "run-card-header";
    const heading = document.createElement("h3"); heading.textContent = run.id;
    const status = document.createElement("p"); status.className = "run-status"; status.textContent = readableRunStatus(run.status);
    header.append(heading, status); card.append(header);
    const primary = document.createElement("p"); primary.className = "run-card-meta"; primary.textContent = `${run.runtime_type} · ${run.source} · ${run.dispatch_state}`;
    const detail = document.createElement("p"); detail.className = "run-card-meta"; detail.textContent = `Task ${run.task_id || "Not linked"} · Agent ${run.agent_id || "Not assigned"} · Created ${run.created_at} · Updated ${run.updated_at}`;
    const lifecycle = document.createElement("p"); lifecycle.className = "run-card-meta"; lifecycle.textContent = `Started ${run.started_at || "Not started"} · Completed ${run.completed_at || "Not completed"}${run.partial ? " · Partial" : ""}${run.timeline_truncated ? " · Timeline truncated" : ""}`;
    const actions = document.createElement("div"); actions.className = "run-card-actions";
    const timeline = document.createElement("button"); timeline.className = "run-timeline-open"; timeline.dataset.runTimelineOpen = ""; timeline.dataset.runId = run.id; timeline.setAttribute("aria-expanded", "false"); timeline.type = "button"; timeline.textContent = "Open timeline";
    actions.append(timeline);
    if (run.status === "running") { const message = document.createElement("button"); message.className = "run-message-open"; message.dataset.runMessageOpen = ""; message.dataset.runId = run.id; message.setAttribute("aria-expanded", "false"); message.type = "button"; message.textContent = "Send message"; actions.append(message); }
    if (["waiting_for_approval", "waiting_for_clarification"].includes(run.status)) { const response = document.createElement("button"); response.className = "run-response-open"; response.dataset.runResponseOpen = ""; response.dataset.runId = run.id; response.setAttribute("aria-expanded", "false"); response.type = "button"; response.textContent = "Respond"; actions.append(response); }
    if (["queued", "submitting", "starting", "running", "waiting", "waiting_for_approval", "waiting_for_clarification"].includes(run.status)) { const stop = document.createElement("button"); stop.className = "run-stop-open"; stop.dataset.runStopOpen = ""; stop.dataset.runId = run.id; stop.setAttribute("aria-expanded", "false"); stop.type = "button"; stop.textContent = "Stop run"; actions.append(stop); }
    card.append(primary, detail, lifecycle, actions); elements.list.append(card);
  }
}
function applyRunsState(state, detail, runs = null) { const elements = runsElements(); if (!elements) return; elements.rootElement.dataset.runsState = state; elements.rootElement.setAttribute("aria-busy", state === "loading" ? "true" : "false"); elements.summary.textContent = detail; elements.refresh.disabled = state === "loading"; if (Array.isArray(runs)) renderRuns(runs); else { closeActiveRunTimeline({ restoreFocus: false }); closeActiveRunStop({ restoreFocus: false }); closeActiveRunMessage({ restoreFocus: false }); closeActiveRunResponse({ restoreFocus: false }); renderedRuns = new Map(); elements.list.replaceChildren(); } }
function clearRunRequest() { runsRequest += 1; runsAbortController?.abort(); runsAbortController = null; closeActiveRunTimeline({ restoreFocus: false }); closeActiveRunStop({ restoreFocus: false }); closeActiveRunMessage({ restoreFocus: false }); closeActiveRunResponse({ restoreFocus: false }); }
async function refreshRuns() {
  if (!runsElements()) return; clearRunRequest(); const request = runsRequest; runsAbortController = new AbortController(); applyRunsState("loading", "Loading current Runs…");
  try { const response = await fetch("/api/runs", { cache: "no-store", headers: { Accept: "application/json" }, signal: runsAbortController.signal }); const payload = await response.json(); if (request !== runsRequest) return;
    if (response.status === 200) { const runs = readRunsPayload(payload); if (!runs) throw new Error("runs_response_invalid"); const detail = pendingRunsSummaryNotice || (runs.length ? `${runs.length} current Run${runs.length === 1 ? "" : "s"}.` : "No current Runs yet."); pendingRunsSummaryNotice = ""; applyRunsState(runs.length ? "ready" : "empty", detail, runs); return; }
    if (response.status === 501 && payload?.schema_version === 1 && payload?.status === "unsupported") { applyRunsState("unsupported", "This Python bridge does not support Run data yet."); return; }
    if (response.status === 503 && payload?.schema_version === 1 && payload?.status === "unavailable") { applyRunsState("unavailable", "Run data is temporarily unavailable. Check the Python connection and retry."); return; }
    throw new Error("runs_response_invalid");
  } catch { if (request === runsRequest) applyRunsState("error", "Mentat could not safely read Run data. Try again."); } finally { if (request === runsRequest) runsAbortController = null; }
}

function runEventIsSafe(event, runId) {
  const metrics = new Set(["input_tokens", "output_tokens", "total_tokens", "context_tokens", "context_length"]);
  const timestamp = (value) => typeof value === "string" && value.length > 0 && value.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && !Number.isNaN(Date.parse(value));
  return event && typeof event === "object" && !Array.isArray(event) && Object.keys(event).sort().join(",") === "id,metrics,occurred_at,run_id,sequence,summary,type"
    && typeof event.id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(event.id) && event.run_id === runId
    && Number.isSafeInteger(event.sequence) && event.sequence >= 1 && event.sequence <= 1_000_000_000
    && ["run.created", "dispatch.reserved", "run.started", "submission.unknown", "run.interrupted", "tool.requested", "tool.completed", "approval.required", "artifact.created", "cost", "run.stopped", "run.completed", "run.failed", "message"].includes(event.type)
    && timestamp(event.occurred_at) && typeof event.summary === "string" && event.summary.length > 0 && event.summary.length <= 500 && event.summary.trim() === event.summary && !event.summary.includes("\0")
    && event.metrics && typeof event.metrics === "object" && !Array.isArray(event.metrics) && Object.entries(event.metrics).every(([name, value]) => metrics.has(name) && Number.isSafeInteger(value) && value >= 0 && value <= 1_000_000_000);
}

function readTimelineEnvelope(value, runId) {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join(",") !== "cursor,events,reset" || !Number.isSafeInteger(value.cursor) || value.cursor < 0 || value.cursor > 1_000_000_000 || typeof value.reset !== "boolean" || !Array.isArray(value.events) || value.events.length > 100 || !value.events.every((event) => runEventIsSafe(event, runId))) return null;
  return value;
}

function closeActiveRunTimeline({ restoreFocus = true } = {}) {
  if (!activeRunTimeline) return;
  activeRunTimeline.source?.close();
  activeRunTimeline.panel.remove();
  activeRunTimeline.trigger.setAttribute("aria-expanded", "false");
  if (restoreFocus && activeRunTimeline.trigger.isConnected) activeRunTimeline.trigger.focus();
  activeRunTimeline = null;
}

function closeActiveRunStop({ restoreFocus = true } = {}) {
  if (!activeRunStop) return;
  activeRunStop.panel.remove(); activeRunStop.trigger.setAttribute("aria-expanded", "false");
  if (restoreFocus && activeRunStop.trigger.isConnected) activeRunStop.trigger.focus();
  activeRunStop = null;
}

function closeActiveRunMessage({ restoreFocus = true } = {}) {
  if (!activeRunMessage) return;
  activeRunMessage.panel.remove(); activeRunMessage.trigger.setAttribute("aria-expanded", "false");
  if (restoreFocus && activeRunMessage.trigger.isConnected) activeRunMessage.trigger.focus(); activeRunMessage = null;
}

function closeActiveRunResponse({ restoreFocus = true } = {}) {
  if (!activeRunResponse) return;
  activeRunResponse.panel.remove(); activeRunResponse.trigger.setAttribute("aria-expanded", "false");
  if (restoreFocus && activeRunResponse.trigger.isConnected) activeRunResponse.trigger.focus(); activeRunResponse = null;
}

function stopStateMessage(response) {
  if (response.status === 404) return "This Run is no longer available.";
  if (response.status === 409) return "This Run changed. Review Stop again.";
  if (response.status === 501) return "Stop is not available for this Run.";
  if (response.status === 503) return "Run control is temporarily unavailable.";
  return "Mentat could not safely process Stop.";
}

function messageStateMessage(response) {
  if (response.status === 404) return "This Run is no longer available.";
  if (response.status === 409) return "This Run or message changed. Review this message again.";
  if (response.status === 501) return "Messages are not available for this Run.";
  if (response.status === 503) return "Run control is temporarily unavailable.";
  return "Mentat could not safely process this message.";
}

async function reviewRunStop(current) {
  current.confirm.disabled = true; current.confirmationId = null; current.notice.textContent = "Reviewing the current Run state…";
  try { const response = await fetch(`/api/runs/${encodeURIComponent(current.run.id)}/stop/preview`, { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: "{}" }); const payload = await response.json(); if (activeRunStop?.panel !== current.panel) return; if (response.status !== 200) { current.notice.textContent = stopStateMessage(response); return; } if (!payload || typeof payload !== "object" || Object.keys(payload).sort().join(",") !== "action,confirmation_id,requires_confirmation,run_id,runtime,schema_version,service,status" || payload.schema_version !== 1 || payload.service !== "mentat-local-bridge" || payload.runtime !== "python" || payload.status !== "ready" || payload.action !== "stop" || payload.run_id !== current.run.id || payload.requires_confirmation !== true || typeof payload.confirmation_id !== "string" || !/^[0-9a-f]{64}$/.test(payload.confirmation_id)) throw new Error("stop_preview_invalid"); current.confirmationId = payload.confirmation_id; delete current.confirm.dataset.runStopReview; current.confirm.dataset.runStopConfirm = ""; current.confirm.textContent = "Confirm stop"; current.notice.textContent = "Stopping asks Hermes to cancel this active Run."; current.confirm.disabled = false; } catch { if (activeRunStop?.panel !== current.panel) return; current.notice.textContent = "Mentat could not safely review Stop."; }
}

async function openRunStop(run, card, trigger) {
  closeActiveRunTimeline({ restoreFocus: false }); closeActiveRunStop({ restoreFocus: false });
  const panel = document.createElement("section"); panel.className = "run-stop"; panel.dataset.runStop = run.id;
  const heading = document.createElement("h4"); heading.textContent = "Stop this Run?";
  const notice = document.createElement("p"); notice.className = "run-stop-notice"; notice.setAttribute("aria-live", "polite"); notice.textContent = "Reviewing the current Run state…";
  const actions = document.createElement("div"); actions.className = "run-stop-actions";
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.dataset.runStopCancel = ""; cancel.textContent = "Cancel";
  const confirm = document.createElement("button"); confirm.type = "button"; confirm.dataset.runStopConfirm = ""; confirm.disabled = true; confirm.textContent = "Confirm stop";
  actions.append(cancel, confirm); panel.append(heading, notice, actions); card.append(panel); trigger.setAttribute("aria-expanded", "true"); activeRunStop = { trigger, panel, run, confirmationId: null, notice, confirm };
  reviewRunStop(activeRunStop);
}

async function confirmRunStop() {
  const current = activeRunStop; if (!current?.confirmationId) return;
  current.confirm.disabled = true; current.notice.textContent = "Requesting Stop…";
  try { const response = await fetch(`/api/runs/${encodeURIComponent(current.run.id)}/stop`, { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ confirmation_id: current.confirmationId }) }); const payload = await response.json(); if (response.status !== 202 || !payload || typeof payload !== "object" || Object.keys(payload).sort().join(",") !== "action,disposition,run_id,runtime,schema_version,service,status" || payload.schema_version !== 1 || payload.service !== "mentat-local-bridge" || payload.runtime !== "python" || payload.status !== "ready" || payload.action !== "stop" || payload.run_id !== current.run.id || payload.disposition !== "requested") { current.notice.textContent = stopStateMessage(response); if (response.status === 409) { current.confirmationId = null; delete current.confirm.dataset.runStopConfirm; current.confirm.dataset.runStopReview = ""; current.confirm.textContent = "Review Stop again"; } current.confirm.disabled = false; return; } current.notice.textContent = "Stop requested. Refreshing the Run…"; refreshRuns(); } catch { if (activeRunStop?.panel === current.panel) { current.notice.textContent = "Mentat could not safely process Stop."; current.confirm.disabled = false; } }
}

async function reviewRunMessage() {
  const current = activeRunMessage; if (!current) return;
  const text = current.input.value.trim(); if (!text) { current.notice.textContent = "Enter a message to review."; return; } current.input.value = text; current.review.disabled = true; current.notice.textContent = "Reviewing the current Run state…";
  try { const response = await fetch(`/api/runs/${encodeURIComponent(current.run.id)}/message/preview`, { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ text }) }); const payload = await response.json(); if (activeRunMessage?.panel !== current.panel) return; if (response.status !== 200 || !payload || typeof payload !== "object" || Object.keys(payload).sort().join(",") !== "action,confirmation_id,requires_confirmation,run_id,runtime,schema_version,service,status" || payload.schema_version !== 1 || payload.service !== "mentat-local-bridge" || payload.runtime !== "python" || payload.status !== "ready" || payload.action !== "message" || payload.run_id !== current.run.id || payload.requires_confirmation !== true || typeof payload.confirmation_id !== "string" || !/^[0-9a-f]{64}$/.test(payload.confirmation_id)) { current.notice.textContent = messageStateMessage(response); current.review.disabled = false; return; } current.confirmationId = payload.confirmation_id; current.input.disabled = true; current.confirm.hidden = false; current.notice.textContent = "Confirm this message for the current Run."; } catch { if (activeRunMessage?.panel === current.panel) { current.notice.textContent = "Mentat could not safely review this message."; current.review.disabled = false; } }
}

async function confirmRunMessage() {
  const current = activeRunMessage; if (!current?.confirmationId) return;
  current.confirm.disabled = true; current.notice.textContent = "Sending message…";
  try { const response = await fetch(`/api/runs/${encodeURIComponent(current.run.id)}/message`, { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ text: current.input.value, confirmation_id: current.confirmationId }) }); const payload = await response.json(); if (response.status !== 202 || !payload || typeof payload !== "object" || Object.keys(payload).sort().join(",") !== "action,disposition,run_id,runtime,schema_version,service,status" || payload.schema_version !== 1 || payload.service !== "mentat-local-bridge" || payload.runtime !== "python" || payload.status !== "ready" || payload.action !== "message" || payload.run_id !== current.run.id || payload.disposition !== "accepted") { current.notice.textContent = messageStateMessage(response); if (response.status === 409) { current.confirmationId = null; current.input.disabled = false; current.confirm.hidden = true; current.review.disabled = false; } current.confirm.disabled = false; return; } current.notice.textContent = "Message accepted. Refreshing the Run…"; refreshRuns(); } catch { if (activeRunMessage?.panel === current.panel) { current.notice.textContent = "Mentat could not safely send this message."; current.confirm.disabled = false; } }
}

function openRunMessage(run, card, trigger) {
  closeActiveRunTimeline({ restoreFocus: false }); closeActiveRunStop({ restoreFocus: false }); closeActiveRunMessage({ restoreFocus: false });
  const panel = document.createElement("section"); panel.className = "run-message"; const heading = document.createElement("h4"); heading.textContent = "Send a message"; const input = document.createElement("textarea"); input.id = `run-message-${run.id}`; input.rows = 3; input.placeholder = "Text-only guidance for this active Run"; input.addEventListener("input", () => { const characters = Array.from(input.value); if (characters.length > 6000) input.value = characters.slice(0, 6000).join(""); }); const label = document.createElement("label"); label.htmlFor = input.id; label.textContent = "Message"; const notice = document.createElement("p"); notice.className = "run-stop-notice"; notice.setAttribute("aria-live", "polite"); const actions = document.createElement("div"); actions.className = "run-stop-actions"; const cancel = document.createElement("button"); cancel.type = "button"; cancel.dataset.runMessageCancel = ""; cancel.textContent = "Cancel"; const review = document.createElement("button"); review.type = "button"; review.dataset.runMessageReview = ""; review.textContent = "Review message"; const confirm = document.createElement("button"); confirm.type = "button"; confirm.dataset.runMessageConfirm = ""; confirm.textContent = "Confirm message"; confirm.hidden = true; actions.append(cancel, review, confirm); panel.append(heading, label, input, notice, actions); card.append(panel); trigger.setAttribute("aria-expanded", "true"); activeRunMessage = { trigger, panel, run, input, notice, review, confirm, confirmationId: null }; input.focus();
}

function responseStateMessage(response) {
  if (response.status === 404) return "This Run is no longer available.";
  if (response.status === 409) return "This request changed. Review your response again.";
  if (response.status === 501) return "A response is not available for this Run.";
  if (response.status === 503) return "Run control is temporarily unavailable.";
  return "Mentat could not safely process this response.";
}

function pendingResponseRequestIsSafe(value, runId, requiresConfirmation) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keys = requiresConfirmation ? "action,confirmation_id,request,requires_confirmation,run_id,runtime,schema_version,service,status" : "action,request,requires_confirmation,run_id,runtime,schema_version,service,status";
  if (Object.keys(value).sort().join(",") !== keys || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || value.action !== "respond" || value.run_id !== runId || value.requires_confirmation !== requiresConfirmation) return false;
  if (requiresConfirmation && (typeof value.confirmation_id !== "string" || !/^[0-9a-f]{64}$/.test(value.confirmation_id))) return false;
  const request = value.request;
  if (!request || typeof request !== "object" || Array.isArray(request) || !Array.isArray(request.choices) || request.choices.length > 16 || !request.choices.every((choice) => choice && typeof choice === "object" && !Array.isArray(choice) && Object.keys(choice).sort().join(",") === "id,label" && typeof choice.id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(choice.id) && typeof choice.label === "string" && choice.label.length > 0 && choice.label.length <= 240) || new Set(request.choices.map((choice) => choice.id)).size !== request.choices.length) return false;
  if (request.kind === "approval") return Object.keys(request).sort().join(",") === "choices,kind,summary,title" && typeof request.title === "string" && request.title.length <= 240 && typeof request.summary === "string" && request.summary.length <= 2000 && request.choices.length > 0 && request.choices.every((choice) => ["once", "deny"].includes(choice.id));
  return request.kind === "clarification" && Object.keys(request).sort().join(",") === "choices,kind,prompt_type,question" && ["choice", "text"].includes(request.prompt_type) && typeof request.question === "string" && request.question.length > 0 && request.question.length <= 2000 && ((request.prompt_type === "choice" && request.choices.length > 0) || (request.prompt_type === "text" && request.choices.length === 0));
}

function selectedRunResponse(current) {
  const request = current.request;
  if (request.kind === "approval" || request.prompt_type === "choice") {
    const selected = current.panel.querySelector("input[name=run-response-choice]:checked");
    return selected instanceof HTMLInputElement ? { kind: request.kind, choice: selected.value } : null;
  }
  const text = current.input?.value.trim();
  return text ? { kind: "clarification", text } : null;
}

async function reviewRunResponse() {
  const current = activeRunResponse; const responseValue = current && selectedRunResponse(current); if (!current || !responseValue) { if (current) current.notice.textContent = "Choose or enter a response to review."; return; }
  current.review.disabled = true; current.notice.textContent = "Reviewing the current Run state…";
  try { const response = await fetch(`/api/runs/${encodeURIComponent(current.run.id)}/response/preview`, { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ response: responseValue }) }); const payload = await response.json(); if (activeRunResponse?.panel !== current.panel) return; if (response.status !== 200 || !pendingResponseRequestIsSafe(payload, current.run.id, true) || payload.request.kind !== current.request.kind || JSON.stringify(payload.request) !== JSON.stringify(current.request)) { current.notice.textContent = responseStateMessage(response); current.review.disabled = false; return; } current.responseValue = responseValue; current.confirmationId = payload.confirmation_id; current.confirm.hidden = false; current.notice.textContent = "Confirm this response for the current Run."; current.confirm.focus(); } catch { if (activeRunResponse?.panel === current.panel) { current.notice.textContent = "Mentat could not safely review this response."; current.review.disabled = false; } }
}

async function confirmRunResponse() {
  const current = activeRunResponse; if (!current?.confirmationId || !current.responseValue) return;
  current.confirm.disabled = true; current.notice.textContent = "Sending response…";
  try { const response = await fetch(`/api/runs/${encodeURIComponent(current.run.id)}/response`, { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ response: current.responseValue, confirmation_id: current.confirmationId }) }); const payload = await response.json(); if (response.status !== 202 || !payload || typeof payload !== "object" || Object.keys(payload).sort().join(",") !== "action,disposition,run_id,runtime,schema_version,service,status" || payload.schema_version !== 1 || payload.service !== "mentat-local-bridge" || payload.runtime !== "python" || payload.status !== "ready" || payload.action !== "respond" || payload.run_id !== current.run.id || payload.disposition !== "accepted") { if (response.status === 502 && payload?.schema_version === 1 && payload?.status === "partial") { pendingRunsSummaryNotice = "Mentat could not verify the response. Check the refreshed Run before trying again."; current.confirmationId = null; current.responseValue = null; current.confirm.hidden = true; current.review.disabled = true; refreshRuns(); return; } current.notice.textContent = responseStateMessage(response); if (response.status === 409) { current.confirmationId = null; current.responseValue = null; current.confirm.hidden = true; current.review.disabled = false; } current.confirm.disabled = false; return; } current.notice.textContent = "Response accepted. Refreshing the Run…"; refreshRuns(); } catch { if (activeRunResponse?.panel === current.panel) { current.notice.textContent = "Mentat could not safely send this response."; current.confirm.disabled = false; } }
}

async function openRunResponse(run, card, trigger) {
  closeActiveRunTimeline({ restoreFocus: false }); closeActiveRunStop({ restoreFocus: false }); closeActiveRunMessage({ restoreFocus: false }); closeActiveRunResponse({ restoreFocus: false });
  const panel = document.createElement("section"); panel.className = "run-response"; const heading = document.createElement("h4"); heading.textContent = "Respond to this Run"; const detail = document.createElement("p"); detail.className = "run-response-detail"; const form = document.createElement("div"); form.className = "run-response-form"; const notice = document.createElement("p"); notice.className = "run-stop-notice"; notice.setAttribute("aria-live", "polite"); notice.textContent = "Loading the current request…"; const actions = document.createElement("div"); actions.className = "run-stop-actions"; const cancel = document.createElement("button"); cancel.type = "button"; cancel.dataset.runResponseCancel = ""; cancel.textContent = "Cancel"; const review = document.createElement("button"); review.type = "button"; review.dataset.runResponseReview = ""; review.textContent = "Review response"; review.disabled = true; const confirm = document.createElement("button"); confirm.type = "button"; confirm.dataset.runResponseConfirm = ""; confirm.textContent = "Confirm response"; confirm.hidden = true; actions.append(cancel, review, confirm); panel.append(heading, detail, form, notice, actions); card.append(panel); trigger.setAttribute("aria-expanded", "true"); activeRunResponse = { trigger, panel, run, request: null, input: null, notice, review, confirm, confirmationId: null, responseValue: null };
  try { const response = await fetch(`/api/runs/${encodeURIComponent(run.id)}/response`, { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: "{}" }); const payload = await response.json(); if (activeRunResponse?.panel !== panel) return; if (response.status !== 200 || !pendingResponseRequestIsSafe(payload, run.id, false)) { notice.textContent = responseStateMessage(response); return; } const request = payload.request; activeRunResponse.request = request; if (request.kind === "approval") { detail.textContent = `${request.title}${request.summary ? `: ${request.summary}` : ""}`; } else { detail.textContent = request.question; }
    if (request.kind === "approval" || request.prompt_type === "choice") { for (const choice of request.choices) { const label = document.createElement("label"); const input = document.createElement("input"); input.type = "radio"; input.name = "run-response-choice"; input.value = choice.id; input.addEventListener("change", () => { review.disabled = false; confirm.hidden = true; activeRunResponse.confirmationId = null; }); label.append(input, document.createTextNode(choice.label)); form.append(label); } } else { const label = document.createElement("label"); label.className = "run-response-text-label"; const input = document.createElement("textarea"); input.id = `run-response-${run.id}`; input.rows = 3; label.htmlFor = input.id; label.textContent = "Response"; input.addEventListener("input", () => { const characters = Array.from(input.value); if (characters.length > 2000) input.value = characters.slice(0, 2000).join(""); review.disabled = !input.value.trim(); confirm.hidden = true; activeRunResponse.confirmationId = null; }); form.append(label, input); activeRunResponse.input = input; }
    notice.textContent = "Review your response before sending it."; if (activeRunResponse.input) activeRunResponse.input.focus();
  } catch { if (activeRunResponse?.panel === panel) notice.textContent = "Mentat could not safely load this request."; }
}

function appendTimelineEvents(list, events) {
  const known = new Set([...list.querySelectorAll("[data-run-event-sequence]")].map((item) => item.getAttribute("data-run-event-sequence")));
  for (const event of events) {
    if (known.has(String(event.sequence))) continue;
    const item = document.createElement("li"); item.dataset.runEventSequence = String(event.sequence);
    const title = document.createElement("strong"); title.textContent = readableRunStatus(event.type);
    const summary = document.createElement("p"); summary.textContent = event.summary;
    const occurred = document.createElement("time"); occurred.dateTime = event.occurred_at; occurred.textContent = event.occurred_at;
    item.append(title, summary, occurred);
    const metrics = Object.entries(event.metrics);
    if (metrics.length) { const detail = document.createElement("p"); detail.className = "run-event-metrics"; detail.textContent = metrics.map(([name, value]) => `${readableRunStatus(name)}: ${value}`).join(" · "); item.append(detail); }
    list.append(item); known.add(String(event.sequence));
  }
  while (list.children.length > 100) list.firstElementChild?.remove();
}

function openRunTimeline(run, card, trigger) {
  closeActiveRunTimeline({ restoreFocus: false });
  const panel = document.createElement("section"); panel.className = "run-timeline"; panel.dataset.runTimeline = run.id;
  const header = document.createElement("div"); header.className = "run-timeline-header";
  const heading = document.createElement("h4"); heading.textContent = "Live timeline";
  const close = document.createElement("button"); close.className = "run-timeline-close"; close.dataset.runTimelineClose = ""; close.type = "button"; close.textContent = "Close";
  header.append(heading, close);
  const notice = document.createElement("p"); notice.className = "run-timeline-notice"; notice.dataset.runTimelineNotice = ""; notice.setAttribute("aria-live", "polite"); notice.textContent = "Connecting to the live timeline…";
  const list = document.createElement("ol"); list.className = "run-timeline-list"; list.dataset.runTimelineList = "";
  panel.append(header, notice, list); card.append(panel); trigger.setAttribute("aria-expanded", "true"); activeRunTimeline = { source: null, trigger, panel };
  if (!("EventSource" in window)) { notice.textContent = "Live timelines are not supported in this browser."; return; }
  const source = new EventSource(`/api/runs/${encodeURIComponent(run.id)}/events`);
  activeRunTimeline.source = source;
  const applyEnvelope = (message, resetText) => {
    let value; try { value = JSON.parse(message.data); } catch { value = null; }
    const envelope = readTimelineEnvelope(value, run.id);
    if (!envelope) { notice.textContent = "Mentat could not safely read this timeline."; source.close(); if (activeRunTimeline?.source === source) activeRunTimeline.source = null; return; }
    if (envelope.reset) { list.replaceChildren(); notice.textContent = resetText; }
    appendTimelineEvents(list, envelope.events);
    if (!envelope.reset && !envelope.events.length && !list.children.length) notice.textContent = "No events yet. Watching this Run.";
    else if (!envelope.reset) notice.textContent = "Watching live events.";
  };
  source.addEventListener("snapshot", (message) => applyEnvelope(message, "Earlier timeline events are no longer available. Showing retained events."));
  source.addEventListener("reset", (message) => applyEnvelope(message, "Earlier timeline events are no longer available. Showing retained events."));
  source.addEventListener("timeline", (message) => { let value; try { value = JSON.parse(message.data); } catch { value = null; } if (!value || typeof value !== "object" || Object.keys(value).join(",") !== "event" || !runEventIsSafe(value.event, run.id)) { notice.textContent = "Mentat could not safely read this timeline."; source.close(); if (activeRunTimeline?.source === source) activeRunTimeline.source = null; return; } appendTimelineEvents(list, [value.event]); notice.textContent = "Watching live events."; });
  source.addEventListener("error", (message) => { if (!(message instanceof MessageEvent)) return; let code = "bridge_error"; try { const value = JSON.parse(message.data); if (value && typeof value === "object" && Object.keys(value).join(",") === "code" && ["bridge_unavailable", "bridge_unsupported", "run_not_found", "bridge_error"].includes(value.code)) code = value.code; } catch {} const messages = { bridge_unavailable: "Timeline data is temporarily unavailable.", bridge_unsupported: "This Python bridge does not support Run timelines yet.", run_not_found: "This Run is no longer available.", bridge_error: "Mentat could not safely read this timeline." }; notice.textContent = messages[code]; source.close(); if (activeRunTimeline?.source === source) activeRunTimeline.source = null; });
  source.onerror = () => { if (activeRunTimeline?.source === source && source.readyState === EventSource.CONNECTING) notice.textContent = "Reconnecting to the live timeline…"; };
}

function synchronizeShell() {
  if (!document.querySelector(".app-shell")) return;
  applyContrast(root.dataset.contrastPreference || storedContrast());
  setSidebarAvailability(Boolean(root.dataset.navOpen));
  applyBridgeState();

  if (window.location.pathname !== observedPath) {
    hideNavigationTooltip();
    observedPath = window.location.pathname;
    requestAnimationFrame(() => requestAnimationFrame(refreshBridgeStatus));
    if (agentsElements()) {
      requestAnimationFrame(() => requestAnimationFrame(refreshAgents));
    } else {
      clearAgentRequest();
    }
    if (tasksElements()) requestAnimationFrame(() => requestAnimationFrame(refreshTasks)); else clearTaskRequest();
    if (runsElements()) requestAnimationFrame(() => requestAnimationFrame(refreshRuns)); else clearRunRequest();
  }
}

document.addEventListener("change", (event) => {
  if (!runtimeStarted) return;
  const select = event.target;
  if (!(select instanceof HTMLSelectElement) || !select.matches("[data-contrast-select]")) return;
  const preference = select.value;
  if (!supportedContrast.has(preference)) return;

  try {
    if (preference === "system") {
      window.localStorage.removeItem(storageKey);
    } else {
      window.localStorage.setItem(storageKey, preference);
    }
  } catch {
    // The current page can still honor the choice when storage is unavailable.
  }
  applyContrast(preference);
});

document.addEventListener("click", (event) => {
  if (!runtimeStarted) return;
  const target = event.target instanceof Element
    ? event.target.closest("[data-agents-refresh], [data-tasks-refresh], [data-runs-refresh], [data-run-timeline-open], [data-run-timeline-close], [data-run-stop-open], [data-run-stop-cancel], [data-run-stop-confirm], [data-run-stop-review], [data-run-message-open], [data-run-message-cancel], [data-run-message-review], [data-run-message-confirm], [data-run-response-open], [data-run-response-cancel], [data-run-response-review], [data-run-response-confirm], [data-nav-open], [data-nav-close], [data-nav-backdrop], [data-nav-link]")
    : null;
  if (!target) return;
  if (target.matches("[data-agents-refresh]")) {
    refreshAgents();
    return;
  }
  if (target.matches("[data-tasks-refresh]")) { refreshTasks(); return; }
  if (target.matches("[data-runs-refresh]")) { refreshRuns(); return; }
  if (target.matches("[data-run-timeline-close]")) { closeActiveRunTimeline(); return; }
  if (target.matches("[data-run-stop-cancel]")) { closeActiveRunStop(); return; }
  if (target.matches("[data-run-stop-confirm]")) { confirmRunStop(); return; }
  if (target.matches("[data-run-stop-review]")) { if (activeRunStop?.panel.parentElement instanceof HTMLElement) reviewRunStop(activeRunStop); return; }
  if (target.matches("[data-run-message-cancel]")) { closeActiveRunMessage(); return; }
  if (target.matches("[data-run-message-review]")) { reviewRunMessage(); return; }
  if (target.matches("[data-run-message-confirm]")) { confirmRunMessage(); return; }
  if (target.matches("[data-run-response-cancel]")) { closeActiveRunResponse(); return; }
  if (target.matches("[data-run-response-review]")) { reviewRunResponse(); return; }
  if (target.matches("[data-run-response-confirm]")) { confirmRunResponse(); return; }
  if (target.matches("[data-run-timeline-open]")) {
    const run = renderedRuns.get(target.dataset.runId); const card = target.closest(".run-card");
    if (run && card instanceof HTMLElement && target instanceof HTMLButtonElement) openRunTimeline(run, card, target);
    return;
  }
  if (target.matches("[data-run-stop-open]")) {
    const run = renderedRuns.get(target.dataset.runId); const card = target.closest(".run-card");
    if (run && card instanceof HTMLElement && target instanceof HTMLButtonElement) openRunStop(run, card, target);
    return;
  }
  if (target.matches("[data-run-message-open]")) {
    const run = renderedRuns.get(target.dataset.runId); const card = target.closest(".run-card");
    if (run && card instanceof HTMLElement && target instanceof HTMLButtonElement) openRunMessage(run, card, target);
    return;
  }
  if (target.matches("[data-run-response-open]")) {
    const run = renderedRuns.get(target.dataset.runId); const card = target.closest(".run-card");
    if (run && card instanceof HTMLElement && target instanceof HTMLButtonElement) openRunResponse(run, card, target);
    return;
  }
  hideNavigationTooltip();
  if (target.matches("[data-nav-open]")) {
    openNavigation();
  } else if (target.matches("[data-nav-link]")) {
    closeNavigation(false);
  } else {
    closeNavigation();
  }
});

document.addEventListener("focusin", (event) => {
  if (!runtimeStarted) return;
  const { sidebar, openButton } = shellElements();
  navigationOwnsFocus = event.target === openButton || Boolean(sidebar?.contains(event.target));
  const link = event.target instanceof Element ? event.target.closest(".nav-link[data-nav-link]") : null;
  showNavigationTooltip(link);
});

document.addEventListener("focusout", (event) => {
  if (!runtimeStarted) return;
  if (event.target instanceof Element && event.target.closest(".nav-link[data-nav-link]")) {
    hideNavigationTooltip();
  }
});

document.addEventListener("pointerover", (event) => {
  if (!runtimeStarted) return;
  const link = event.target instanceof Element ? event.target.closest(".nav-link[data-nav-link]") : null;
  showNavigationTooltip(link);
});

document.addEventListener("pointerout", (event) => {
  if (!runtimeStarted) return;
  const link = event.target instanceof Element ? event.target.closest(".nav-link[data-nav-link]") : null;
  if (link && !(event.relatedTarget instanceof Node && link.contains(event.relatedTarget))) {
    hideNavigationTooltip();
  }
});

document.addEventListener("scroll", (event) => {
  if (!runtimeStarted) return;
  const { sidebar } = shellElements();
  const activeElement = document.activeElement;
  const focusedNavigationLink = activeElement instanceof Element
    ? activeElement.closest(".nav-link[data-nav-link]")
    : null;
  if (sidebar?.contains(event.target) && focusedNavigationLink) {
    showNavigationTooltip(focusedNavigationLink);
    return;
  }
  hideNavigationTooltip();
}, true);

document.addEventListener("keydown", (event) => {
  if (!root.dataset.navOpen) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeNavigation();
    return;
  }
  const { sidebar } = shellElements();
  if (event.key !== "Tab" || !(sidebar instanceof HTMLElement)) return;

  const focusable = Array.from(
    sidebar.querySelectorAll("a[href], button:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])"),
  ).filter((element) => element instanceof HTMLElement && !element.hidden);
  if (focusable.length === 0) return;

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});

contrastMedia.addEventListener("change", () => {
  if (runtimeStarted && root.dataset.contrastPreference === "system") applyContrast("system");
});

compactNavigation.addEventListener("change", () => {
  if (runtimeStarted) hideNavigationTooltip();
});

mobileNavigation.addEventListener("change", () => {
  if (!runtimeStarted) return;
  const { sidebar, openButton, currentNavigationLink } = shellElements();
  const activeElement = document.activeElement;
  const focusNeedsMove = Boolean(root.dataset.navOpen)
    || navigationOwnsFocus
    || activeElement === openButton
    || Boolean(sidebar?.contains(activeElement));
  closeNavigation(false);
  if (!focusNeedsMove) return;
  const focusTarget = mobileNavigation.matches ? openButton : currentNavigationLink;
  if (focusTarget instanceof HTMLElement) focusTarget.focus();
});

function startShellRuntime() {
  if (runtimeStarted) return;
  runtimeStarted = true;
  root.dataset.shellRuntime = "ready";
  applyContrast(root.dataset.contrastPreference || storedContrast());
  synchronizeShell();
  new MutationObserver(synchronizeShell).observe(document.body, {
    childList: true,
    subtree: true,
  });
}

const frameworkRuntime = document.querySelector('script[src^="/_next/static/"][src*=".js"]');
if (root.dataset.shellHydrated === "true") {
  requestAnimationFrame(startShellRuntime);
} else if (frameworkRuntime) {
  window.addEventListener("mentat:shell-hydrated", () => requestAnimationFrame(startShellRuntime), { once: true });
} else if (document.readyState === "complete") {
  requestAnimationFrame(startShellRuntime);
} else {
  window.addEventListener("load", () => requestAnimationFrame(startShellRuntime), { once: true });
}
