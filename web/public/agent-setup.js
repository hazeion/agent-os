// Loaded only by the explicit setup action on the script-light Agents page.
const panels = new WeakMap();
const fields = (value, names) => value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === names;
const validName = (value) => typeof value === "string" && [...value].length > 0 && [...value].length <= 120 && value.trim() === value && !/\p{C}/u.test(value);
const validAgent = (agent) => fields(agent, "id,name") && typeof agent.id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(agent.id) && validName(agent.name);

async function request(action, body, fetcher) {
  const response = await fetcher(`/api/agent-setup/${action}`, { method: "POST", cache: "no-store", redirect: "error", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(20_000) });
  if (response.status !== 200 || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || !response.body) throw new Error("setup_unverified");
  const reader = response.body.getReader(); const chunks = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > 4096) { await reader.cancel(); throw new Error("setup_unverified"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  if (value?.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready") throw new Error("setup_unverified");
  const valid = action === "check"
    ? fields(value, "agent,runtime,schema_version,service,state,status") && ["available", "already_configured", "hermes_missing", "hermes_unconfigured", "remote_selected", "registry_full", "unavailable"].includes(value.state) && (value.state === "already_configured" ? validAgent(value.agent) : value.agent === null)
    : action === "preview"
      ? fields(value, "confirmation_id,name,runtime,schema_version,service,status") && value.name === body.name && validName(value.name) && typeof value.confirmation_id === "string" && /^[0-9a-f]{64}$/u.test(value.confirmation_id)
      : fields(value, "agent,runtime,schema_version,service,status") && validAgent(value.agent) && value.agent.name === body.name;
  if (!valid) throw new Error("setup_unverified");
  return value;
}

export function openAgentSetup(panel, refreshAgents = () => undefined, fetcher = fetch) {
  if (panels.has(panel)) { panels.get(panel).open(); return; }
  const find = (name) => panel.querySelector(`[data-agent-setup-${name}]`);
  const body = find("body"), form = find("form"), input = form.querySelector("input"), notice = find("notice"), review = find("review"), confirm = find("confirm"), previewButton = find("preview"), check = find("check"), result = find("result");
  let busy = false, preview = null;
  function discardPreview() { preview = null; review.hidden = true; confirm.hidden = true; }
  function setBusy(value) { busy = value; input.disabled = value; check.disabled = value; confirm.disabled = value; previewButton.disabled = value || !validName(input.value); }
  function showAgent(agent) { form.hidden = true; result.hidden = false; find("result-name").textContent = `${agent.name} is available in the canonical Agent registry.`; void refreshAgents(); }
  function open() { body.hidden = false; find("open").setAttribute("aria-expanded", "true"); check.focus(); }
  async function checkSetup() {
    if (busy) return;
    setBusy(true); discardPreview(); form.hidden = true; result.hidden = true; notice.textContent = "Checking local Hermes configuration…";
    try {
      const value = await request("check", {}, fetcher);
      if (!panel.isConnected) return;
      const messages = {
        available: "Local Hermes configuration found. Enter a name and review the Agent before creating it.",
        already_configured: "This local Hermes identity already has a Mentat Agent. Use the existing Agent below.",
        hermes_missing: "Hermes is not available in the Mentat server environment. Install Hermes, complete its setup, then restart Mentat and Check setup.",
        hermes_unconfigured: "Configure the local default identity with Hermes setup in your terminal, then Check setup. Credentials stay in Hermes.",
        remote_selected: "Remote Hermes is selected. This creation flow supports local Hermes only. Return Mentat to local Hermes using the supported connection setup, then Check setup.",
        registry_full: "The canonical Agent registry is full. Use an existing Agent; this flow cannot add another identity.",
        unavailable: "Mentat could not verify local Hermes configuration. Check that Hermes works in your terminal, then Check setup again.",
      };
      notice.textContent = messages[value.state];
      if (value.state === "available") { form.hidden = false; input.disabled = false; input.focus(); }
      else if (value.agent) showAgent(value.agent);
    } catch { if (panel.isConnected) notice.textContent = "Setup could not be verified. Check setup again when the local connection is available."; }
    finally { setBusy(false); }
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); if (busy || form.hidden || !validName(input.value)) return;
    const name = input.value; setBusy(true); discardPreview(); notice.textContent = "Reviewing the exact Agent configuration…";
    try {
      const value = await request("preview", { name }, fetcher);
      if (!panel.isConnected || input.value !== name) return;
      preview = value; review.textContent = `Create “${value.name}” using the existing local Hermes configuration. This creates a Mentat Agent only; it does not start work or change Hermes settings.`; review.hidden = false; confirm.hidden = false; notice.textContent = "Review these effects, then confirm creation."; confirm.disabled = false; confirm.focus();
    } catch { if (panel.isConnected) notice.textContent = "The Agent could not be reviewed. Your name was kept. Check setup and review again."; }
    finally { setBusy(false); }
  });
  confirm.addEventListener("click", async () => {
    if (busy || !preview || preview.name !== input.value) return;
    const selected = preview; setBusy(true); notice.textContent = "Creating the confirmed Mentat Agent…";
    try {
      const value = await request("confirm", { name: selected.name, confirmation_id: selected.confirmation_id, confirmed: true }, fetcher);
      if (!panel.isConnected) return;
      showAgent(value.agent); notice.textContent = "Agent creation verified. Open Home when you want to start a Conversation.";
    } catch {
      form.hidden = true;
      if (panel.isConnected) notice.textContent = "Agent creation could not be verified. Check setup before trying again; the Agent may already exist. Your name was kept.";
    } finally { discardPreview(); setBusy(false); }
  });
  input.addEventListener("input", () => { discardPreview(); setBusy(busy); });
  check.addEventListener("click", () => void checkSetup());
  find("close").addEventListener("click", () => { body.hidden = true; find("open").setAttribute("aria-expanded", "false"); find("open").focus(); });
  panels.set(panel, { open }); open(); void checkSetup();
}
