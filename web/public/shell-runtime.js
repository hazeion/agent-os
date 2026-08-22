const root = document.documentElement;
const storageKey = "mentat-contrast-v1";
const contrastMedia = window.matchMedia("(prefers-contrast: more)");
const mobileNavigation = window.matchMedia("(max-width: 900px)");
const compactNavigation = window.matchMedia("(min-width: 901px) and (max-width: 1199px)");
const supportedContrast = new Set(["system", "standard", "high"]);

let bridgeRequest = 0;
let bridgeState = "checking";
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

function synchronizeShell() {
  if (!document.querySelector(".app-shell")) return;
  applyContrast(root.dataset.contrastPreference || storedContrast());
  setSidebarAvailability(Boolean(root.dataset.navOpen));
  applyBridgeState();

  if (window.location.pathname !== observedPath) {
    hideNavigationTooltip();
    observedPath = window.location.pathname;
    requestAnimationFrame(() => requestAnimationFrame(refreshBridgeStatus));
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
    ? event.target.closest("[data-nav-open], [data-nav-close], [data-nav-backdrop], [data-nav-link]")
    : null;
  if (!target) return;
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

document.addEventListener("scroll", () => {
  if (runtimeStarted) hideNavigationTooltip();
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
