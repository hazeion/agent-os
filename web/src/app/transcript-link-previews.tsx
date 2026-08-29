const MAXIMUM_LINK_BYTES = 2_048;
const MAXIMUM_PREVIEWS = 3;
const MAXIMUM_TITLE_CODE_POINTS = 200;
const MAXIMUM_DESCRIPTION_CODE_POINTS = 500;
const MAXIMUM_HOST_CODE_POINTS = 253;
const HTTPS_CANDIDATE = /https:\/\/[^\s<>"'`]+/giu;
const BIDI_CONTROL = /[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/gu;
const OPAQUE_IMAGE_ID = /^[A-Za-z0-9_-]{22,128}$/u;
const DNS_HOST = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/u;
const TRAILING_PUNCTUATION = /[,.!?;:]+$/u;
const SPECIAL_USE_SUFFIXES = ["localhost", "local", "home.arpa", "test", "invalid", "example"];

export type LinkPreviewStatus = "blocked" | "disabled" | "pending" | "ready" | "unavailable";

export type SafeLinkPreviewProjection = Readonly<{
  candidateOrdinal: number;
  description?: string | null;
  displayHost?: string | null;
  imageAlt?: string | null;
  imageId?: string | null;
  status: LinkPreviewStatus;
  title?: string | null;
}>;

function boundedSafeText(value: string | null | undefined, maximum: number): string {
  if (typeof value !== "string") return "";
  const clean = value.replace(BIDI_CONTROL, "�").replace(/[\u0000-\u001f\u007f-\u009f]/gu, " ").replace(/\s+/gu, " ").trim();
  return Array.from(clean).slice(0, maximum).join("");
}

function isSpecialUseHost(hostname: string): boolean {
  return SPECIAL_USE_SUFFIXES.some((suffix) => hostname === suffix || hostname.endsWith(`.${suffix}`));
}

function isDisplayHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/\.$/u, "");
  if (/^[0-9a-f:]{2,45}$/u.test(host)) {
    try { return new URL(`https://[${host}]/`).hostname === `[${host}]`; } catch { return false; }
  }
  return DNS_HOST.test(host)
    && host.includes(".")
    && !isSpecialUseHost(host)
    && !/^\d+(?:\.\d+){3}$/u.test(host);
}

function trimCandidate(value: string): string {
  let candidate = value.replace(TRAILING_PUNCTUATION, "");
  for (const [opening, closing] of [["(", ")"], ["[", "]"], ["{", "}"]] as const) {
    while (candidate.endsWith(closing) && candidate.split(opening).length < candidate.split(closing).length) {
      candidate = candidate.slice(0, -1);
    }
  }
  return candidate;
}

/**
 * This is a deliberately narrow display allowlist, not the preview network
 * policy. Python remains the only authority that may resolve or fetch a URL.
 */
export function safePublicHttpsDisplayHref(value: string): string | null {
  const href = trimCandidate(value);
  if (!href || /[^\x20-\x7e]/u.test(href) || href.includes("\\") || /%5c/iu.test(href) || /%(?![0-9a-f]{2})/iu.test(href)) return null;
  if (new TextEncoder().encode(href).length > MAXIMUM_LINK_BYTES) return null;
  let parsed: URL;
  try {
    parsed = new URL(href);
  } catch {
    return null;
  }
  const authority = href.slice("https://".length).split(/[/?#]/u, 1)[0];
  if (authority.includes("%") || parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.port && parsed.port !== "443") return null;
  if (!isDisplayHost(parsed.hostname) || parsed.href.startsWith("https://[") || parsed.href.includes("%5C")) return null;
  return href;
}

function backendApprovedHttpsHref(value: string): string | null {
  const href = trimCandidate(value);
  if (!href || href.includes("\\") || /%5c/iu.test(href) || /%(?![0-9a-f]{2})/iu.test(href) || /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u.test(href)) return null;
  if (new TextEncoder().encode(href).length > MAXIMUM_LINK_BYTES) return null;
  try {
    const parsed = new URL(href);
    const authority = href.slice("https://".length).split(/[/?#]/u, 1)[0];
    if (authority.includes("%") || parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.port && parsed.port !== "443") return null;
  } catch {
    return null;
  }
  return href;
}

export function backendTrustedLinkHrefs(content: string, previews: readonly SafeLinkPreviewProjection[]): ReadonlySet<string> {
  const candidates = Array.from(content.matchAll(HTTPS_CANDIDATE), (match) => trimCandidate(match[0])).slice(0, MAXIMUM_PREVIEWS);
  const trusted = new Set<string>();
  for (const preview of previews) {
    if (preview.status === "blocked") continue;
    const candidate = candidates[preview.candidateOrdinal - 1];
    const href = candidate ? backendApprovedHttpsHref(candidate) : null;
    if (href) trusted.add(href);
  }
  return trusted;
}

export function linkifiedText(value: string, keyPrefix = "text", backendTrusted: ReadonlySet<string> = new Set()) {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  HTTPS_CANDIDATE.lastIndex = 0;
  for (const match of value.matchAll(HTTPS_CANDIDATE)) {
    const offset = match.index ?? 0;
    const candidate = trimCandidate(match[0]);
    const href = safePublicHttpsDisplayHref(candidate) ?? (backendTrusted.has(candidate) ? backendApprovedHttpsHref(candidate) : null);
    if (!href) continue;
    if (offset > cursor) nodes.push(value.slice(cursor, offset));
    nodes.push(
      <a
        href={href}
        key={`${keyPrefix}-link-${offset}`}
        referrerPolicy="no-referrer"
        rel="noopener noreferrer"
        target="_blank"
      >
        {href}
      </a>,
    );
    cursor = offset + href.length;
  }
  if (cursor < value.length) nodes.push(value.slice(cursor));
  return nodes;
}

function previewStatusText(status: LinkPreviewStatus): string {
  if (status === "pending") return "Preview loading";
  if (status === "blocked") return "Preview blocked for safety";
  if (status === "disabled") return "Rich link previews are off";
  if (status === "unavailable") return "Preview unavailable";
  return "Link preview";
}

function safeProjection(value: SafeLinkPreviewProjection): SafeLinkPreviewProjection | null {
  if (!Number.isInteger(value.candidateOrdinal) || value.candidateOrdinal < 1 || value.candidateOrdinal > MAXIMUM_PREVIEWS) return null;
  if (!["blocked", "disabled", "pending", "ready", "unavailable"].includes(value.status)) return null;
  const rawDisplayHost = value.displayHost;
  const displayHost = typeof rawDisplayHost === "string" && Array.from(rawDisplayHost).length <= MAXIMUM_HOST_CODE_POINTS
    ? boundedSafeText(rawDisplayHost, MAXIMUM_HOST_CODE_POINTS).toLowerCase()
    : "";
  return {
    candidateOrdinal: value.candidateOrdinal,
    description: boundedSafeText(value.description, MAXIMUM_DESCRIPTION_CODE_POINTS) || null,
    displayHost: isDisplayHost(displayHost) ? displayHost : null,
    imageAlt: boundedSafeText(value.imageAlt, MAXIMUM_TITLE_CODE_POINTS) || null,
    imageId: typeof value.imageId === "string" && OPAQUE_IMAGE_ID.test(value.imageId) ? value.imageId : null,
    status: value.status,
    title: boundedSafeText(value.title, MAXIMUM_TITLE_CODE_POINTS) || null,
  };
}

export function TranscriptLinkPreviews({ messageLabel = "message", onRetry, previews, retrying = false }: Readonly<{
  messageLabel?: string;
  onRetry?: () => void;
  previews: readonly SafeLinkPreviewProjection[];
  retrying?: boolean;
}>) {
  const seen = new Set<number>();
  const safe = previews
    .map(safeProjection)
    .filter((preview): preview is SafeLinkPreviewProjection => preview !== null)
    .sort((left, right) => left.candidateOrdinal - right.candidateOrdinal)
    .filter((preview) => {
      if (seen.has(preview.candidateOrdinal)) return false;
      seen.add(preview.candidateOrdinal);
      return true;
    })
    .slice(0, MAXIMUM_PREVIEWS);

  if (!safe.length) return null;
  return (
    <section aria-label="Link previews" className="transcript-link-previews">
      {safe.map((preview) => {
        const label = previewStatusText(preview.status);
        const ready = preview.status === "ready";
        return (
          <article aria-atomic="true" aria-live="polite" className={`transcript-link-preview transcript-link-preview-${preview.status}`} data-candidate-ordinal={preview.candidateOrdinal} key={preview.candidateOrdinal}>
            {ready && preview.imageId ? <>
              {/* eslint-disable-next-line @next/next/no-img-element -- the fixed same-origin route already returns the transformed asset */}
              <img alt={preview.imageAlt ?? ""} decoding="async" loading="lazy" src={`/api/link-previews/images/${encodeURIComponent(preview.imageId)}`} />
            </> : null}
            <div className="transcript-link-preview-body">
              <span className="transcript-link-preview-status">{label}</span>
              {ready && preview.title ? <strong>{preview.title}</strong> : null}
              {ready && preview.description ? <p>{preview.description}</p> : null}
              {preview.displayHost ? <span className="transcript-link-preview-host">{preview.displayHost}</span> : null}
              {!ready ? <p>The original link remains available above.</p> : null}
            </div>
          </article>
        );
      })}
      {onRetry && safe.some((preview) => preview.status === "blocked" || preview.status === "unavailable")
        ? <button aria-label={`Retry previews for ${messageLabel}`} className="transcript-link-preview-retry" disabled={retrying} onClick={onRetry} type="button">{retrying ? "Retrying previews…" : "Retry previews"}</button>
        : null}
    </section>
  );
}
