"use client";

import { memo, useState } from "react";

import type { ConversationMediaItem } from "@/lib/public-conversation-media";


function fileSize(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.ceil(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}


export const ConversationFileCard = memo(function ConversationFileCard({
  item,
  label,
}: Readonly<{
  item: ConversationMediaItem;
  label: "Generated file" | "Input file";
}>) {
  const [imageState, setImageState] = useState<"loading" | "ready" | "error">("loading");
  const contentUrl = item.available ? item.contentUrl : null;
  const canOpen = contentUrl !== null;
  return (
    <article className="conversation-file-card" data-available={canOpen ? "true" : "false"}>
      {item.kind === "image" && canOpen ? (
        <div className="conversation-file-image" data-state={imageState}>
          {imageState === "loading" ? <span aria-live="polite">Loading image…</span> : null}
          {/* eslint-disable-next-line @next/next/no-img-element -- fixed same-origin route returns validated local raster bytes */}
          <img
            alt={item.name}
            decoding="async"
            loading="lazy"
            onError={() => setImageState("error")}
            onLoad={() => setImageState("ready")}
            src={contentUrl ?? undefined}
          />
          {imageState === "error" ? <span role="status">Image unavailable</span> : null}
        </div>
      ) : null}
      <div className="conversation-file-body">
        <span className="conversation-file-kind">{label}</span>
        <strong>{item.name}</strong>
        <span>{fileSize(item.byteSize)} · {item.available ? "Available" : "Unavailable"}</span>
      </div>
      {canOpen ? (
        <div className="conversation-file-actions">
          <a href={contentUrl ?? undefined} referrerPolicy="no-referrer" rel="noopener noreferrer" target="_blank">Review</a>
          <a download={item.name} href={contentUrl ?? undefined}>Download</a>
        </div>
      ) : null}
    </article>
  );
});


export const RunConversationMedia = memo(function RunConversationMedia({
  inputs,
  outputs,
}: Readonly<{
  inputs: ConversationMediaItem[];
  outputs: ConversationMediaItem[];
}>) {
  if (!inputs.length && !outputs.length) return null;
  return (
    <div aria-label="Run files" className="conversation-run-files">
      {inputs.map((item) => <ConversationFileCard item={item} key={`input-${item.id}`} label="Input file" />)}
      {outputs.map((item) => <ConversationFileCard item={item} key={`output-${item.id}`} label="Generated file" />)}
    </div>
  );
});
