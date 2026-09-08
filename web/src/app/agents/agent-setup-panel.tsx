import Link from "next/link.js";

export function AgentSetupPanel() {
  return <section className="agent-setup" data-agent-setup-root>
    <div className="agents-toolbar"><div><h2>Create an Agent</h2><p>Name an Agent for your configured local Hermes runtime, or find runtime setup instructions.</p></div><button aria-expanded="false" className="agent-refresh" data-agent-setup-open type="button">Create Agent / Setup</button></div>
    <div data-agent-setup-body hidden>
      <div className="agent-setup-runtimes">
        <section><h3>Hermes</h3><p>This flow connects one named Mentat Agent to the configured local Hermes default identity. It does not create or clone a Hermes profile. Provider setup stays in Hermes.</p><button data-agent-setup-check type="button">Check setup</button></section>
        <section><h3>Codex</h3><p>Codex uses one local identity, normally shown as Direct Agent. Open Home to choose it and check sign-in. To sign in, run <code>codex login</code> in your terminal.</p><Link href="/" prefetch={false}>Open Home for Codex</Link></section>
        <section><h3>Vercel</h3><p>Vercel setup and Agent creation require a stopped Mentat server and exact CLI preview/confirmation. Use <code>mentat vercel --help</code> for the supported setup commands.</p></section>
      </div>
      <p aria-live="polite" data-agent-setup-notice role="status">Check local Hermes setup to continue.</p>
      <form data-agent-setup-form hidden>
        <label htmlFor="agent-setup-name">Agent name</label><input aria-describedby="agent-setup-name-help" autoComplete="off" id="agent-setup-name" name="name" required /><p id="agent-setup-name-help">Use 1–120 characters, with no leading or trailing spaces.</p>
        <p>Configuration discovery does not verify sign-in, model access, or successful execution. Files and Inbox task creation are separate opt-ins.</p>
        <p data-agent-setup-review hidden />
        <div className="agent-setup-actions"><button data-agent-setup-preview type="submit">Review Agent</button><button data-agent-setup-confirm hidden type="button">Confirm create Agent</button></div>
      </form>
      <p data-agent-setup-result hidden><span data-agent-setup-result-name /> <Link href="/" prefetch={false}>Open Home</Link> and choose this Agent to start a Conversation.</p>
      <button data-agent-setup-close type="button">Close setup</button>
    </div>
  </section>;
}
