"use client";

import { Fragment, memo, useMemo, useState } from "react";

import { backendTrustedLinkHrefs, linkifiedText, TranscriptLinkPreviews, type SafeLinkPreviewProjection } from "./transcript-link-previews";

const MAXIMUM_DISPLAY_CODE_POINTS = 20_000;
const MAXIMUM_RENDER_UNITS = 512;
const MAXIMUM_TRANSCRIPT_RENDER_UNITS = 8_000;
const BIDI_CONTROL = /[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/gu;
const INLINE_TOKEN = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*)/gu;
const CODE_TOKEN = /(<!--[\s\S]*?-->|\/\*[\s\S]*?\*\/|\/\/[^\n]*|#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b\d+(?:\.\d+)?\b|\b[A-Za-z_$][\w$]*\b)/gu;

type CopyText = (text: string) => Promise<void>;

type MarkdownBlock =
  | { kind: "blockquote"; text: string }
  | { code: string; kind: "code"; language: string; ordinal: number }
  | { depth: number; kind: "heading"; text: string }
  | { items: string[]; kind: "list"; ordered: boolean }
  | { kind: "paragraph"; text: string };

function replaceBidiControls(value: string): string {
  return value.replace(BIDI_CONTROL, "�");
}

function boundedContent(value: string): { text: string; truncated: boolean } {
  const codePoints: string[] = [];
  let truncated = false;
  for (const codePoint of value) {
    if (codePoints.length === MAXIMUM_DISPLAY_CODE_POINTS) {
      truncated = true;
      break;
    }
    codePoints.push(codePoint);
  }
  return {
    text: replaceBidiControls(codePoints.join("")),
    truncated,
  };
}

function parseMarkdown(value: string): MarkdownBlock[] {
  const lines = value.replace(/\r\n?/gu, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let index = 0;
  let codeOrdinal = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    const fence = /^\s*```([A-Za-z0-9_+-]{0,24})\s*$/u.exec(line);
    if (fence) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/u.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      codeOrdinal += 1;
      blocks.push({ code: code.join("\n"), kind: "code", language: fence[1].toLowerCase(), ordinal: codeOrdinal });
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/u.exec(line);
    if (heading) {
      blocks.push({ depth: heading[1].length, kind: "heading", text: heading[2] });
      index += 1;
      continue;
    }
    const quote = /^\s*>\s?(.*)$/u.exec(line);
    if (quote) {
      const quoted = [quote[1]];
      index += 1;
      while (index < lines.length) {
        const continuation = /^\s*>\s?(.*)$/u.exec(lines[index]);
        if (!continuation) break;
        quoted.push(continuation[1]);
        index += 1;
      }
      blocks.push({ kind: "blockquote", text: quoted.join("\n") });
      continue;
    }
    const listItem = /^\s*(?:(\d+)\.|([-*]))\s+(.+)$/u.exec(line);
    if (listItem) {
      const ordered = listItem[1] !== undefined;
      const items = [listItem[3]];
      index += 1;
      while (index < lines.length) {
        const continuation = /^\s*(?:(\d+)\.|([-*]))\s+(.+)$/u.exec(lines[index]);
        if (!continuation || (continuation[1] !== undefined) !== ordered) break;
        items.push(continuation[3]);
        index += 1;
      }
      blocks.push({ items, kind: "list", ordered });
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !/^\s*```/u.test(lines[index])
      && !/^(#{1,3})\s+/u.test(lines[index])
      && !/^\s*>/u.test(lines[index])
      && !/^\s*(?:(\d+)\.|[-*])\s+/u.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ kind: "paragraph", text: paragraph.join("\n") });
  }
  return blocks;
}

function tokenUnits(value: string, pattern: RegExp): number {
  pattern.lastIndex = 0;
  let units = 1;
  for (const match of value.matchAll(pattern)) {
    units += match[0].length ? 2 : 0;
    if (units > MAXIMUM_RENDER_UNITS) return units;
  }
  return units;
}

function renderUnits(blocks: MarkdownBlock[]): number {
  let units = blocks.length;
  for (const block of blocks) {
    if (block.kind === "list") {
      units += block.items.length;
      for (const item of block.items) units += tokenUnits(item, INLINE_TOKEN);
    } else if (block.kind === "code") {
      units += tokenUnits(block.code, CODE_TOKEN);
    } else {
      units += tokenUnits(block.text, INLINE_TOKEN);
    }
    if (units > MAXIMUM_RENDER_UNITS) return units;
  }
  return units;
}

export function transcriptContentRenderUnits(content: string): number {
  return renderUnits(parseMarkdown(boundedContent(content).text));
}

function inlineContent(value: string, backendTrusted: ReadonlySet<string>) {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  INLINE_TOKEN.lastIndex = 0;
  for (const match of value.matchAll(INLINE_TOKEN)) {
    const offset = match.index ?? 0;
    if (offset > cursor) nodes.push(...linkifiedText(value.slice(cursor, offset), `inline-${cursor}`, backendTrusted));
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(<code key={`inline-${offset}`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={`strong-${offset}`}>{linkifiedText(token.slice(2, -2), `strong-${offset}`, backendTrusted)}</strong>);
    } else {
      nodes.push(<em key={`em-${offset}`}>{linkifiedText(token.slice(1, -1), `em-${offset}`, backendTrusted)}</em>);
    }
    cursor = offset + token.length;
  }
  if (cursor < value.length) nodes.push(...linkifiedText(value.slice(cursor), `inline-${cursor}`, backendTrusted));
  return nodes;
}

const KEYWORDS = new Set([
  "as", "async", "await", "break", "case", "catch", "class", "const", "continue",
  "def", "do", "else", "export", "extends", "false", "finally", "for", "from",
  "function", "if", "import", "in", "interface", "let", "new", "none", "null",
  "return", "switch", "throw", "true", "try", "type", "undefined", "var", "while",
  "with", "yield",
]);

function highlightedCode(code: string) {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  CODE_TOKEN.lastIndex = 0;
  for (const match of code.matchAll(CODE_TOKEN)) {
    const offset = match.index ?? 0;
    if (offset > cursor) nodes.push(code.slice(cursor, offset));
    const token = match[0];
    let className = "";
    if (token.startsWith("//") || token.startsWith("#") || token.startsWith("/*") || token.startsWith("<!--")) {
      className = "transcript-token-comment";
    } else if (/^["'`]/u.test(token)) {
      className = "transcript-token-string";
    } else if (/^\d/u.test(token)) {
      className = "transcript-token-number";
    } else if (KEYWORDS.has(token.toLowerCase())) {
      className = "transcript-token-keyword";
    }
    nodes.push(className
      ? <span className={className} key={`token-${offset}`}>{token}</span>
      : <Fragment key={`plain-${offset}`}>{token}</Fragment>);
    cursor = offset + token.length;
  }
  if (cursor < code.length) nodes.push(code.slice(cursor));
  return nodes;
}

function languageLabel(language: string): string {
  const labels: Record<string, string> = {
    bash: "Shell", css: "CSS", html: "HTML", js: "JavaScript", javascript: "JavaScript",
    json: "JSON", jsx: "JSX", py: "Python", python: "Python", sh: "Shell", shell: "Shell",
    ts: "TypeScript", tsx: "TSX", typescript: "TypeScript", xml: "XML", zsh: "Shell",
  };
  return labels[language] ?? (language ? language.toUpperCase() : "Plain text");
}

async function defaultCopyText(value: string): Promise<void> {
  if (!navigator.clipboard?.writeText) throw new Error("clipboard_unavailable");
  await navigator.clipboard.writeText(value);
}

export const TranscriptContent = memo(function TranscriptContent({
  content,
  copyText = defaultCopyText,
  forcePlainText = false,
  linkPreviewConversationId,
  linkPreviews = [],
  linkPreviewMessageId,
  linkPreviewMessageRevision,
  linkPreviewRetrying = false,
  messageLabel = "message",
  onRetryLinkPreviews,
  showLinkPreviewCards = true,
}: Readonly<{
  content: string;
  copyText?: CopyText;
  forcePlainText?: boolean;
  linkPreviewConversationId?: string;
  linkPreviews?: readonly SafeLinkPreviewProjection[];
  linkPreviewMessageId?: string;
  linkPreviewMessageRevision?: number;
  linkPreviewRetrying?: boolean;
  messageLabel?: string;
  onRetryLinkPreviews?: (conversationId: string, messageId: string, revision: number) => void;
  showLinkPreviewCards?: boolean;
}>) {
  const bounded = useMemo(() => boundedContent(content), [content]);
  const blocks = useMemo(() => forcePlainText ? [] : parseMarkdown(bounded.text), [bounded.text, forcePlainText]);
  const backendTrusted = useMemo(() => backendTrustedLinkHrefs(bounded.text, linkPreviews), [bounded.text, linkPreviews]);
  const simplified = useMemo(() => forcePlainText || renderUnits(blocks) > MAXIMUM_RENDER_UNITS, [blocks, forcePlainText]);
  const [copyStatus, setCopyStatus] = useState("");

  async function copy(value: string, label: string) {
    try {
      await copyText(value);
      setCopyStatus(`${label} copied.`);
    } catch {
      setCopyStatus(`${label} could not be copied.`);
    }
  }

  return (
    <div className="transcript-content" dir="auto">
      <div className="transcript-content-actions">
        <button aria-label={`Copy ${messageLabel}`} onClick={() => void copy(bounded.text, "Message")} type="button">Copy</button>
      </div>
      <div className="transcript-markdown">
        {simplified ? <p dir="auto">{linkifiedText(bounded.text, "plain", backendTrusted)}</p> : blocks.map((block, index) => {
          if (block.kind === "heading") {
            const Tag = block.depth === 1 ? "h2" : block.depth === 2 ? "h3" : "h4";
            return <Tag dir="auto" key={`heading-${index}`}>{inlineContent(block.text, backendTrusted)}</Tag>;
          }
          if (block.kind === "blockquote") {
            return <blockquote dir="auto" key={`quote-${index}`}>{inlineContent(block.text, backendTrusted)}</blockquote>;
          }
          if (block.kind === "list") {
            const Tag = block.ordered ? "ol" : "ul";
            return <Tag key={`list-${index}`}>{block.items.map((item, itemIndex) => <li dir="auto" key={`item-${itemIndex}`}>{inlineContent(item, backendTrusted)}</li>)}</Tag>;
          }
          if (block.kind === "code") {
            const label = languageLabel(block.language);
            return <div className="transcript-code-block" key={`code-${index}`}>
              <div className="transcript-code-heading"><span>{label}</span><button aria-label={`Copy ${label} code block ${block.ordinal}`} onClick={() => void copy(block.code, "Code")} type="button">Copy code</button></div>
              <pre aria-label={`${label} code block ${block.ordinal}`} dir="ltr" tabIndex={0}><code>{highlightedCode(block.code)}</code></pre>
            </div>;
          }
          return <p dir="auto" key={`paragraph-${index}`}>{inlineContent(block.text, backendTrusted)}</p>;
        })}
      </div>
      <TranscriptLinkPreviews messageLabel={messageLabel} onRetry={onRetryLinkPreviews && linkPreviewConversationId && linkPreviewMessageId && linkPreviewMessageRevision
        ? () => onRetryLinkPreviews(linkPreviewConversationId, linkPreviewMessageId, linkPreviewMessageRevision)
        : undefined} previews={showLinkPreviewCards ? linkPreviews : []} retrying={linkPreviewRetrying} />
      {bounded.truncated ? <p className="transcript-truncated" role="note">Content truncated for safe display.</p> : null}
      {simplified ? <p className="transcript-truncated" role="note">Formatting simplified for safe display.</p> : null}
      {copyStatus ? <span aria-live="polite" className="transcript-copy-status" role="status">{copyStatus}</span> : null}
    </div>
  );
});

export const transcriptContentLimits = {
  maximumDisplayCodePoints: MAXIMUM_DISPLAY_CODE_POINTS,
  maximumRenderUnits: MAXIMUM_RENDER_UNITS,
  maximumTranscriptRenderUnits: MAXIMUM_TRANSCRIPT_RENDER_UNITS,
};
