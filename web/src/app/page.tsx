import { BridgeStatus } from "./bridge-status";

export default function RuntimeFoundationPage() {
  return (
    <>
      <main id="main-content" className="min-h-screen">
      <div className="ambient-grid" aria-hidden="true" />
      <div className="foundation-shell">
        <header className="foundation-header">
          <a className="brand" href="#main-content" aria-label="Mentat runtime foundation home">
            <span className="brand__mark" aria-hidden="true">M</span>
            <span>Mentat</span>
          </a>
          <span className="slice-label">Pivot 2A-A</span>
        </header>

        <section className="hero" aria-labelledby="foundation-title">
          <p className="hero__eyebrow">Local runtime foundation</p>
          <h1 id="foundation-title">The new Mentat shell is running on Node.</h1>
          <p className="hero__summary">
            Next.js now owns this browser-facing preview while Python keeps local
            authority, storage, and runtime capabilities behind a private bridge.
          </p>
        </section>

        <section className="runtime-grid" aria-label="Runtime readiness">
          <section className="runtime-card" aria-labelledby="gateway-heading">
            <div className="runtime-card__icon" aria-hidden="true">N</div>
            <div>
              <p className="runtime-card__eyebrow">Browser gateway</p>
              <h2 id="gateway-heading">Next.js on Node 24</h2>
              <p className="runtime-card__description">
                Route-split rendering and a fixed backend-for-frontend boundary.
              </p>
            </div>
            <div className="runtime-state">
              <span className="runtime-state__dot runtime-state__dot--ready" aria-hidden="true" />
              <span>Gateway ready</span>
            </div>
          </section>
          <BridgeStatus />
        </section>

        <aside className="compatibility-note" aria-label="Compatibility status">
          <span aria-hidden="true">↳</span>
          <p>
            This is an additive source preview. The existing Mentat dashboard remains
            the default compatibility surface until the replacement shell completes
            its functional and Lighthouse gates.
          </p>
        </aside>
      </div>
      </main>
      <script
        data-mentat-foundation-status
        defer
        src="/foundation-status.js"
      />
    </>
  );
}
