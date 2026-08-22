export function BridgeStatus() {
  return (
    <div className="bridge-status" aria-atomic="true" aria-live="polite" data-bridge-status>
      <span className="bridge-status-dot" aria-hidden="true" data-bridge-status-dot />
      <span className="bridge-status-text" data-bridge-status-text>Checking Python</span>
      <span aria-hidden="true" className="bridge-status-compact" data-bridge-status-compact>
        Check
      </span>
    </div>
  );
}
