type PanelProps = Readonly<{
  children: React.ReactNode;
  eyebrow?: string;
  title: string;
}>;

export function Panel({ children, eyebrow, title }: PanelProps) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          {eyebrow ? <p className="panel-eyebrow">{eyebrow}</p> : null}
          <h2>{title}</h2>
        </div>
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

type FoundationStateProps = Readonly<{
  detail: string;
  label: string;
}>;

export function FoundationState({ detail, label }: FoundationStateProps) {
  return (
    <div className="foundation-state">
      <span className="foundation-state-dot" aria-hidden="true" />
      <div>
        <p className="foundation-state-label">{label}</p>
        <p className="foundation-state-detail">{detail}</p>
      </div>
    </div>
  );
}
