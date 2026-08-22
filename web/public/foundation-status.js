(() => {
  "use strict";

  const status = document.querySelector("[data-bridge-status]");
  const dot = document.querySelector("[data-bridge-status-dot]");
  const text = document.querySelector("[data-bridge-status-text]");
  if (!status || !dot || !text) return;

  function render(kind, label) {
    dot.className = `runtime-state__dot runtime-state__dot--${kind}`;
    text.textContent = label;
  }

  async function check() {
    try {
      const response = await fetch("/api/bridge/health", {
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (
        !response.ok
        || payload?.status !== "ready"
        || typeof payload.mentat_version !== "string"
      ) {
        throw new Error("bridge_unavailable");
      }
      render("ready", `Connected · Mentat ${payload.mentat_version}`);
    } catch {
      render("unavailable", "Bridge unavailable");
    }
  }

  requestAnimationFrame(() => requestAnimationFrame(() => void check()));
})();
