export function BridgeStatus() {
  return (
    <section className="runtime-card" aria-labelledby="bridge-heading">
      <div className="runtime-card__icon" aria-hidden="true">P</div>
      <div>
        <p className="runtime-card__eyebrow">Authority boundary</p>
        <h2 id="bridge-heading">Python Local Bridge</h2>
        <p className="runtime-card__description">
          Durable state and local capabilities remain behind the Python boundary.
        </p>
      </div>
      <div className="runtime-state" aria-live="polite" aria-atomic="true" data-bridge-status>
        <span
          className="runtime-state__dot runtime-state__dot--checking"
          aria-hidden="true"
          data-bridge-status-dot
        />
        <span data-bridge-status-text>Checking private bridge</span>
      </div>
    </section>
  );
}
