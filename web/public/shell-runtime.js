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
    ? event.target.closest("[data-agents-refresh], [data-tasks-refresh], [data-nav-open], [data-nav-close], [data-nav-backdrop], [data-nav-link]")
    : null;
  if (!target) return;
  if (target.matches("[data-agents-refresh]")) {
    refreshAgents();
    return;
  }
  if (target.matches("[data-tasks-refresh]")) { refreshTasks(); return; }
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
