"use client";

import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type {
  PublicActivityPayload,
  PublicConversation,
  PublicConversationAgent,
  PublicConversationDetail,
  PublicConversationMessage,
  PublicConversationQueueMutation,
  PublicConversationTurnSubmission,
  PublicQueuedConversationTurn,
  PublicCodexReadiness,
  PublicAgentConfiguration,
  PublicAgentConfigurationPreview,
} from "@/lib/bridge-conversations";
import {
  conversationComposerIntent,
  validConversationComposerText,
} from "@/lib/conversation-composer";
import {
  cancelConversationTurn,
  archiveConversation,
  continueConversationTurn,
  createConversation,
  editConversationTurn,
  fetchActivity,
  fetchCodexReadiness,
  fetchConversation,
  fetchConversations,
  retryConversationRun,
  resumeConversationRun,
  steerConversation,
  submitConversationTurn,
  PublicConversationError,
} from "@/lib/public-conversations";
import type { PendingRunRequest, RunActionResponse } from "@/lib/bridge-run-response";
import type { PublicRunEvent } from "@/lib/bridge-run-events";
import { TranscriptContent, transcriptContentLimits, transcriptContentRenderUnits } from "./transcript-content";
import type { SafeLinkPreviewProjection } from "./transcript-link-previews";
import {
  clearLinkPreviewCache,
  readLinkPreviewPreference,
  readLinkPreviews,
  requestLinkPreviews,
  updateLinkPreviewPreference,
  type PublicLinkPreviewPreference,
} from "@/lib/public-link-previews";
import {
  confirmRunResponse,
  confirmRunStop,
  fetchPendingRunRequest,
  previewRunResponse,
  previewRunStop,
  PublicRunActionError,
} from "@/lib/public-run-actions";
import {
  confirmAgentConfiguration,
  fetchAgentConfiguration,
  previewAgentConfiguration,
  PublicAgentConfigurationError,
} from "@/lib/public-agent-configuration";
import { RunConversationMedia } from "./conversation-media";
import { ConversationContextControls } from "./conversation-context-controls";
import {
  readConversationMedia,
  readStagedConversationContext,
  type ConversationMedia,
  type StagedConversationContext,
} from "@/lib/public-conversation-media";

const SUGGESTIONS = [
  "Help me plan the work I need to finish today",
  "Summarize what is currently waiting for my attention",
  "Turn a rough idea into a clear next step",
];
const EMPTY_RUN_EVENTS: PublicRunEvent[] = [];
const EMPTY_LINK_PREVIEWS: readonly SafeLinkPreviewProjection[] = [];

type LoadingState = "loading" | "ready" | "empty" | "unavailable" | "unsupported" | "error";
type OptimisticMessage = { conversationId: string; key: string; text: string };
type NoticeEntry = { message: string; sequence: number };
type QueueEditorGuard = { revision: number; turnId: string | null };
const UNBOUND_DRAFT_KEY = "new-conversation";
const MAX_TRANSCRIPT_MESSAGES = 200;
const HAS_HTTPS_LINK = /https:\/\//iu;

const ACTIVE_RUN_STATUSES = new Set([
  "reserved", "queued", "submitting", "starting", "running", "cancelling",
  "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown",
  "finalizing",
]);
const RETRYABLE_RUN_STATUSES = new Set(["failed", "cancelled", "stopped", "interrupted"]);

function readable(value: string): string {
  return value.split(/[._-]/u).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

function conversationLabel(conversation: PublicConversation): string {
  return conversation.title_source === "default" ? "New conversation" : conversation.title;
}

function statusFrom(error: unknown): LoadingState {
  const code = error && typeof error === "object" && "code" in error ? String((error as PublicConversationError).code) : "";
  return code.includes("unsupported") ? "unsupported" : code.includes("unavailable") ? "unavailable" : "error";
}

function errorCode(error: unknown): string {
  return error && typeof error === "object" && "code" in error
    ? String((error as PublicConversationError).code)
    : "";
}

function queuedTurnFromSubmission(
  submission: PublicConversationTurnSubmission,
): PublicQueuedConversationTurn | null {
  const { message, turn } = submission;
  if (
    (turn.state !== "pending" && turn.state !== "blocked")
    || turn.latest_run_id !== null
    || message.state !== "accepted"
  ) return null;
  return {
    blocked_reason: turn.blocked_reason,
    conversation_id: turn.conversation_id,
    created_at: turn.created_at,
    id: turn.id,
    message_revision: message.revision,
    queue_ordinal: turn.queue_ordinal,
    revision: turn.revision,
    state: turn.state,
    text: message.content.parts[0].text,
    updated_at: turn.updated_at,
    user_message_id: turn.user_message_id,
  };
}

function mergeTurnSubmission(
  existing: PublicConversationDetail,
  submission: PublicConversationTurnSubmission,
): PublicConversationDetail {
  const queued = queuedTurnFromSubmission(submission);
  const queuedTurns = existing.queued_turns
    .filter((turn) => turn.id !== submission.turn.id)
    .concat(queued ? [queued] : [])
    .sort((left, right) => left.queue_ordinal - right.queue_ordinal);
  const messages = existing.messages
    .filter((message) => message.id !== submission.message.id)
    .concat(submission.message)
    .sort((left, right) => left.sequence - right.sequence)
    .slice(-MAX_TRANSCRIPT_MESSAGES);
  return {
    ...existing,
    conversation: submission.conversation,
    current_run: submission.run ?? existing.current_run,
    messages,
    queued_turns: queuedTurns,
  };
}

function mergeQueueMutation(
  existing: PublicConversationDetail,
  mutation: PublicConversationQueueMutation,
): PublicConversationDetail {
  const messages = existing.messages
    .filter((message) => message.id !== mutation.message.id)
    .concat(mutation.message)
    .sort((left, right) => left.sequence - right.sequence)
    .slice(-MAX_TRANSCRIPT_MESSAGES);
  const queuedTurns = mutation.disposition === "cancelled"
    ? existing.queued_turns.filter((turn) => turn.id !== mutation.turn.id)
    : existing.queued_turns.map((turn) => turn.id === mutation.turn.id ? {
      ...turn,
      blocked_reason: mutation.turn.blocked_reason,
      message_revision: mutation.message.revision,
      revision: mutation.turn.revision,
      state: mutation.turn.state as "pending" | "blocked",
      text: mutation.message.content.parts[0].text,
      updated_at: mutation.turn.updated_at,
    } : turn);
  return {
    ...existing,
    conversation: mutation.conversation,
    messages,
    queued_turns: queuedTurns,
  };
}

function mergeMessages(
  existing: PublicConversationMessage[],
  incoming: PublicConversationMessage[],
): PublicConversationMessage[] {
  const messages = new Map<string, PublicConversationMessage>();
  for (const message of existing) messages.set(message.id, message);
  for (const message of incoming) {
    const current = messages.get(message.id);
    if (!current || message.revision >= current.revision) messages.set(message.id, message);
  }
  return [...messages.values()]
    .sort((left, right) => left.sequence - right.sequence)
    .slice(-MAX_TRANSCRIPT_MESSAGES);
}

function mergeRefreshedConversationDetail(
  existing: PublicConversationDetail | undefined,
  incoming: PublicConversationDetail,
): PublicConversationDetail {
  if (!existing || existing.conversation.id !== incoming.conversation.id) return incoming;
  const staleConversation = incoming.conversation.revision < existing.conversation.revision;
  const messages = mergeMessages(existing.messages, incoming.messages);
  const incomingFirst = incoming.messages[0]?.sequence;
  const retainedFirst = messages[0]?.sequence;
  const preservesLoadedHistory = incomingFirst !== undefined
    && retainedFirst !== undefined
    && retainedFirst < incomingFirst;
  const currentRun = !staleConversation
    && existing.current_run
    && incoming.current_run
    && existing.current_run.id === incoming.current_run.id
    && Date.parse(existing.current_run.updated_at) > Date.parse(incoming.current_run.updated_at)
    ? existing.current_run
    : staleConversation ? existing.current_run : incoming.current_run;
  return {
    ...incoming,
    conversation: staleConversation ? existing.conversation : incoming.conversation,
    current_run: currentRun,
    messages,
    next_message_cursor: preservesLoadedHistory
      ? existing.next_message_cursor
      : incoming.next_message_cursor,
    queued_turns: staleConversation ? existing.queued_turns : incoming.queued_turns,
  };
}

function mergeOlderConversationDetail(
  existing: PublicConversationDetail | undefined,
  older: PublicConversationDetail,
): PublicConversationDetail {
  if (!existing || existing.conversation.id !== older.conversation.id) return older;
  const messages = mergeMessages(older.messages, existing.messages);
  return {
    ...existing,
    messages,
    next_message_cursor: messages.length >= MAX_TRANSCRIPT_MESSAGES
      ? null
      : older.next_message_cursor,
  };
}

function queueFocusSuccessor(
  turns: PublicQueuedConversationTurn[],
  turnId: string,
): string | null {
  const index = turns.findIndex((turn) => turn.id === turnId);
  if (index < 0) return turns[0]?.id ?? null;
  return turns[index + 1]?.id ?? turns[index - 1]?.id ?? null;
}

function liveSummary(data: string, runId: string): string | null {
  if (data.length > 100_000) return null;
  let value: unknown;
  try { value = JSON.parse(data) as unknown; } catch { return null; }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const candidates = Array.isArray(record.events)
    ? record.events
    : record.event && typeof record.event === "object" ? [record.event] : [];
  for (const candidate of candidates.slice(-100).reverse()) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
    const event = candidate as Record<string, unknown>;
    if (
      event.run_id === runId
      && typeof event.summary === "string"
      && event.summary.length > 0
      && event.summary.length <= 500
      && event.summary.trim() === event.summary
      && !event.summary.includes("\0")
    ) return event.summary;
  }
  return null;
}

function snapshotPresentationMode(data: string): "merge" | "replace" | null {
  if (data.length > 100_000) return null;
  let value: unknown;
  try { value = JSON.parse(data) as unknown; } catch { return null; }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  return Array.isArray(record.events) && typeof record.reset === "boolean"
    ? record.reset ? "replace" : "merge"
    : null;
}

function livePresentationEvents(data: string, runId: string, envelope: "many" | "single"): PublicRunEvent[] | null {
  if (data.length > 100_000) return null;
  let value: unknown;
  try { value = JSON.parse(data) as unknown; } catch { return null; }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const candidates = envelope === "many"
    ? Array.isArray(record.events) ? record.events : null
    : record.event && typeof record.event === "object" && !Array.isArray(record.event) ? [record.event] : null;
  if (candidates === null) return null;
  const projected: PublicRunEvent[] = [];
  for (const candidate of candidates.slice(-100)) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return null;
    const event = candidate as Record<string, unknown>;
    const presentation = event.presentation;
    if (event.run_id !== runId || typeof event.id !== "string" || !Number.isInteger(event.sequence) || (event.sequence as number) < 1 || typeof event.type !== "string" || typeof event.summary !== "string") return null;
    if (presentation === null) {
      projected.push({
        id: event.id as string,
        run_id: runId,
        sequence: event.sequence as number,
        type: event.type as string,
        occurred_at: typeof event.occurred_at === "string" ? event.occurred_at : "",
        summary: event.summary as string,
        message: null,
        metrics: {},
        presentation: null,
      });
      continue;
    }
    if (!presentation || typeof presentation !== "object" || Array.isArray(presentation)) return null;
    const safe = presentation as Record<string, unknown>;
    if (Object.keys(safe).sort().join(",") !== "kind,label,phase" || event.summary !== safe.label) return null;
    const safePresentation = safe.kind === "reasoning"
      ? event.type === "message" && safe.phase === "available" && safe.label === "Reasoning summary available"
      : safe.kind === "tool" && (
        event.type === "tool.completed" && safe.phase === "completed" && safe.label === "Tool activity completed"
      || event.type === "tool.requested" && safe.phase === "requested" && safe.label === "Tool activity requested"
      || event.type === "tool.requested" && safe.phase === "started" && safe.label === "Tool activity started"
      );
    if (!safePresentation) return null;
    projected.push({
      id: event.id as string,
      run_id: runId,
      sequence: event.sequence as number,
      type: event.type as string,
      occurred_at: typeof event.occurred_at === "string" ? event.occurred_at : "",
      summary: event.summary as string,
      message: null,
      metrics: {},
      presentation: { ...(presentation as PublicRunEvent["presentation"])! },
    });
  }
  return projected.sort((left, right) => left.sequence - right.sequence);
}

function StatusMessage({ state, children }: Readonly<{ state: LoadingState; children: React.ReactNode }>) {
  return <p aria-live="polite" className={`console-status console-status-${state}`}>{children}</p>;
}

const LinkPreviewSettings = memo(function LinkPreviewSettings({ busy, onClear, onToggle, preference, state }: Readonly<{
  busy: boolean;
  onClear: () => void;
  onToggle: () => void;
  preference: PublicLinkPreviewPreference | null;
  state: LoadingState;
}>) {
  const label = state === "loading" ? "Checking" : state !== "ready" ? "Unavailable" : preference?.enabled ? "On" : "Off";
  return <details className="link-preview-settings"><summary>Link previews · {label}</summary><div>
    <p>Credential-free previews reveal your public IP, the submitted path and query, request timing, and the fixed Mentat user-agent to the destination and its network providers. Plain links always remain available.</p>
    <div className="link-preview-settings-actions">
      <button disabled={busy || !preference || state !== "ready"} onClick={onToggle} type="button">{preference?.enabled ? "Turn off" : "Turn on"}</button>
      <button disabled={busy || state !== "ready"} onClick={onClear} type="button">Clear preview cache</button>
    </div>
  </div></details>;
});

const RunPresentation = memo(function RunPresentation({ active, events }: Readonly<{ active: boolean; events: PublicRunEvent[] }>) {
  const reasoning = [...events].reverse().find((event) => event.presentation?.kind === "reasoning") ?? null;
  const last = events.at(-1) ?? null;
  const reasoningActive = active && reasoning !== null && last?.sequence === reasoning.sequence;
  const toolEvents = events.filter((event) => event.presentation?.kind === "tool").slice(-40);
  const lastTool = toolEvents.at(-1);
  const toolActive = active && !!lastTool && lastTool.presentation?.phase !== "completed";
  const [thinkingOpen, setThinkingOpen] = useState(reasoningActive);
  const priorReasoningActive = useRef(reasoningActive);
  const priorToolActive = useRef(false);
  const [announcement, setAnnouncement] = useState("");
  useEffect(() => {
    const wasActive = priorReasoningActive.current;
    priorReasoningActive.current = reasoningActive;
    void Promise.resolve().then(() => {
      if (reasoningActive) setThinkingOpen(true);
      else if (wasActive) setThinkingOpen(false);
    });
  }, [reasoningActive]);
  useEffect(() => {
    if (toolActive !== priorToolActive.current) {
      priorToolActive.current = toolActive;
      void Promise.resolve().then(() => setAnnouncement(toolActive ? "Agent activity started." : "Agent activity finished."));
    }
  }, [toolActive]);
  if (!reasoning && toolEvents.length === 0) return null;
  return <aside aria-label="Run details" className="run-presentation">
    {reasoning ? <details className="thinking-disclosure" onToggle={(event) => setThinkingOpen(event.currentTarget.open)} open={thinkingOpen}><summary>{reasoningActive ? "Thinking…" : "Thinking"}</summary><p>{reasoning.presentation?.label}</p></details> : null}
    {toolEvents.length ? <details className="activity-disclosure"><summary>{toolActive ? "Activity in progress" : `Activity · ${toolEvents.length}`}</summary><ol>{toolEvents.map((event) => <li key={event.id}>{event.presentation?.label}</li>)}</ol></details> : null}
    <span aria-live="polite" className="presentation-announcement" role="status">{announcement}</span>
  </aside>;
});

function messageGroups(messages: PublicConversationMessage[]) {
  const groups: Array<{ key: string; label: string; messages: PublicConversationMessage[]; runKey: string }> = [];
  const runOrdinals = new Map<string, number>();
  for (const message of messages) {
    const runKey = message.run_id ?? `queued-${message.id}`;
    const current = groups.at(-1);
    if (current?.runKey === runKey) current.messages.push(message);
    else {
      if (message.run_id && !runOrdinals.has(message.run_id)) runOrdinals.set(message.run_id, runOrdinals.size + 1);
      groups.push({ key: `${runKey}-${groups.length}`, label: message.run_id ? `Run ${runOrdinals.get(message.run_id)}` : "Queued turn", messages: [message], runKey });
    }
  }
  return groups;
}

function linkPreviewKey(message: Pick<PublicConversationMessage, "id" | "revision">): string {
  return `${message.id}:${message.revision}`;
}

function mergeLinkPreviewState(
  current: Record<string, readonly SafeLinkPreviewProjection[]>,
  key: string,
  previews: readonly SafeLinkPreviewProjection[],
) {
  const next = Object.fromEntries(Object.entries(current).slice(-599));
  next[key] = previews.map((preview) => ({ ...preview }));
  return next;
}

const Transcript = memo(function Transcript({
  detail,
  detailState,
  selectedAgentName,
  draftSuggestion,
  loadOlder,
  loadingOlder,
  linkPreviewBusyMessages,
  linkPreviews,
  mediaRuns,
  onRetryLinkPreviews,
  optimisticMessage,
  presentationEvents,
  presentationRunId,
  runActive,
  selectedConversationId,
  showLinkPreviewCards,
}: Readonly<{
  detail: PublicConversationDetail | null;
  detailState: LoadingState;
  selectedAgentName: string | null;
  draftSuggestion: (suggestion: string) => void;
  loadOlder: () => void;
  loadingOlder: boolean;
  linkPreviewBusyMessages: ReadonlySet<string>;
  linkPreviews: Readonly<Record<string, readonly SafeLinkPreviewProjection[]>>;
  mediaRuns: ConversationMedia["runs"];
  onRetryLinkPreviews: (conversationId: string, messageId: string, revision: number) => void;
  optimisticMessage: OptimisticMessage | null;
  presentationEvents: PublicRunEvent[];
  presentationRunId: string | null;
  runActive: boolean;
  selectedConversationId: string | null;
  showLinkPreviewCards: boolean;
}>) {
  const transcriptRef = useRef<HTMLDivElement>(null);
  const scrollStates = useRef(new Map<string, { stick: boolean; top: number }>());
  const optimistic = optimisticMessage?.conversationId === selectedConversationId ? optimisticMessage : null;
  const isEmpty = detailState === "empty" || detailState === "ready" && detail?.messages.length === 0 && optimistic === null && mediaRuns.length === 0;
  const messageWindow = useMemo(() => detail?.messages.slice(-200) ?? [], [detail]);
  const groups = useMemo(() => messageGroups(messageWindow), [messageWindow]);
  const mediaByRun = useMemo(
    () => new Map(mediaRuns.map((run) => [run.runId, run])),
    [mediaRuns],
  );
  const ungroupedMedia = useMemo(() => {
    const groupedRunIds = new Set(groups.map((group) => group.runKey));
    return mediaRuns.filter((run) => !groupedRunIds.has(run.runId));
  }, [groups, mediaRuns]);
  const renderEntries = useMemo(() => [
    ...groups.map((group) => ({ kind: "messages" as const, createdAt: group.messages[0]?.created_at ?? "", group })),
    ...ungroupedMedia.map((media) => ({ kind: "files" as const, createdAt: media.createdAt, media })),
  ].sort((left, right) => left.createdAt.localeCompare(right.createdAt) || left.kind.localeCompare(right.kind)), [groups, ungroupedMedia]);
  const aggregatePlainText = useMemo(() => {
    const simplified = new Set<string>();
    let remaining = transcriptContentLimits.maximumTranscriptRenderUnits;
    const unitCache = new Map<string, number>();
    const candidates = messageWindow.map((message) => ({ id: message.id, text: message.content.parts[0].text }));
    if (optimistic) candidates.push({ id: optimistic.key, text: optimistic.text });
    for (const candidate of candidates.reverse()) {
      const units = unitCache.get(candidate.text) ?? transcriptContentRenderUnits(candidate.text);
      unitCache.set(candidate.text, units);
      const cost = units > transcriptContentLimits.maximumRenderUnits ? 2 : units;
      if (cost > remaining) simplified.add(candidate.id);
      else remaining -= cost;
    }
    return simplified;
  }, [messageWindow, optimistic]);
  const transcriptVersion = `${detail?.messages.length ?? 0}:${optimistic?.key ?? ""}`;
  useLayoutEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript || !selectedConversationId) return;
    const saved = scrollStates.current.get(selectedConversationId);
    transcript.scrollTop = !saved || saved.stick
      ? transcript.scrollHeight
      : Math.min(saved.top, Math.max(0, transcript.scrollHeight - transcript.clientHeight));
    scrollStates.current.delete(selectedConversationId);
    scrollStates.current.set(selectedConversationId, {
      stick: !saved || saved.stick,
      top: transcript.scrollTop,
    });
    while (scrollStates.current.size > 32) {
      const oldest = scrollStates.current.keys().next().value as string | undefined;
      if (oldest === undefined) break;
      scrollStates.current.delete(oldest);
    }
  }, [selectedConversationId, transcriptVersion]);
  return (
    <div className="conversation-transcript" id="conversation-panel" onScroll={(event) => { if (!selectedConversationId) return; const node = event.currentTarget; scrollStates.current.delete(selectedConversationId); scrollStates.current.set(selectedConversationId, { stick: node.scrollHeight - node.scrollTop - node.clientHeight < 48, top: node.scrollTop }); }} ref={transcriptRef} role="tabpanel" aria-labelledby={selectedConversationId ? `conversation-tab-${selectedConversationId}` : undefined} tabIndex={-1}>
      {detailState === "loading" ? <StatusMessage state="loading">Loading the selected Conversation…</StatusMessage> : null}
      {detailState === "unavailable" ? <StatusMessage state="unavailable">Conversation data is temporarily unavailable.</StatusMessage> : null}
      {detailState === "error" ? <StatusMessage state="error">Mentat could not safely read this Conversation.</StatusMessage> : null}
      {isEmpty ? <div className="conversation-empty-state"><span className="empty-state-mark" aria-hidden="true">✦</span><h2>{detail?.conversation.title ?? "A clear place to begin"}</h2><p>Choose a suggestion or write a prompt below. Mentat will keep the accepted Turn and its Run visible here.</p><div className="suggestion-list">{SUGGESTIONS.map((suggestion) => <button key={suggestion} onClick={() => draftSuggestion(suggestion)} type="button">{suggestion}</button>)}</div></div> : null}
      {detailState === "ready" && detail ? <RunPresentation active={runActive} events={presentationEvents} key={presentationRunId ?? "no-run"} /> : null}
      {detailState === "ready" && detail && (detail.messages.length > 0 || optimistic || ungroupedMedia.length > 0) ? <>{detail.next_message_cursor ? <button className="load-older" disabled={loadingOlder} onClick={loadOlder} type="button">{loadingOlder ? "Loading older messages…" : "Load older messages"}</button> : null}<div className="message-list">{renderEntries.map((entry) => { if (entry.kind === "files") return <section aria-label={`Run files ${entry.media.runId}`} className="message-group message-group-files" key={`files-${entry.media.runId}`}><h3>Run files</h3><RunConversationMedia inputs={entry.media.inputs} outputs={entry.media.outputs} /></section>; const group = entry.group; const media = mediaByRun.get(group.runKey); return <section aria-label={group.label} className="message-group" key={group.key}><h3>{group.label}</h3><ol>{group.messages.map((message) => <li className={`message-row message-${message.role}${message.state === "cancelled" ? " message-cancelled" : ""}`} key={message.id}><span className="message-role">{message.role === "user" ? `You${message.state === "cancelled" ? " · Cancelled" : ""}` : selectedAgentName ?? "Agent"}</span><TranscriptContent content={message.content.parts[0].text} forcePlainText={aggregatePlainText.has(message.id)} linkPreviewConversationId={message.conversation_id} linkPreviewMessageId={message.id} linkPreviewMessageRevision={message.revision} linkPreviewRetrying={linkPreviewBusyMessages.has(linkPreviewKey(message))} linkPreviews={linkPreviews[linkPreviewKey(message)] ?? EMPTY_LINK_PREVIEWS} messageLabel={`${message.role} message ${message.sequence}`} onRetryLinkPreviews={onRetryLinkPreviews} showLinkPreviewCards={showLinkPreviewCards} /></li>)}</ol>{media ? <RunConversationMedia inputs={media.inputs} outputs={media.outputs} /> : null}</section>; })}{optimistic ? <section aria-label="Sending turn" className="message-group message-group-optimistic"><h3>Sending turn</h3><ol><li aria-label="Sending message" className="message-row message-user message-optimistic"><span className="message-role">You · Sending…</span><TranscriptContent content={optimistic.text} forcePlainText={aggregatePlainText.has(optimistic.key)} messageLabel="sending message" /></li></ol></section> : null}</div></> : null}
    </div>
  );
});

const QueuedTurns = memo(function QueuedTurns({
  busyTurnIds,
  editDrafts,
  editingTurnId,
  onBeginEdit,
  onCancel,
  onContinue,
  onDiscardEdit,
  onEditDraft,
  onSaveEdit,
  turns,
}: Readonly<{
  busyTurnIds: ReadonlySet<string>;
  editDrafts: Readonly<Record<string, string>>;
  editingTurnId: string | null;
  onBeginEdit: (turn: PublicQueuedConversationTurn) => void;
  onCancel: (turn: PublicQueuedConversationTurn) => void;
  onContinue: (turn: PublicQueuedConversationTurn) => void;
  onDiscardEdit: (turn: PublicQueuedConversationTurn) => void;
  onEditDraft: (turnId: string, text: string) => void;
  onSaveEdit: (turn: PublicQueuedConversationTurn) => void;
  turns: PublicQueuedConversationTurn[];
}>) {
  if (!turns.length) return null;
  return (
    <section aria-label="Queued Turns" className="conversation-queue">
      <div className="queue-heading"><div><p className="console-kicker">Up next</p><h3>Queued Turns</h3></div><span>{turns.length} / 8 waiting</span></div>
      <ol>{turns.map((turn, index) => { const busy = busyTurnIds.has(turn.id); const editing = editingTurnId === turn.id; const editDraft = editDrafts[turn.id] ?? turn.text; const editValid = validConversationComposerText(editDraft); return <li key={turn.id}><div className="queue-copy"><span>#{turn.queue_ordinal} · {turn.state === "blocked" ? `Blocked: ${readable(turn.blocked_reason ?? "unknown")}` : "Pending"}</span>{editing ? <textarea aria-label={`Edit queued Turn ${turn.queue_ordinal}`} autoFocus disabled={busy} onChange={(event) => onEditDraft(turn.id, event.target.value)} rows={2} value={editDraft} /> : <p>{turn.text}</p>}</div><div className="queue-actions">{editing ? <><button aria-label={`Save queued Turn ${turn.queue_ordinal}`} disabled={busy || !editValid || editDraft === turn.text} onClick={() => onSaveEdit(turn)} type="button">Save</button><button aria-label={`Discard queued Turn ${turn.queue_ordinal} edit`} disabled={busy} onClick={() => onDiscardEdit(turn)} type="button">Discard</button></> : <button aria-label={`Edit queued Turn ${turn.queue_ordinal}`} disabled={busy} id={`queue-edit-${turn.id}`} onClick={() => onBeginEdit(turn)} type="button">Edit</button>}<button aria-label={`Cancel queued Turn ${turn.queue_ordinal}`} disabled={busy} onClick={() => onCancel(turn)} type="button">Cancel</button>{!editing && index === 0 && turn.state === "blocked" ? <button aria-label={`Continue queued Turn ${turn.queue_ordinal}`} className="queue-continue" disabled={busy} onClick={() => onContinue(turn)} type="button">Continue</button> : null}</div></li>; })}</ol>
    </section>
  );
});

const PendingActionCard = memo(function PendingActionCard({
  busy,
  clarificationText,
  confirmationPending,
  onCancelConfirmation,
  onClarificationText,
  onConfirm,
  onPrepare,
  request,
}: Readonly<{
  busy: boolean;
  clarificationText: string;
  confirmationPending: boolean;
  onCancelConfirmation: () => void;
  onClarificationText: (text: string) => void;
  onConfirm: () => void;
  onPrepare: (response: RunActionResponse) => void;
  request: PendingRunRequest;
}>) {
  return (
    <section aria-label={request.kind === "approval" ? "Approval required" : "Clarification required"} className="pending-action-card">
      <div><p className="console-kicker">Operator input</p><h3>{request.kind === "approval" ? request.title || "Approval required" : "Clarification required"}</h3><p>{request.kind === "approval" ? request.summary : request.question}</p></div>
      {confirmationPending ? <div className="pending-action-confirm"><p>Confirm this exact response to the current Run.</p><div><button disabled={busy} onClick={onCancelConfirmation} type="button">Back</button><button className="console-primary-action" disabled={busy} onClick={onConfirm} type="button">{busy ? "Confirming…" : "Confirm response"}</button></div></div> : request.kind === "approval" || request.prompt_type === "choice" ? <div className="pending-action-choices">{request.choices.map((choice) => <button disabled={busy} key={choice.id} onClick={() => onPrepare({ kind: request.kind, choice: choice.id } as RunActionResponse)} type="button">{choice.label}</button>)}</div> : <div className="pending-action-text"><label htmlFor="clarification-response">Response</label><textarea id="clarification-response" maxLength={2_000} onChange={(event) => onClarificationText(event.target.value)} rows={3} value={clarificationText} /><button disabled={busy || !clarificationText.trim()} onClick={() => onPrepare({ kind: "clarification", text: clarificationText.trim() })} type="button">Review response</button></div>}
      <p className="pending-action-note">The prompt composer cannot answer this request.</p>
    </section>
  );
});

const ActivityRail = memo(function ActivityRail({
  activity,
  activityState,
  collapsed,
  expandedAgents,
  onToggle,
  onToggleAgent,
  onSelectConversation,
}: Readonly<{
  activity: PublicActivityPayload | null;
  activityState: LoadingState;
  collapsed: boolean;
  expandedAgents: ReadonlySet<string>;
  onToggle: () => void;
  onToggleAgent: (agentId: string) => void;
  onSelectConversation: (conversationId: string) => void;
}>) {
  return (
    <aside aria-label="Agent activity" className="activity-rail">
      <button aria-controls="agent-activity-content" aria-expanded={!collapsed} aria-label={collapsed ? "Expand Agent activity" : "Collapse Agent activity"} className="rail-toggle activity-toggle" onClick={onToggle} type="button"><span aria-hidden="true">{collapsed ? "‹" : "›"}</span></button>
      <div className="activity-rail-content" id="agent-activity-content"><div className="activity-heading"><p className="console-kicker">Live context</p><h2>Agent activity</h2></div>
        {activityState === "loading" ? <StatusMessage state="loading">Loading activity…</StatusMessage> : null}
        {activityState === "unavailable" ? <StatusMessage state="unavailable">Activity is temporarily unavailable.</StatusMessage> : null}
        {activityState === "unsupported" ? <StatusMessage state="unsupported">Activity is not available yet.</StatusMessage> : null}
        {activityState === "error" ? <StatusMessage state="error">Activity could not be read safely.</StatusMessage> : null}
        {activityState === "ready" && activity?.activity.length === 0 ? <StatusMessage state="empty">No Agent activity yet.</StatusMessage> : null}
        {activityState === "ready" && activity?.activity.length ? <div className="activity-list">{activity.activity.map((item) => { const expanded = expandedAgents.has(item.agent.id); const contentId = `activity-agent-${item.agent.id}`; return <article className="activity-card" data-attention={item.attention ? "true" : "false"} key={item.agent.id}><button aria-controls={contentId} aria-expanded={expanded} className="activity-agent-toggle" onClick={() => onToggleAgent(item.agent.id)} type="button"><span className="activity-state-dot" aria-hidden="true" /><span className="activity-agent-label"><strong>{item.agent.name}</strong><small>{readable(item.state)}</small></span><span aria-hidden="true">{expanded ? "−" : "+"}</span></button>{expanded ? <div className="activity-card-content" id={contentId}><p className="activity-summary">{item.summary}</p>{item.conversations.length ? <ul>{item.conversations.map((conversation) => <li key={conversation.id}><button onClick={() => onSelectConversation(conversation.id)} type="button">{conversation.title}</button><span>{readable(conversation.run_status)}</span></li>)}</ul> : null}</div> : null}</article>; })}</div> : null}
      </div>
    </aside>
  );
});

function tabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, index: number, count: number, select: (next: number) => void) {
  const next = event.key === "ArrowRight" ? (index + 1) % count : event.key === "ArrowLeft" ? (index - 1 + count) % count : event.key === "Home" ? 0 : event.key === "End" ? count - 1 : -1;
  if (next < 0 || count === 0) return;
  event.preventDefault();
  document.querySelector<HTMLButtonElement>(`[data-conversation-tab-index="${next}"]`)?.focus();
  select(next);
}

function ComposerConfiguration({
  active,
  agentId,
  agentLocked,
  agents,
  busy,
  configuration,
  loading,
  model,
  onAgent,
  onConfirm,
  onModel,
  onPreview,
  onProvider,
  preview,
  provider,
  snapshot,
}: Readonly<{
  active: boolean;
  agentId: string | null;
  agentLocked: boolean;
  agents: PublicConversationAgent[];
  busy: boolean;
  configuration: PublicAgentConfiguration | null;
  loading: LoadingState;
  model: string;
  onAgent: (agentId: string | null) => void;
  onConfirm: () => void;
  onModel: (model: string) => void;
  onPreview: () => void;
  onProvider: (provider: string) => void;
  preview: PublicAgentConfigurationPreview | null;
  provider: string;
  snapshot: { provider: string; model: string; effort: string } | null;
}>) {
  const confirmFocus = useRef<HTMLButtonElement>(null);
  const providerFocus = useRef<HTMLSelectElement>(null);
  const hadPreview = useRef(false);
  useEffect(() => {
    if (preview) confirmFocus.current?.focus();
    else if (hadPreview.current) providerFocus.current?.focus();
    hadPreview.current = preview !== null;
  }, [preview]);
  const selectedProvider = configuration?.providers.find((item) => item.id === provider);
  const models = selectedProvider?.models ?? [];
  const changed = !!configuration
    && (provider !== (configuration.current.provider ?? "")
      || model !== (configuration.current.model ?? ""));
  const disabled = busy || active || !configuration?.mutable;
  const explanation = active
    ? "Active Run snapshot is unchanged. Stop it before configuring the next Run."
    : loading === "loading" ? "Loading Agent configuration…"
      : loading === "unavailable" ? "Agent configuration is temporarily unavailable."
        : loading === "unsupported" ? "This Mentat build does not support Agent configuration."
          : loading === "error" ? "Agent configuration could not be read safely."
      : configuration?.explanation || (configuration?.mutable ? "Changes apply to the next Run." : "Configuration is read-only.");
  return <div aria-label="Composer Agent configuration" className="composer-configuration">
    <label><span>Agent</span><select aria-label={agentLocked ? "Conversation Agent" : "Agent for new conversations"} disabled={agentLocked} onChange={(event) => onAgent(event.target.value || null)} value={agentId ?? ""}><option value="">Choose an Agent</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
    <label><span>Provider</span><select aria-label="Provider for next Run" disabled={disabled || !configuration?.providers.length} onChange={(event) => onProvider(event.target.value)} ref={providerFocus} value={provider}><option value="">{configuration?.current.provider ?? "Unavailable"}</option>{configuration?.providers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    <label><span>Model</span><select aria-label="Model for next Run" disabled={disabled || !models.length} onChange={(event) => onModel(event.target.value)} value={model}><option value="">{configuration?.current.model ?? "Unavailable"}</option>{models.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
    <label><span>Effort</span><select aria-label="Effort for next Run" disabled value="runtime_default"><option value="runtime_default">Runtime default</option></select></label>
    {preview ? <div className="configuration-confirmation"><span>{preview.target.provider_name} · {preview.target.model} · next Run</span><button disabled={busy || active} onClick={onConfirm} ref={confirmFocus} type="button">{busy ? "Applying…" : "Confirm"}</button></div> : changed && !disabled ? <button className="configuration-review" disabled={!provider || !model} onClick={onPreview} type="button">Review</button> : null}
    {active && snapshot ? <small className="configuration-snapshot">Active snapshot: {snapshot.provider} · {snapshot.model} · {readable(snapshot.effort)}</small> : null}
    <small className="configuration-explanation">{explanation}</small>
  </div>;
}

export function HomeConsole() {
  const [conversations, setConversations] = useState<PublicConversation[]>([]);
  const [conversationCursor, setConversationCursor] = useState<string | null>(null);
  const [agents, setAgents] = useState<PublicConversationAgent[]>([]);
  const [directAgentId, setDirectAgentId] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [openConversationIds, setOpenConversationIds] = useState<ReadonlySet<string>>(new Set());
  const [details, setDetails] = useState<Record<string, PublicConversationDetail>>({});
  const [activity, setActivity] = useState<PublicActivityPayload | null>(null);
  const [conversationState, setConversationState] = useState<LoadingState>("loading");
  const [activityState, setActivityState] = useState<LoadingState>("loading");
  const [detailState, setDetailState] = useState<LoadingState>("loading");
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [expandedAgents, setExpandedAgents] = useState<ReadonlySet<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [optimisticMessages, setOptimisticMessages] = useState<Record<string, OptimisticMessage>>({});
  const [sendingConversationIds, setSendingConversationIds] = useState<ReadonlySet<string>>(new Set());
  const [queueBusyTurnIds, setQueueBusyTurnIds] = useState<ReadonlySet<string>>(new Set());
  const [queueEditDrafts, setQueueEditDrafts] = useState<Record<string, string>>({});
  const [editingTurnIds, setEditingTurnIds] = useState<Record<string, string>>({});
  const [queueFocusSequence, setQueueFocusSequence] = useState(0);
  const [liveProgress, setLiveProgress] = useState<{ runId: string; summary: string } | null>(null);
  const [runPresentationEvents, setRunPresentationEvents] = useState<Record<string, PublicRunEvent[]>>({});
  const [codexReadiness, setCodexReadiness] = useState<PublicCodexReadiness["state"] | null>(null);
  const [checkingCodex, setCheckingCodex] = useState(false);
  const [notice, setNoticeState] = useState<NoticeEntry>({ message: "", sequence: 0 });
  const [conversationNotices, setConversationNotices] = useState<Record<string, NoticeEntry>>({});
  const [creating, setCreating] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [archiveBusyIds, setArchiveBusyIds] = useState<ReadonlySet<string>>(new Set());
  const [pendingAction, setPendingAction] = useState<{ request: PendingRunRequest; runId: string } | null>(null);
  const [pendingActionState, setPendingActionState] = useState<{ runId: string; state: "ready" | "unavailable" } | null>(null);
  const [pendingResponse, setPendingResponse] = useState<{ confirmationId: string; response: RunActionResponse; runId: string } | null>(null);
  const [clarificationText, setClarificationText] = useState("");
  const [runActionBusy, setRunActionBusy] = useState(false);
  const [stopConfirmation, setStopConfirmation] = useState<{ confirmationId: string; runId: string } | null>(null);
  const [verifiedLiveRunIds, setVerifiedLiveRunIds] = useState<ReadonlySet<string>>(new Set());
  const [retryBusyRunIds, setRetryBusyRunIds] = useState<ReadonlySet<string>>(new Set());
  const [agentConfiguration, setAgentConfiguration] = useState<PublicAgentConfiguration | null>(null);
  const [agentConfigurationState, setAgentConfigurationState] = useState<LoadingState>("loading");
  const [configurationProvider, setConfigurationProvider] = useState("");
  const [configurationModel, setConfigurationModel] = useState("");
  const [configurationPreview, setConfigurationPreview] = useState<PublicAgentConfigurationPreview | null>(null);
  const [configurationBusy, setConfigurationBusy] = useState(false);
  const [configurationRefresh, setConfigurationRefresh] = useState(0);
  const [linkPreviewStates, setLinkPreviewStates] = useState<Record<string, readonly SafeLinkPreviewProjection[]>>({});
  const [linkPreviewPreference, setLinkPreviewPreference] = useState<PublicLinkPreviewPreference | null>(null);
  const [linkPreviewPreferenceState, setLinkPreviewPreferenceState] = useState<LoadingState>("loading");
  const [linkPreviewBusy, setLinkPreviewBusy] = useState(false);
  const [linkPreviewBusyMessages, setLinkPreviewBusyMessages] = useState<ReadonlySet<string>>(new Set());
  const [stagedContexts, setStagedContexts] = useState<Record<string, StagedConversationContext>>({});
  const [stagedContextStates, setStagedContextStates] = useState<Record<string, "loading" | "ready" | "error">>({});
  const [conversationMedia, setConversationMedia] = useState<Record<string, ConversationMedia>>({});
  const [conversationMediaStates, setConversationMediaStates] = useState<Record<string, "loading" | "ready" | "error">>({});
  const linkPreviewReads = useRef(new Set<string>());
  const linkPreviewGeneration = useRef(0);
  const configurationRequest = useRef(0);
  const selectedConversationRef = useRef<string | null>(null);
  const noticeSequence = useRef(0);
  const pendingTabFocus = useRef<string | null>(null);
  const setNotice = (message: string) => {
    if (!message) {
      setNoticeState({ message: "", sequence: 0 });
      return;
    }
    noticeSequence.current += 1;
    setNoticeState({ message, sequence: noticeSequence.current });
  };
  const setConversationNotice = (conversationId: string, message: string) => {
    noticeSequence.current += 1;
    const entry = { message, sequence: noticeSequence.current };
    setConversationNotices((current) => ({ ...current, [conversationId]: entry }));
  };
  const draftKey = selectedConversationId ?? UNBOUND_DRAFT_KEY;
  const draft = drafts[draftKey] ?? "";
  const optimisticMessage = selectedConversationId ? optimisticMessages[selectedConversationId] ?? null : null;
  const sending = selectedConversationId ? sendingConversationIds.has(selectedConversationId) : false;
  const selectedConversationNotice = selectedConversationId
    ? conversationNotices[selectedConversationId]
    : undefined;
  const visibleNotice = selectedConversationNotice
    && selectedConversationNotice.sequence > notice.sequence
    ? selectedConversationNotice.message
    : notice.message;
  const detail = selectedConversationId ? details[selectedConversationId] ?? null : null;
  const selectedAgent = detail?.agent ?? agents.find((agent) => agent.id === selectedAgentId) ?? null;
  const configurationAgentId = selectedConversationId === null
    ? selectedAgentId
    : detail?.agent.id ?? null;
  const setupRequired = directAgentId === null;
  const selectedIsDirect = selectedAgent?.id === directAgentId && directAgentId !== null;
  const selectedNeedsCodexReadiness = selectedAgent?.runtime_type === "codex";
  const activeRun = detail?.current_run && ACTIVE_RUN_STATUSES.has(detail.current_run.status)
    ? detail.current_run
    : null;
  const activeRunId = activeRun?.id ?? null;
  const retryableRun = detail?.current_run
    && (RETRYABLE_RUN_STATUSES.has(detail.current_run.status)
      || (detail.current_run.status === "completed" && detail.current_run.partial))
    ? detail.current_run
    : null;
  const activeRunNeedsResponse = activeRun?.status === "waiting_for_approval"
    || activeRun?.status === "waiting_for_clarification";
  const activeRunVerified = activeRunId !== null && verifiedLiveRunIds.has(activeRunId);
  const selectedRunId = detail?.current_run?.id ?? null;
  const selectedRunPresentationEvents = selectedRunId ? runPresentationEvents[selectedRunId] ?? EMPTY_RUN_EVENTS : EMPTY_RUN_EVENTS;
  const initialWorkspaceLoading = selectedConversationId === null && conversationState === "loading";
  const composerIntent = conversationComposerIntent(draft);
  const draftIsValid = validConversationComposerText(composerIntent.text);
  const queueAtCapacity = (detail?.queued_turns.length ?? 0) >= 8;
  const stagedContext = selectedConversationId ? stagedContexts[selectedConversationId] ?? null : null;
  const stagedContextState = selectedConversationId ? stagedContextStates[selectedConversationId] ?? "loading" : "loading";
  const selectedMedia = selectedConversationId ? conversationMedia[selectedConversationId]?.runs ?? [] : [];
  const stagedAttachmentCount = stagedContext?.attachments.length ?? 0;
  const stagedContextCount = stagedAttachmentCount + (stagedContext?.contextPack ? 1 : 0);
  const hasStagedContext = stagedContextCount > 0;
  const contextWillStartImmediateRun = composerIntent.kind === "turn"
    && activeRun === null
    && (detail?.queued_turns.length ?? 0) === 0;
  const contextSendReady = !contextWillStartImmediateRun
    || stagedContextState === "ready";
  const contextDisabledReason = detail?.conversation.state !== "active"
    ? "Restore this Conversation before staging files."
    : activeRun !== null
      ? "Files cannot be staged or changed while this Conversation has an active Run."
      : (detail?.queued_turns.length ?? 0) > 0
        ? "Finish or cancel queued Turns before staging files."
        : configurationBusy
          ? "Wait for Agent configuration to finish before staging files."
          : null;
  const codexSendReady = !selectedNeedsCodexReadiness
    || codexReadiness === "ready"
    || activeRun !== null
    || (detail?.queued_turns.length ?? 0) > 0;
  const canSend = !!selectedConversationId
    && detail?.conversation.state === "active"
    && draftIsValid
    && !sending
    && (composerIntent.kind !== "steer" || activeRunVerified)
    && (composerIntent.kind === "steer" || !queueAtCapacity && codexSendReady)
    && contextSendReady;
  const loadedConversationIds = useMemo(() => new Set(conversations.map((item) => item.id)), [conversations]);
  const openConversations = useMemo(
    () => conversations.filter((item) => openConversationIds.has(item.id)),
    [conversations, openConversationIds],
  );
  const mounted = useRef(true);
  const compositionActive = useRef(false);
  const retryByConversationRef = useRef(new Map<string, OptimisticMessage>());
  const retryRunKeysRef = useRef(new Map<string, string>());
  const detailRefreshes = useRef(new Map<string, Promise<PublicConversationDetail>>());
  const pendingDetailRefreshes = useRef(new Set<string>());
  const editingTurnIdsRef = useRef<Record<string, string>>({});
  const queueEditorRevisions = useRef<Record<string, number>>({});
  const queueFocusRequest = useRef<{
    conversationId: string;
    editorRevision: number;
    turnId: string | null;
  } | null>(null);
  const editingTurnId = selectedConversationId
    ? editingTurnIds[selectedConversationId] ?? null
    : null;
  const displayedDetailState = selectedConversationId === null
    ? conversationState === "empty" ? "empty" : conversationState
    : detail?.conversation.id === selectedConversationId ? detailState : "loading";

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { selectedConversationRef.current = selectedConversationId; }, [selectedConversationId]);

  useEffect(() => {
    let cancelled = false;
    void readLinkPreviewPreference().then((preference) => {
      if (!cancelled) { setLinkPreviewPreference(preference); setLinkPreviewPreferenceState("ready"); }
    }).catch(() => { if (!cancelled) setLinkPreviewPreferenceState("unavailable"); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const request = configurationRequest.current + 1;
    configurationRequest.current = request;
    void Promise.resolve().then(async () => {
      if (!mounted.current || configurationRequest.current !== request) return;
      setConfigurationPreview(null);
      setAgentConfiguration(null);
      if (!configurationAgentId) {
        setAgentConfigurationState("empty");
        setConfigurationProvider("");
        setConfigurationModel("");
        return;
      }
      setAgentConfigurationState("loading");
      try {
        const payload = await fetchAgentConfiguration(configurationAgentId);
        if (!mounted.current || configurationRequest.current !== request) return;
        setAgentConfiguration(payload.configuration);
        setConfigurationProvider(payload.configuration.current.provider ?? "");
        setConfigurationModel(payload.configuration.current.model ?? "");
        setAgentConfigurationState("ready");
      } catch (error) {
        if (!mounted.current || configurationRequest.current !== request) return;
        const code = error instanceof PublicAgentConfigurationError ? error.code : "error";
        setAgentConfigurationState(code === "unavailable" ? "unavailable" : code === "unsupported" ? "unsupported" : "error");
      }
    });
  }, [configurationAgentId, configurationRefresh, selectedConversationId]);

  useEffect(() => {
    if (!activeRunId) return;
    void Promise.resolve().then(() => {
      if (mounted.current) setConfigurationPreview(null);
    });
  }, [activeRunId]);

  const setSelectedDraft = useCallback((value: string) => {
    setDrafts((current) => current[draftKey] === value
      ? current
      : { ...current, [draftKey]: value });
  }, [draftKey]);

  const trackLinkPreviews = useCallback(async (message: Pick<PublicConversationMessage, "conversation_id" | "id" | "revision">, action: "enqueue" | "read" | "retry") => {
    const key = linkPreviewKey(message);
    const generation = linkPreviewGeneration.current;
    if (action === "retry") setLinkPreviewBusyMessages((current) => new Set(current).add(key));
    try {
      let state = action === "read"
        ? await readLinkPreviews(message.conversation_id, message.id, message.revision)
        : await requestLinkPreviews(message.conversation_id, message.id, message.revision, action);
      if (!mounted.current || generation !== linkPreviewGeneration.current) return;
      setLinkPreviewStates((current) => mergeLinkPreviewState(current, key, state.previews));
      for (let attempt = 0; attempt < 36 && state.previews.some((preview) => preview.status === "pending"); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 750));
        if (!mounted.current || generation !== linkPreviewGeneration.current) return;
        state = await readLinkPreviews(message.conversation_id, message.id, message.revision);
        if (!mounted.current || generation !== linkPreviewGeneration.current) return;
        setLinkPreviewStates((current) => mergeLinkPreviewState(current, key, state.previews));
      }
      if (state.previews.some((preview) => preview.status === "pending")) {
        const terminal = state.previews.map((preview) => preview.status === "pending"
          ? { candidateOrdinal: preview.candidateOrdinal, status: "unavailable" as const }
          : preview);
        setLinkPreviewStates((current) => mergeLinkPreviewState(current, key, terminal));
        if (action === "retry") setConversationNotice(message.conversation_id, "Link preview processing timed out. The original links still work.");
      }
    } catch {
      if (mounted.current && generation === linkPreviewGeneration.current && action === "retry") {
        setConversationNotice(message.conversation_id, "Mentat could not retry those previews. The original links still work.");
      }
    } finally {
      if (action === "retry" && mounted.current) {
        setLinkPreviewBusyMessages((current) => {
          const next = new Set(current);
          next.delete(key);
          return next;
        });
      }
    }
  }, []);
  const retryTrackedLinkPreviews = useCallback((conversationId: string, messageId: string, revision: number) => {
    void trackLinkPreviews({ conversation_id: conversationId, id: messageId, revision }, "retry");
  }, [trackLinkPreviews]);

  useEffect(() => {
    if (!detail) return;
    for (const message of detail.messages) {
      if (message.role !== "user" || message.state !== "accepted" || !HAS_HTTPS_LINK.test(message.content.parts[0].text)) continue;
      const key = linkPreviewKey(message);
      if (linkPreviewReads.current.has(key)) continue;
      while (linkPreviewReads.current.size >= 600) {
        const oldest = linkPreviewReads.current.values().next().value as string | undefined;
        if (oldest === undefined) break;
        linkPreviewReads.current.delete(oldest);
      }
      linkPreviewReads.current.add(key);
      void trackLinkPreviews(message, "read");
    }
  }, [detail, trackLinkPreviews]);

  const setConversationEditor = useCallback((conversationId: string, turnId: string | null) => {
    const next = { ...editingTurnIdsRef.current };
    if (turnId === null) delete next[conversationId];
    else next[conversationId] = turnId;
    editingTurnIdsRef.current = next;
    queueEditorRevisions.current = {
      ...queueEditorRevisions.current,
      [conversationId]: (queueEditorRevisions.current[conversationId] ?? 0) + 1,
    };
    setEditingTurnIds(next);
  }, []);

  const captureQueueEditor = useCallback((conversationId: string): QueueEditorGuard => ({
    revision: queueEditorRevisions.current[conversationId] ?? 0,
    turnId: editingTurnIdsRef.current[conversationId] ?? null,
  }), []);

  const queueEditorIsCurrent = useCallback((conversationId: string, guard: QueueEditorGuard) => (
    (queueEditorRevisions.current[conversationId] ?? 0) === guard.revision
    && (editingTurnIdsRef.current[conversationId] ?? null) === guard.turnId
  ), []);

  const focusQueueTarget = useCallback((conversationId: string, turnId: string | null) => {
    queueFocusRequest.current = {
      conversationId,
      editorRevision: queueEditorRevisions.current[conversationId] ?? 0,
      turnId,
    };
    setQueueFocusSequence((current) => current + 1);
  }, []);

  useEffect(() => {
    const request = queueFocusRequest.current;
    if (!request) return;
    queueFocusRequest.current = null;
    if (selectedConversationId !== request.conversationId) {
      return;
    }
    if ((queueEditorRevisions.current[request.conversationId] ?? 0) !== request.editorRevision) {
      return;
    }
    const target = request.turnId
      ? document.getElementById(`queue-edit-${request.turnId}`)
      : null;
    (target ?? document.getElementById("console-prompt"))?.focus();
  }, [details, editingTurnIds, queueFocusSequence, selectedConversationId]);

  const refreshConversationDetail = useCallback((conversationId: string) => {
    const active = detailRefreshes.current.get(conversationId);
    if (active) {
      pendingDetailRefreshes.current.add(conversationId);
      return active;
    }
    const refresh = (async () => {
      let value: PublicConversationDetail | null = null;
      do {
        pendingDetailRefreshes.current.delete(conversationId);
        value = await fetchConversation(conversationId);
        if (mounted.current) {
          setDetails((current) => ({
            ...current,
            [conversationId]: mergeRefreshedConversationDetail(
              current[conversationId],
              value as PublicConversationDetail,
            ),
          }));
          setConversations((current) => current.some((item) => item.id === conversationId)
            ? current.map((item) => item.id === conversationId
              && value !== null
              && value.conversation.revision >= item.revision
              ? value.conversation
              : item)
            : value === null ? current : [value.conversation, ...current]);
        }
      } while (mounted.current && pendingDetailRefreshes.current.delete(conversationId));
      if (value === null) throw new PublicConversationError("unavailable");
      return value;
    })().finally(() => {
      detailRefreshes.current.delete(conversationId);
      pendingDetailRefreshes.current.delete(conversationId);
    });
    detailRefreshes.current.set(conversationId, refresh);
    return refresh;
  }, []);

  const refreshConversationContext = useCallback(async (conversationId: string) => {
    setStagedContextStates((current) => ({ ...current, [conversationId]: "loading" }));
    try {
      const context = await readStagedConversationContext(conversationId);
      if (!mounted.current) return;
      setStagedContexts((current) => ({ ...current, [conversationId]: context }));
      setStagedContextStates((current) => ({ ...current, [conversationId]: "ready" }));
    } catch {
      if (!mounted.current) return;
      setStagedContexts((current) => {
        if (!(conversationId in current)) return current;
        const next = { ...current };
        delete next[conversationId];
        return next;
      });
      setStagedContextStates((current) => ({ ...current, [conversationId]: "error" }));
    }
  }, []);

  const refreshActivityHints = useCallback(async () => {
    const value = await fetchActivity();
    if (mounted.current) { setActivity(value); setActivityState("ready"); }
    return value;
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([fetchConversations(), fetchActivity()]).then(([conversationResult, activityResult]) => {
      if (cancelled) return;
      if (conversationResult.status === "fulfilled") {
        const payload = conversationResult.value;
        setConversations(payload.conversations); setConversationCursor(payload.next_cursor); setAgents(payload.agents); setDirectAgentId(payload.direct_agent_id);
        setSelectedAgentId((current) => current ?? payload.direct_agent_id);
        const activeConversationIds = payload.conversations.filter((item) => item.state === "active").map((item) => item.id);
        const initialConversationId = activeConversationIds[0] ?? payload.conversations[0]?.id ?? null;
        setOpenConversationIds(new Set(activeConversationIds.length ? activeConversationIds : initialConversationId ? [initialConversationId] : []));
        setSelectedConversationId((current) => current && payload.conversations.some((item) => item.id === current) ? current : initialConversationId);
        setConversationState(payload.conversations.length ? "ready" : "empty");
      } else setConversationState(statusFrom(conversationResult.reason));
      if (activityResult.status === "fulfilled") { setActivity(activityResult.value); setActivityState("ready"); } else setActivityState(statusFrom(activityResult.reason));
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedConversationId) return;
    let cancelled = false;
    void refreshConversationDetail(selectedConversationId).then(() => { if (!cancelled) setDetailState("ready"); }).catch((error: unknown) => { if (!cancelled) setDetailState(statusFrom(error)); });
    return () => { cancelled = true; };
  }, [refreshConversationDetail, selectedConversationId]);

  useEffect(() => {
    if (!selectedConversationId || detail?.conversation.id !== selectedConversationId) return;
    const conversationId = selectedConversationId;
    let cancelled = false;
    void Promise.resolve().then(() => refreshConversationContext(conversationId));
    void Promise.resolve().then(() => {
      if (!cancelled) setConversationMediaStates((current) => ({ ...current, [conversationId]: "loading" }));
    });
    void Promise.allSettled([
      readConversationMedia(conversationId),
    ]).then(([mediaResult]) => {
      if (cancelled || !mounted.current) return;
      if (mediaResult.status === "fulfilled") {
        setConversationMedia((current) => ({ ...current, [conversationId]: mediaResult.value }));
        setConversationMediaStates((current) => ({ ...current, [conversationId]: "ready" }));
      } else {
        setConversationMedia((current) => {
          if (!(conversationId in current)) return current;
          const next = { ...current };
          delete next[conversationId];
          return next;
        });
        setConversationMediaStates((current) => ({ ...current, [conversationId]: "error" }));
      }
    });
    return () => { cancelled = true; };
  }, [detail?.conversation.id, detail?.conversation.revision, refreshConversationContext, selectedConversationId]);

  useEffect(() => {
    if (!selectedConversationId || !activeRunId || typeof EventSource === "undefined") return;
    const conversationId = selectedConversationId;
    const runId = activeRunId;
    let closed = false;
    let source: EventSource;
    try {
      source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
    } catch {
      return;
    }
    const receive = (event: Event, envelope: "many" | "single", mode: "merge" | "replace" | null) => {
      if (closed) return;
      const data = (event as MessageEvent<string>).data;
      if (typeof data !== "string") return;
      const summary = liveSummary(data, runId);
      if (summary) setLiveProgress({ runId, summary });
      const presentation = mode === null ? null : livePresentationEvents(data, runId, envelope);
      if (presentation !== null && mode !== null) setRunPresentationEvents((current) => {
        const merged = new Map(mode === "replace" ? [] : (current[runId] ?? []).map((item) => [item.sequence, item]));
        presentation.forEach((item) => merged.set(item.sequence, item));
        const next = Object.fromEntries(Object.entries(current).slice(-15));
        next[runId] = [...merged.values()].sort((left, right) => left.sequence - right.sequence).slice(-100);
        return next;
      });
      void refreshConversationDetail(conversationId).then(() => {
        if (!closed) setVerifiedLiveRunIds((current) => new Set(current).add(runId));
      }).catch(() => {
        if (!closed) {
          setVerifiedLiveRunIds((current) => { const next = new Set(current); next.delete(runId); return next; });
          setLiveProgress({ runId, summary: "Live updates are reconnecting…" });
        }
      });
    };
    source.addEventListener("snapshot", (event) => {
      const data = (event as MessageEvent<string>).data;
      receive(event, "many", typeof data === "string" ? snapshotPresentationMode(data) : null);
    });
    source.addEventListener("reset", (event) => receive(event, "many", "replace"));
    source.addEventListener("timeline", (event) => receive(event, "single", "merge"));
    source.onerror = () => {
      if (!closed) {
        setVerifiedLiveRunIds((current) => { const next = new Set(current); next.delete(runId); return next; });
        setLiveProgress({ runId, summary: "Live updates are reconnecting…" });
      }
    };
    return () => { closed = true; source.close(); };
  }, [activeRunId, refreshConversationDetail, selectedConversationId]);

  useEffect(() => {
    if (!activeRunId || !activeRunNeedsResponse || !activeRunVerified) return;
    const runId = activeRunId;
    let cancelled = false;
    void fetchPendingRunRequest(runId).then((request) => {
      if (cancelled) return;
      setPendingResponse(null);
      setClarificationText("");
      setPendingAction({ request, runId });
      setPendingActionState({ runId, state: "ready" });
    }).catch(() => {
      if (cancelled) return;
      setPendingAction(null);
      setPendingActionState({ runId, state: "unavailable" });
    });
    return () => { cancelled = true; };
  }, [activeRunId, activeRunNeedsResponse, activeRunVerified]);

  const hasActiveActivity = activity?.activity.some((item) => item.conversations.some(
    (conversation) => ACTIVE_RUN_STATUSES.has(conversation.run_status)
      || conversation.run_status === "reconciling",
  )) ?? false;
  const shouldPollActivity = hasActiveActivity || activityState !== "ready";
  useEffect(() => {
    if (!shouldPollActivity) return;
    let cancelled = false;
    let inFlight = false;
    const timer = window.setInterval(() => {
      if (cancelled || inFlight) return;
      inFlight = true;
      void refreshActivityHints().catch((error: unknown) => {
        if (!cancelled) setActivityState(statusFrom(error));
      }).finally(() => { inFlight = false; });
    }, 4_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [refreshActivityHints, shouldPollActivity]);

  const loadMoreConversations = useCallback(() => {
    if (!conversationCursor || loadingConversations) return;
    setLoadingConversations(true);
    void fetchConversations(conversationCursor).then((payload) => { if (mounted.current) { setConversations((current) => [...current, ...payload.conversations.filter((item) => !current.some((existing) => existing.id === item.id))]); setConversationCursor(payload.next_cursor); } }).catch((error: unknown) => setNotice(`Could not load older Conversations (${statusFrom(error)}).`)).finally(() => setLoadingConversations(false));
  }, [conversationCursor, loadingConversations]);

  const loadOlder = useCallback(() => {
    if (!detail?.next_message_cursor || detail.messages.length >= MAX_TRANSCRIPT_MESSAGES || loadingOlder || !selectedConversationId) return;
    setLoadingOlder(true);
    void fetchConversation(selectedConversationId, detail.next_message_cursor).then((older) => { if (mounted.current) setDetails((current) => ({ ...current, [selectedConversationId]: mergeOlderConversationDetail(current[selectedConversationId], older) })); }).catch((error: unknown) => setNotice(`Could not load older messages (${statusFrom(error)}).`)).finally(() => setLoadingOlder(false));
  }, [detail, loadingOlder, selectedConversationId]);

  const selectConversation = useCallback((conversationId: string) => {
    setOpenConversationIds((current) => new Set(current).add(conversationId));
    setDetailState(details[conversationId] ? "ready" : "loading");
    setSelectedConversationId(conversationId);
  }, [details]);

  const closeConversation = useCallback((conversationId: string) => {
    setOpenConversationIds((current) => {
      const next = new Set(current);
      next.delete(conversationId);
      return next;
    });
    if (selectedConversationId === conversationId) {
      const successor = openConversations.find((item) => item.id !== conversationId);
      pendingTabFocus.current = successor?.id ?? "recent";
      setSelectedConversationId(successor?.id ?? null);
      setDetailState(successor && details[successor.id] ? "ready" : successor ? "loading" : "empty");
    }
  }, [details, openConversations, selectedConversationId]);

  useEffect(() => {
    const target = pendingTabFocus.current;
    if (target === null) return;
    pendingTabFocus.current = null;
    const element = target === "recent"
      ? document.getElementById("recent-conversations-summary")
      : document.getElementById(`conversation-tab-${target}`);
    element?.focus();
  }, [openConversationIds, selectedConversationId]);

  const selectActivityConversation = useCallback((conversationId: string) => {
    setNotice("");
    if (loadedConversationIds.has(conversationId)) { selectConversation(conversationId); return; }
    void refreshConversationDetail(conversationId).then(() => { if (mounted.current) selectConversation(conversationId); }).catch(() => setNotice("Mentat could not reopen that Conversation safely."));
  }, [loadedConversationIds, refreshConversationDetail, selectConversation]);

  async function createNewConversation() {
    if (creating || !selectedAgentId) return;
    setCreating(true); setNotice("Creating a new Conversation…");
    try { const created = await createConversation(selectedAgentId); setDetails((current) => ({ ...current, [created.conversation.id]: created })); setDrafts((current) => { const next = { ...current }; const carriedDraft = next[UNBOUND_DRAFT_KEY] ?? ""; delete next[UNBOUND_DRAFT_KEY]; if (carriedDraft) next[created.conversation.id] = carriedDraft; return next; }); setOpenConversationIds((current) => new Set(current).add(created.conversation.id)); setDetailState("ready"); setSelectedConversationId(created.conversation.id); setConversations((current) => [created.conversation, ...current.filter((item) => item.id !== created.conversation.id)]); setConversationState("ready"); setNotice("Conversation created and ready for a prompt."); } catch { setNotice("Mentat could not create that Conversation. Try again."); } finally { setCreating(false); }
  }

  async function toggleLinkPreviewPreference() {
    if (!linkPreviewPreference || linkPreviewBusy) return;
    linkPreviewGeneration.current += 1;
    setLinkPreviewBusy(true);
    try {
      const updated = await updateLinkPreviewPreference(!linkPreviewPreference.enabled, linkPreviewPreference.revision);
      setLinkPreviewPreference(updated);
      if (!updated.enabled) {
        setLinkPreviewStates((current) => Object.fromEntries(Object.entries(current).map(([key, previews]) => [key, previews.map((preview) => ({ candidateOrdinal: preview.candidateOrdinal, status: preview.status === "blocked" ? "blocked" as const : "disabled" as const }))])));
        setNotice("Rich link previews are off. Existing plain links remain available.");
      } else {
        setLinkPreviewStates({});
        linkPreviewReads.current.clear();
        if (detail) {
          for (const message of detail.messages) {
            if (message.role === "user" && message.state === "accepted" && HAS_HTTPS_LINK.test(message.content.parts[0].text)) {
              const key = linkPreviewKey(message);
              linkPreviewReads.current.add(key);
              void trackLinkPreviews(message, "read");
            }
          }
        }
        setNotice("Rich link previews are on. Old Messages are not fetched unless you choose Retry preview.");
      }
    } catch {
      setNotice("Mentat could not verify the link preview setting. Nothing was changed.");
      try {
        const preference = await readLinkPreviewPreference();
        if (mounted.current) {
          setLinkPreviewPreference(preference);
          setLinkPreviewPreferenceState("ready");
          if (preference.enabled && detail) {
            for (const message of detail.messages) {
              if (message.role !== "user" || message.state !== "accepted" || !HAS_HTTPS_LINK.test(message.content.parts[0].text)) continue;
              const key = linkPreviewKey(message);
              linkPreviewReads.current.delete(key);
              linkPreviewReads.current.add(key);
              void trackLinkPreviews(message, "read");
            }
          }
        }
      } catch {
        if (mounted.current) setLinkPreviewPreferenceState("unavailable");
      }
    } finally {
      setLinkPreviewBusy(false);
    }
  }

  async function clearPreviewCache() {
    if (linkPreviewBusy) return;
    linkPreviewGeneration.current += 1;
    setLinkPreviewBusy(true);
    try {
      await clearLinkPreviewCache();
      setLinkPreviewStates((current) => Object.fromEntries(Object.entries(current).map(([key, previews]) => [key, previews.map((preview) => ({ candidateOrdinal: preview.candidateOrdinal, status: preview.status === "blocked" ? "blocked" as const : linkPreviewPreference?.enabled ? "unavailable" as const : "disabled" as const }))])));
      setNotice("The disposable link preview cache was cleared. Plain links were unchanged.");
    } catch {
      setNotice("Mentat could not verify cache deletion. Plain links were unchanged.");
      try {
        const preference = await readLinkPreviewPreference();
        if (mounted.current) {
          setLinkPreviewPreference(preference);
          setLinkPreviewPreferenceState("ready");
          if (preference.enabled && detail) {
            for (const message of detail.messages) {
              if (message.role !== "user" || message.state !== "accepted" || !HAS_HTTPS_LINK.test(message.content.parts[0].text)) continue;
              const key = linkPreviewKey(message);
              linkPreviewReads.current.delete(key);
              linkPreviewReads.current.add(key);
              void trackLinkPreviews(message, "read");
            }
          }
        }
      } catch {
        if (mounted.current) setLinkPreviewPreferenceState("unavailable");
      }
    } finally {
      setLinkPreviewBusy(false);
    }
  }

  function chooseConfigurationProvider(provider: string) {
    setConfigurationPreview(null);
    setConfigurationProvider(provider);
    const selected = agentConfiguration?.providers.find((item) => item.id === provider);
    setConfigurationModel(
      provider === agentConfiguration?.current.provider
        && selected?.models.includes(agentConfiguration.current.model ?? "")
        ? agentConfiguration.current.model ?? ""
        : selected?.models[0] ?? "",
    );
  }

  async function prepareAgentConfiguration() {
    if (!configurationAgentId || !configurationProvider || !configurationModel || configurationBusy || activeRun) return;
    const targetAgentId = configurationAgentId;
    const targetConversationId = selectedConversationId;
    const request = configurationRequest.current;
    setConfigurationBusy(true);
    if (targetConversationId) setConversationNotice(targetConversationId, "Verifying the exact next-Run configuration…");
    else setNotice("Verifying the exact next-Run configuration…");
    try {
      const prepared = await previewAgentConfiguration(targetAgentId, configurationProvider, configurationModel);
      if (configurationRequest.current === request && selectedConversationRef.current === targetConversationId) {
        setConfigurationPreview(prepared);
        if (targetConversationId) setConversationNotice(targetConversationId, "Review the verified Agent configuration, then Confirm.");
        else setNotice("Review the verified Agent configuration, then Confirm.");
      }
    } catch (error) {
      if (configurationRequest.current === request && selectedConversationRef.current === targetConversationId) {
        const code = error instanceof PublicAgentConfigurationError ? error.code : "error";
        const message = code === "conflict" ? "The Agent or active Run changed. Refresh configuration and try again." : code === "partial" ? "Hermes could not verify configuration or rollback. Review the Agent in Hermes before running it." : "Mentat could not verify that configuration. Nothing was changed.";
        if (targetConversationId) setConversationNotice(targetConversationId, message); else setNotice(message);
      }
    } finally { setConfigurationBusy(false); }
  }

  async function applyAgentConfiguration() {
    if (!configurationPreview || !configurationAgentId || configurationBusy || activeRun) return;
    const targetAgentId = configurationAgentId;
    const targetConversationId = selectedConversationId;
    const request = configurationRequest.current;
    const prepared = configurationPreview;
    setConfigurationBusy(true);
    try {
      const result = await confirmAgentConfiguration(targetAgentId, prepared.target.provider, prepared.target.model, prepared.confirmation_id);
      setConfigurationRefresh((current) => current + 1);
      if (configurationRequest.current !== request || selectedConversationRef.current !== targetConversationId) return;
      setAgentConfiguration(result.configuration);
      setConfigurationProvider(result.configuration.current.provider ?? "");
      setConfigurationModel(result.configuration.current.model ?? "");
      setConfigurationPreview(null);
      if (targetConversationId) setConversationNotice(targetConversationId, "Agent configuration verified. The next Run will use it; active Run evidence was unchanged.");
      else setNotice("Agent configuration verified. The next Run will use it.");
    } catch (error) {
      if (configurationRequest.current === request && selectedConversationRef.current === targetConversationId) {
        const code = error instanceof PublicAgentConfigurationError ? error.code : "error";
        setConfigurationPreview(null);
        const message = code === "conflict" ? "Configuration changed after preview. Nothing was retried; preview it again." : code === "partial" ? "Hermes did not verify the change or rollback. Review the Agent in Hermes before running it." : "Mentat could not apply that configuration. Nothing was retried.";
        if (targetConversationId) setConversationNotice(targetConversationId, message); else setNotice(message);
      }
    } finally { setConfigurationBusy(false); }
  }

  async function setConversationArchived(conversation: PublicConversation, archived: boolean) {
    if (archiveBusyIds.has(conversation.id)) return;
    setArchiveBusyIds((current) => new Set(current).add(conversation.id));
    setConversationNotice(conversation.id, archived ? "Archiving this Conversation…" : "Restoring this Conversation…");
    try {
      const result = await archiveConversation(conversation.id, conversation.revision, archived);
      setConversations((current) => current.map((item) => item.id === conversation.id ? result.conversation : item));
      setDetails((current) => current[conversation.id]
        ? { ...current, [conversation.id]: { ...current[conversation.id], conversation: result.conversation } }
        : current);
      setConversationNotice(conversation.id, archived
        ? "Conversation archived. Active work, Messages, and Runs were not changed."
        : "Conversation restored and ready for work.");
    } catch (error) {
      setConversationNotice(conversation.id, errorCode(error) === "conflict"
        ? "That Conversation changed before its archive state could be updated."
        : "Mentat could not verify the Conversation archive change.");
      void refreshConversationDetail(conversation.id).catch(() => undefined);
    } finally {
      setArchiveBusyIds((current) => { const next = new Set(current); next.delete(conversation.id); return next; });
    }
  }

  async function preparePendingResponse(response: RunActionResponse) {
    if (!pendingAction || !selectedConversationId || runActionBusy || pendingAction.runId !== activeRunId) return;
    const runId = pendingAction.runId;
    const conversationId = selectedConversationId;
    setRunActionBusy(true);
    setConversationNotice(conversationId, "Reviewing the exact pending request…");
    try {
      const preview = await previewRunResponse(runId, response);
      if (preview.run_id !== activeRunId) throw new PublicRunActionError("conflict");
      setPendingResponse({ confirmationId: preview.confirmation_id, response, runId });
      setConversationNotice(conversationId, "Response preview is current. Confirm to send it.");
    } catch (error) {
      setConversationNotice(conversationId, error instanceof PublicRunActionError && error.code === "conflict" ? "The pending request changed before preview. Nothing was sent." : "Mentat could not verify that pending request. Nothing was sent.");
      void refreshConversationDetail(conversationId).catch(() => undefined);
    } finally {
      setRunActionBusy(false);
    }
  }

  async function submitPendingResponse() {
    if (!pendingResponse || runActionBusy || pendingResponse.runId !== activeRunId || !selectedConversationId) return;
    const conversationId = selectedConversationId;
    setRunActionBusy(true);
    setConversationNotice(conversationId, "Confirming the exact pending response…");
    try {
      await confirmRunResponse(pendingResponse.runId, pendingResponse.response, pendingResponse.confirmationId);
      setPendingResponse(null);
      setPendingAction(null);
      setPendingActionState(null);
      setClarificationText("");
      setConversationNotice(conversationId, "Response accepted. Mentat is reconciling the exact Run.");
      await refreshConversationDetail(conversationId);
      void refreshActivityHints().catch(() => undefined);
    } catch (error) {
      const code = error instanceof PublicRunActionError ? error.code : "error";
      setPendingResponse(null);
      setConversationNotice(conversationId, code === "partial" ? "The runtime may have accepted this response, but Mentat could not verify it. Nothing will retry automatically." : code === "conflict" ? "The pending request changed. Nothing was sent." : "Mentat could not verify the response. Nothing was retried.");
      void refreshConversationDetail(conversationId).catch(() => undefined);
    } finally {
      setRunActionBusy(false);
    }
  }

  async function prepareStop() {
    if (!activeRunId || !selectedConversationId || runActionBusy) return;
    const runId = activeRunId;
    const conversationId = selectedConversationId;
    setRunActionBusy(true);
    setConversationNotice(conversationId, "Reviewing the exact Stop target…");
    try {
      const preview = await previewRunStop(runId);
      if (preview.run_id !== activeRunId) throw new PublicRunActionError("conflict");
      setStopConfirmation({ confirmationId: preview.confirmation_id, runId });
      setConversationNotice(conversationId, "Stop preview is current. Confirm to request Stop.");
    } catch (error) {
      const code = error instanceof PublicRunActionError ? error.code : "error";
      setConversationNotice(conversationId, code === "unsupported" ? "This active Run does not support Stop." : code === "conflict" ? "The active Run changed before Stop could be previewed." : "Mentat could not verify the Stop target.");
      void refreshConversationDetail(conversationId).catch(() => undefined);
    } finally {
      setRunActionBusy(false);
    }
  }

  async function submitStop() {
    if (!stopConfirmation || stopConfirmation.runId !== activeRunId || !selectedConversationId || runActionBusy) return;
    const conversationId = selectedConversationId;
    setRunActionBusy(true);
    setConversationNotice(conversationId, "Requesting Stop for the exact active Run…");
    try {
      await confirmRunStop(stopConfirmation.runId, stopConfirmation.confirmationId);
      setStopConfirmation(null);
      setConversationNotice(conversationId, "Stop was requested. The Conversation remains open and its queue is paused.");
      await refreshConversationDetail(conversationId);
      void refreshActivityHints().catch(() => undefined);
    } catch (error) {
      const code = error instanceof PublicRunActionError ? error.code : "error";
      setStopConfirmation(null);
      setConversationNotice(conversationId, code === "conflict" ? "The Run changed before Stop confirmation. Nothing was retried." : "Mentat could not verify Stop. Nothing was retried automatically.");
      void refreshConversationDetail(conversationId).catch(() => undefined);
    } finally {
      setRunActionBusy(false);
    }
  }

  async function continueRun(action: "retry" | "resume") {
    if (!retryableRun || !selectedConversationId || retryBusyRunIds.has(retryableRun.id)) return;
    const conversationId = selectedConversationId;
    const sourceRunId = retryableRun.id;
    const keySlot = `${action}:${sourceRunId}`;
    const key = retryRunKeysRef.current.get(keySlot) ?? crypto.randomUUID();
    retryRunKeysRef.current.set(keySlot, key);
    setRetryBusyRunIds((current) => new Set(current).add(sourceRunId));
    setConversationNotice(conversationId, `Starting one exact ${readable(action)} Run…`);
    try {
      const operation = action === "retry" ? retryConversationRun : resumeConversationRun;
      const result = await operation(conversationId, sourceRunId, key);
      retryRunKeysRef.current.delete(keySlot);
      if (!result.duplicate) setVerifiedLiveRunIds((current) => new Set(current).add(result.run.id));
      setConversationNotice(conversationId, result.duplicate
        ? `This ${readable(action)} was already accepted. No duplicate Run was started.`
        : `${readable(action)} accepted as a new Run. The prior attempt remains in history.`);
      await refreshConversationDetail(conversationId);
      void refreshActivityHints().catch(() => undefined);
    } catch (error) {
      const code = errorCode(error);
      if (code === "idempotency_conflict") retryRunKeysRef.current.delete(keySlot);
      setConversationNotice(conversationId, code === "capacity_unavailable"
        ? `Runtime capacity is unavailable. No ${readable(action)} Run was created.`
        : code === "conflict" || code === "active_run"
          ? `The source Run changed before ${readable(action)} admission. Nothing was started.`
          : `Mentat could not confirm ${readable(action)} admission. The exact action key was kept; try again to replay safely.`);
      void refreshConversationDetail(conversationId).catch(() => undefined);
    } finally {
      setRetryBusyRunIds((current) => { const next = new Set(current); next.delete(sourceRunId); return next; });
    }
  }

  async function recheckCodex() {
    if (checkingCodex) return;
    if (selectedConversationId) setConversationNotices((current) => { const next = { ...current }; delete next[selectedConversationId]; return next; });
    setCheckingCodex(true); setNotice("Checking Codex readiness…");
    try {
      const readiness = await fetchCodexReadiness();
      setCodexReadiness(readiness.state);
      if (readiness.state === "ready") {
        const refreshed = await fetchConversations();
        setConversations(refreshed.conversations); setConversationCursor(refreshed.next_cursor); setAgents(refreshed.agents); setDirectAgentId(refreshed.direct_agent_id);
        setSelectedAgentId((current) => current ?? refreshed.direct_agent_id);
        setNotice("Codex is signed in and ready.");
      } else if (readiness.state === "sign_in_required") setNotice("Run codex login in a terminal, complete the browser sign-in, then Recheck.");
      else if (readiness.state === "cli_missing") setNotice("Install the Codex CLI, run codex login, then restart Mentat.");
      else setNotice("Codex readiness could not be confirmed. Recheck when the local CLI is available.");
    } catch { setCodexReadiness("unavailable"); setNotice("Codex readiness could not be checked safely."); }
    finally { setCheckingCodex(false); }
  }

  async function sendTurn() {
    if (!canSend || !selectedConversationId || !detail) return;
    const conversationId = selectedConversationId;
    const draftAtSend = draft;
    if (composerIntent.kind === "steer") {
      if (!activeRun) {
        setConversationNotice(conversationId, "There is no active Run to steer. Nothing was sent, and the draft was kept.");
        return;
      }
      if (activeRun.status !== "running") {
        setConversationNotice(conversationId, `This Run is ${readable(activeRun.status)} and cannot accept steering. Nothing was sent, and the draft was kept.`);
        return;
      }
      if (!selectedAgent?.capabilities.includes("run.message")) {
        setConversationNotice(conversationId, "This Agent does not support steering. Nothing was sent, and the draft was kept.");
        return;
      }
      setSendingConversationIds((current) => new Set(current).add(conversationId));
      setConversationNotice(conversationId, "Steering the exact active Run…");
      try {
        await steerConversation(conversationId, activeRun.id, composerIntent.text);
        setDrafts((current) => current[conversationId] === draftAtSend
          ? { ...current, [conversationId]: "" }
          : current);
        setConversationNotice(conversationId, "Steering was accepted by the exact active Run. It was not queued.");
      } catch (error) {
        const code = errorCode(error);
        const message = code === "partial"
          ? "The runtime may have received this steering, but Mentat could not verify it. Nothing was queued; the draft was kept."
          : code === "unsupported"
            ? "This active Run does not support steering. Nothing was sent, and the draft was kept."
            : code === "unavailable"
              ? "Steering is temporarily unavailable. Nothing was sent, nothing was queued, and the draft was kept."
            : code === "conflict" || code === "not_found"
              ? "The active Run changed before steering could be verified. Nothing was queued; the draft was kept."
              : "Mentat could not verify steering. Nothing was queued, and the draft was kept.";
        setConversationNotice(conversationId, message);
        void refreshConversationDetail(conversationId).catch(() => undefined);
      } finally {
        setSendingConversationIds((current) => { const next = new Set(current); next.delete(conversationId); return next; });
      }
      return;
    }
    const text = composerIntent.text;
    const reusable = retryByConversationRef.current.get(conversationId);
    const request: OptimisticMessage = reusable?.text === text
      ? reusable
      : { conversationId, key: crypto.randomUUID(), text };
    retryByConversationRef.current.set(conversationId, request);
    setOptimisticMessages((current) => ({ ...current, [conversationId]: request }));
    setSendingConversationIds((current) => new Set(current).add(conversationId));
    setConversationNotice(conversationId, "Submitting the exact Turn…");
    try {
      const submitted = await submitConversationTurn(conversationId, text, request.key);
      setOptimisticMessages((current) => { const next = { ...current }; delete next[conversationId]; return next; });
      setDetails((current) => {
        const existing = current[conversationId];
        if (!existing) return current;
        return { ...current, [conversationId]: mergeTurnSubmission(existing, submitted) };
      });
      setConversations((current) => [submitted.conversation, ...current.filter((item) => item.id !== submitted.conversation.id)]);
      if (submitted.run && !submitted.duplicate) setVerifiedLiveRunIds((current) => new Set(current).add(submitted.run!.id));
      setDrafts((current) => current[conversationId] === draftAtSend
        ? { ...current, [conversationId]: "" }
        : current);
      retryByConversationRef.current.delete(conversationId);
      setStagedContexts((current) => {
        if (!(conversationId in current)) return current;
        const next = { ...current };
        delete next[conversationId];
        return next;
      });
      setStagedContextStates((current) => ({ ...current, [conversationId]: "loading" }));
      void Promise.allSettled([
        readStagedConversationContext(conversationId),
        readConversationMedia(conversationId),
      ]).then(([stagedResult, mediaResult]) => {
        if (!mounted.current) return;
        if (stagedResult.status === "fulfilled") {
          setStagedContexts((current) => ({ ...current, [conversationId]: stagedResult.value }));
          setStagedContextStates((current) => ({ ...current, [conversationId]: "ready" }));
        } else {
          setStagedContextStates((current) => ({ ...current, [conversationId]: "error" }));
        }
        if (mediaResult.status === "fulfilled") {
          setConversationMedia((current) => ({ ...current, [conversationId]: mediaResult.value }));
          setConversationMediaStates((current) => ({ ...current, [conversationId]: "ready" }));
        } else {
          setConversationMedia((current) => { const next = { ...current }; delete next[conversationId]; return next; });
          setConversationMediaStates((current) => ({ ...current, [conversationId]: "error" }));
        }
      });
      const submittedNotice = submitted.disposition === "pending"
        ? "Turn queued behind the current work."
        : submitted.disposition === "blocked"
          ? `Turn saved, but the queue is blocked${submitted.turn.blocked_reason ? ` by ${readable(submitted.turn.blocked_reason)}` : ""}. Use Continue after reviewing it.`
          : submitted.disposition === "rejected"
            ? "The Turn is saved, but the runtime rejected this Run. The queue is paused."
            : submitted.disposition === "unknown"
              ? "The Turn is saved, but runtime acceptance is unknown. The queue is paused and will not retry automatically."
              : submitted.disposition === "accepted"
                ? submitted.duplicate ? "This Turn was already accepted; no duplicate Run was started." : "Turn accepted. The Run is now visible in this Conversation."
                : "The exact Turn is already being submitted.";
      setConversationNotice(conversationId, submittedNotice);
      if (!submitted.duplicate && submitted.message.role === "user" && HAS_HTTPS_LINK.test(submitted.message.content.parts[0].text)) {
        void trackLinkPreviews(submitted.message, "enqueue");
      }
      void refreshConversationDetail(conversationId).catch(() => undefined);
      void refreshActivityHints().catch(() => undefined);
    } catch (error) {
      setOptimisticMessages((current) => { const next = { ...current }; delete next[conversationId]; return next; });
      setDrafts((current) => ({ ...current, [conversationId]: draftAtSend }));
      const code = errorCode(error);
      if (code === "sign_in_required" || code === "cli_missing") {
        setCodexReadiness(code);
        setConversationNotice(conversationId, code === "sign_in_required" ? "Codex sign-in is required. Run codex login, then Recheck." : "The Codex CLI is not available yet.");
      } else if (code === "active_run") {
        setConversationNotice(conversationId, "The Run changed during admission. The draft was kept; refresh completed before another Send.");
        void refreshConversationDetail(conversationId).catch(() => undefined);
      }
      else if (code === "capacity_unavailable") setConversationNotice(conversationId, "Runtime capacity is unavailable. The draft was kept.");
      else if (code === "idempotency_conflict") { retryByConversationRef.current.delete(conversationId); setConversationNotice(conversationId, "This Send key no longer matches the draft. Please send again."); }
      else if (code === "conflict") setConversationNotice(conversationId, "The Conversation changed before this Turn could be admitted. The draft was kept.");
      else setConversationNotice(conversationId, "Mentat could not confirm admission. The draft and exact retry key were kept; Send again to retry safely.");
    } finally { setSendingConversationIds((current) => { const next = new Set(current); next.delete(conversationId); return next; }); }
  }

  async function editQueuedTurn(turn: PublicQueuedConversationTurn) {
    if (!selectedConversationId || queueBusyTurnIds.has(turn.id)) return;
    const conversationId = selectedConversationId;
    const text = queueEditDrafts[turn.id] ?? turn.text;
    if (!validConversationComposerText(text) || text === turn.text) return;
    const editorGuard = captureQueueEditor(conversationId);
    const restoreFocus = editorGuard.turnId === turn.id;
    setQueueBusyTurnIds((current) => new Set(current).add(turn.id));
    try {
      const mutation = await editConversationTurn(conversationId, turn.id, turn.revision, turn.message_revision, text);
      setDetails((current) => current[conversationId] ? { ...current, [conversationId]: mergeQueueMutation(current[conversationId], mutation) } : current);
      setConversations((current) => current.map((item) => item.id === conversationId ? mutation.conversation : item));
      const focusCommitIsCurrent = restoreFocus
        && queueEditorIsCurrent(conversationId, editorGuard);
      if (focusCommitIsCurrent) setConversationEditor(conversationId, null);
      setQueueEditDrafts((current) => { const next = { ...current }; delete next[turn.id]; return next; });
      setConversationNotice(conversationId, `Queued Turn #${turn.queue_ordinal} was updated.`);
      if (focusCommitIsCurrent) focusQueueTarget(conversationId, turn.id);
    } catch (error) {
      setConversationNotice(conversationId, errorCode(error) === "conflict" ? "That queued Turn changed. Mentat kept your edit so you can compare it with the refreshed queue." : "Mentat could not verify that queue edit. Your edit was kept.");
      void refreshConversationDetail(conversationId).catch(() => undefined);
    } finally {
      setQueueBusyTurnIds((current) => { const next = new Set(current); next.delete(turn.id); return next; });
    }
  }

  async function cancelQueuedTurn(turn: PublicQueuedConversationTurn) {
    if (!selectedConversationId || queueBusyTurnIds.has(turn.id)) return;
    const conversationId = selectedConversationId;
    const focusTurnId = queueFocusSuccessor(detail?.queued_turns ?? [], turn.id);
    const editorGuard = captureQueueEditor(conversationId);
    const restoreFocus = editorGuard.turnId === null || editorGuard.turnId === turn.id;
    setQueueBusyTurnIds((current) => new Set(current).add(turn.id));
    try {
      const mutation = await cancelConversationTurn(conversationId, turn.id, turn.revision, turn.message_revision);
      setDetails((current) => current[conversationId] ? { ...current, [conversationId]: mergeQueueMutation(current[conversationId], mutation) } : current);
      setConversations((current) => current.map((item) => item.id === conversationId ? mutation.conversation : item));
      setQueueEditDrafts((current) => {
        if (!(turn.id in current)) return current;
        const next = { ...current };
        delete next[turn.id];
        return next;
      });
      let refreshed = true;
      try {
        await refreshConversationDetail(conversationId);
      } catch {
        refreshed = false;
      }
      setConversationNotice(conversationId, refreshed
        ? `Queued Turn #${turn.queue_ordinal} was cancelled. Its FIFO ordinal remains retired.`
        : `Queued Turn #${turn.queue_ordinal} was cancelled, but the remaining queue could not be refreshed yet.`);
      const focusCommitIsCurrent = restoreFocus
        && queueEditorIsCurrent(conversationId, editorGuard);
      if (focusCommitIsCurrent) {
        if (editorGuard.turnId === turn.id) setConversationEditor(conversationId, null);
        focusQueueTarget(conversationId, focusTurnId);
      }
    } catch (error) {
      setConversationNotice(conversationId, errorCode(error) === "conflict" ? "That queued Turn changed before cancellation. The canonical queue was refreshed." : "Mentat could not verify cancellation; the queue was left unchanged.");
      void refreshConversationDetail(conversationId).catch(() => undefined);
    } finally {
      setQueueBusyTurnIds((current) => { const next = new Set(current); next.delete(turn.id); return next; });
    }
  }

  async function continueQueuedTurn(turn: PublicQueuedConversationTurn) {
    if (!selectedConversationId || queueBusyTurnIds.has(turn.id)) return;
    const conversationId = selectedConversationId;
    const focusTurnId = queueFocusSuccessor(detail?.queued_turns ?? [], turn.id);
    const editorGuard = captureQueueEditor(conversationId);
    const restoreFocus = editorGuard.turnId === null || editorGuard.turnId === turn.id;
    setQueueBusyTurnIds((current) => new Set(current).add(turn.id));
    setConversationNotice(conversationId, `Revalidating queued Turn #${turn.queue_ordinal}…`);
    try {
      const submitted = await continueConversationTurn(conversationId, turn.id, turn.revision, turn.message_revision);
      setDetails((current) => current[conversationId] ? { ...current, [conversationId]: mergeTurnSubmission(current[conversationId], submitted) } : current);
      setConversations((current) => [submitted.conversation, ...current.filter((item) => item.id !== submitted.conversation.id)]);
      if (submitted.run && !submitted.duplicate) setVerifiedLiveRunIds((current) => new Set(current).add(submitted.run!.id));
      setConversationNotice(conversationId, submitted.disposition === "blocked"
        ? `Turn #${turn.queue_ordinal} remains blocked${submitted.turn.blocked_reason ? ` by ${readable(submitted.turn.blocked_reason)}` : ""}. No Run was started.`
        : submitted.disposition === "accepted"
          ? `Turn #${turn.queue_ordinal} started after exact revalidation.`
          : `Turn #${turn.queue_ordinal} was claimed, but the runtime result is ${readable(submitted.disposition)}. The queue remains paused.`);
      const focusCommitIsCurrent = restoreFocus
        && queueEditorIsCurrent(conversationId, editorGuard);
      if (focusCommitIsCurrent) {
        if (editorGuard.turnId === turn.id) setConversationEditor(conversationId, null);
        focusQueueTarget(conversationId, submitted.disposition === "blocked" ? turn.id : focusTurnId);
      }
      void refreshConversationDetail(conversationId).catch(() => undefined);
      void refreshActivityHints().catch(() => undefined);
    } catch (error) {
      setConversationNotice(conversationId, errorCode(error) === "conflict" ? "The blocked queue head changed. Nothing was started; the queue was refreshed." : "Mentat could not verify Continue. Nothing was retried automatically.");
      void refreshConversationDetail(conversationId).catch(() => undefined);
    } finally {
      setQueueBusyTurnIds((current) => { const next = new Set(current); next.delete(turn.id); return next; });
    }
  }

  return (
    <section aria-label="Agent Console Home" className="home-console">
      <div className="home-console-heading"><div><p className="console-kicker">Agent Console</p><h1>What can Mentat help with?</h1><p className="console-subtitle">Start a durable Conversation, then keep the work visible as it moves.</p></div><button className="console-primary-action" disabled={creating || conversationState === "unsupported" || selectedAgentId === null} onClick={() => void createNewConversation()} type="button">{creating ? "Creating…" : "New conversation"}</button></div>
      <div className="home-console-layout" data-right-collapsed={rightCollapsed ? "true" : "false"}>
        <section aria-label="Conversation workspace" className="conversation-workspace">
          <div className="conversation-tabs-heading"><div><p className="console-kicker">Conversations</p><h2>Workspace</h2></div><div className="conversation-heading-controls"><LinkPreviewSettings busy={linkPreviewBusy} onClear={() => void clearPreviewCache()} onToggle={() => void toggleLinkPreviewPreference()} preference={linkPreviewPreference} state={linkPreviewPreferenceState} /><label className="agent-picker"><span>Agent</span><select aria-label="Agent for new conversations" onChange={(event) => setSelectedAgentId(event.target.value || null)} value={selectedAgentId ?? ""}><option value="">{setupRequired ? "Direct Agent setup required" : "Choose an Agent"}</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label></div></div>
          <div aria-label="Conversation tabs" aria-orientation="horizontal" className="conversation-tabs" role="tablist">
            {openConversations.map((conversation, index) => (
              <div className="conversation-tab-group" key={conversation.id} role="presentation">
                <button
                  aria-controls="conversation-panel"
                  aria-selected={conversation.id === selectedConversationId}
                  className="conversation-tab"
                  data-conversation-tab-index={index}
                  id={`conversation-tab-${conversation.id}`}
                  onClick={() => selectConversation(conversation.id)}
                  onKeyDown={(event) => tabKeyDown(event, index, openConversations.length, (next) => selectConversation(openConversations[next].id))}
                  role="tab"
                  tabIndex={conversation.id === selectedConversationId ? 0 : -1}
                  title={conversationLabel(conversation)}
                  type="button"
                ><span>{conversationLabel(conversation)}</span></button>
                <button
                  aria-label={`Close ${conversationLabel(conversation)} tab`}
                  className="conversation-tab-close"
                  onClick={() => closeConversation(conversation.id)}
                  type="button"
                >×</button>
              </div>
            ))}
            {conversationState === "loading" ? <StatusMessage state="loading">Loading Conversations…</StatusMessage> : null}
            {conversationCursor ? <button className="load-more-conversations" disabled={loadingConversations} onClick={loadMoreConversations} type="button">{loadingConversations ? "Loading…" : "Load older"}</button> : null}
          </div>
          {conversations.length ? <details className="conversation-history"><summary id="recent-conversations-summary" tabIndex={-1}>Recent Conversations</summary><ul>{conversations.map((conversation) => <li key={conversation.id}><button className="history-open" onClick={() => selectConversation(conversation.id)} type="button"><span>{conversationLabel(conversation)}</span><small>{readable(conversation.state)} · {new Date(conversation.updated_at).toLocaleDateString()}</small></button><button aria-label={`${conversation.state === "archived" ? "Restore" : "Archive"} ${conversationLabel(conversation)}`} disabled={archiveBusyIds.has(conversation.id)} onClick={() => void setConversationArchived(conversation, conversation.state !== "archived")} type="button">{archiveBusyIds.has(conversation.id) ? "Updating…" : conversation.state === "archived" ? "Restore" : "Archive"}</button></li>)}</ul></details> : null}
          <Transcript detail={detail} detailState={displayedDetailState} draftSuggestion={setSelectedDraft} linkPreviewBusyMessages={linkPreviewBusyMessages} linkPreviews={linkPreviewStates} loadOlder={loadOlder} loadingOlder={loadingOlder} mediaRuns={selectedMedia} onRetryLinkPreviews={retryTrackedLinkPreviews} optimisticMessage={optimisticMessage} presentationEvents={selectedRunPresentationEvents} presentationRunId={selectedRunId} runActive={activeRun !== null} selectedAgentName={selectedAgent?.name ?? null} selectedConversationId={selectedConversationId} showLinkPreviewCards={linkPreviewPreferenceState === "ready" && linkPreviewPreference?.enabled === true} />
          {selectedConversationId && conversationMediaStates[selectedConversationId] === "error" ? <StatusMessage state="unavailable">Run files could not be refreshed. Stale file actions were removed.</StatusMessage> : null}
          {activeRun ? <><div aria-live="polite" className="selected-run-progress"><span className="activity-state-dot" aria-hidden="true" /><div><strong>Run {activeRunVerified ? readable(activeRun.status) : "Reconciling"}</strong><p>{liveProgress?.runId === activeRun.id ? liveProgress.summary : "Checking the exact runtime state before enabling controls…"}</p></div><div className="selected-run-actions">{activeRunVerified ? stopConfirmation?.runId === activeRun.id ? <><button disabled={runActionBusy} onClick={() => setStopConfirmation(null)} type="button">Keep running</button><button className="run-stop-confirm" disabled={runActionBusy} onClick={() => void submitStop()} type="button">{runActionBusy ? "Stopping…" : "Confirm Stop"}</button></> : selectedAgent?.capabilities.includes("run.stop") && activeRun.status !== "finalizing" ? <button className="run-stop" disabled={runActionBusy} onClick={() => void prepareStop()} type="button">Stop</button> : null : null}</div></div>{activeRunVerified && activeRunNeedsResponse && pendingActionState?.runId === activeRun.id && pendingActionState.state === "unavailable" ? <StatusMessage state="unavailable">The pending request could not be verified. Composer text will not answer it.</StatusMessage> : null}{activeRunVerified && pendingAction?.runId === activeRun.id ? <PendingActionCard busy={runActionBusy} clarificationText={clarificationText} confirmationPending={pendingResponse?.runId === activeRun.id} onCancelConfirmation={() => setPendingResponse(null)} onClarificationText={setClarificationText} onConfirm={() => void submitPendingResponse()} onPrepare={(response) => void preparePendingResponse(response)} request={pendingAction.request} /> : null}</> : null}
          {retryableRun ? <section aria-label="Run recovery" className="run-recovery-card"><div><p className="console-kicker">Run recovery</p><h3>Run {readable(retryableRun.status)}{retryableRun.partial ? " · verification partial" : ""}</h3><p>The prior Run and its events remain in history. Retry creates a separate execution attempt with the current Agent configuration.</p></div><div className="run-recovery-actions"><button disabled={retryBusyRunIds.has(retryableRun.id) || detail?.conversation.state !== "active"} onClick={() => void continueRun("retry")} type="button">{retryBusyRunIds.has(retryableRun.id) ? "Working…" : "Retry"}</button></div></section> : null}
          <QueuedTurns busyTurnIds={queueBusyTurnIds} editDrafts={queueEditDrafts} editingTurnId={editingTurnId} onBeginEdit={(turn) => { if (!selectedConversationId) return; setConversationEditor(selectedConversationId, turn.id); setQueueEditDrafts((current) => ({ ...current, [turn.id]: turn.text })); }} onCancel={(turn) => void cancelQueuedTurn(turn)} onContinue={(turn) => void continueQueuedTurn(turn)} onDiscardEdit={(turn) => { if (!selectedConversationId) return; const conversationId = selectedConversationId; if (editingTurnIdsRef.current[conversationId] !== turn.id) return; setConversationEditor(conversationId, null); focusQueueTarget(conversationId, turn.id); }} onEditDraft={(turnId, text) => setQueueEditDrafts((current) => ({ ...current, [turnId]: text }))} onSaveEdit={(turn) => void editQueuedTurn(turn)} turns={detail?.queued_turns ?? []} />
          {setupRequired || selectedNeedsCodexReadiness ? <div className="codex-setup" data-state={codexReadiness ?? "unchecked"}><div><strong>{codexReadiness === "ready" ? "Codex ready" : "Codex subscription sign-in"}</strong><p>{codexReadiness === "sign_in_required" ? <>Run <code>codex login</code> in a terminal, finish the browser sign-in, then Recheck.</> : codexReadiness === "cli_missing" ? <>Install the Codex CLI, run <code>codex login</code>, then restart Mentat.</> : codexReadiness === "unavailable" ? "Mentat could not confirm local Codex readiness." : codexReadiness === "ready" ? "The local Codex CLI is signed in. Mentat never receives your credentials." : "Mentat uses the Codex CLI's existing ChatGPT subscription sign-in; credentials stay with Codex."}</p></div><button disabled={checkingCodex} onClick={() => void recheckCodex()} type="button">{checkingCodex ? "Checking…" : codexReadiness === null ? "Check readiness" : "Recheck"}</button></div> : null}
          {selectedConversationId && detail ? <ConversationContextControls agent={selectedAgent} conversationId={selectedConversationId} disabledReason={contextDisabledReason} key={selectedConversationId} onAgentEnabled={(enabled) => { setAgents((current) => current.map((agent) => agent.id === enabled.id ? enabled : agent)); setDetails((current) => current[selectedConversationId] ? { ...current, [selectedConversationId]: { ...current[selectedConversationId], agent: enabled } } : current); }} onContext={(context) => setStagedContexts((current) => ({ ...current, [selectedConversationId]: context }))} onContextState={(state) => setStagedContextStates((current) => ({ ...current, [selectedConversationId]: state }))} onNotice={(message) => setConversationNotice(selectedConversationId, message)} onRefresh={() => void refreshConversationContext(selectedConversationId)} staged={stagedContext} stagingState={stagedContextState} /> : null}
          <form className="console-composer" onSubmit={(event) => { event.preventDefault(); void sendTurn(); }}><label htmlFor="console-prompt">Prompt</label><textarea disabled={initialWorkspaceLoading || sending} id="console-prompt" onChange={(event) => setSelectedDraft(event.target.value)} onCompositionEnd={() => { compositionActive.current = false; }} onCompositionStart={() => { compositionActive.current = true; }} onKeyDown={(event) => { const native = event.nativeEvent; const composing = compositionActive.current || native.isComposing || native.keyCode === 229; if (event.key === "Enter" && !event.shiftKey && !composing) { event.preventDefault(); void sendTurn(); } }} placeholder={initialWorkspaceLoading ? "Loading Conversations" : sending ? composerIntent.kind === "steer" ? "Steering this Run" : "Submitting this Turn" : activeRun ? "Write a follow-up to queue, or begin with /steer" : "Write a prompt for your Agent…"} rows={1} value={draft} /><div className="composer-footer"><ComposerConfiguration active={activeRun !== null} agentId={configurationAgentId} agentLocked={selectedConversationId !== null} agents={agents} busy={configurationBusy} configuration={agentConfiguration} loading={agentConfigurationState} model={configurationModel} onAgent={setSelectedAgentId} onConfirm={() => void applyAgentConfiguration()} onModel={(value) => { setConfigurationPreview(null); setConfigurationModel(value); }} onPreview={() => void prepareAgentConfiguration()} onProvider={chooseConfigurationProvider} preview={configurationPreview} provider={configurationProvider} snapshot={activeRun?.configuration ?? null} /><span className="composer-context">{selectedAgent ? `${selectedAgent.name} · ${selectedIsDirect ? "Direct mode" : "Selected Agent"}` : setupRequired ? "Direct Agent setup required" : "Select an Agent to continue"}</span><span className="composer-boundary">{sending ? composerIntent.kind === "steer" ? "Steering exact active Run…" : "Submitting exact Turn…" : hasStagedContext && !contextSendReady ? "Files send only from an idle Conversation" : hasStagedContext ? `${stagedContextCount} staged context item${stagedContextCount === 1 ? "" : "s"} · Send starts one exact Run` : composerIntent.kind === "steer" ? draftIsValid ? "Steering is never queued" : "Add guidance after /steer" : queueAtCapacity ? "Queue full · edit, cancel, or continue existing work" : activeRun ? `Run ${readable(activeRun.status)} · ordinary Send queues` : selectedNeedsCodexReadiness && codexReadiness !== "ready" && !(detail?.queued_turns.length) ? "Check Codex readiness before starting a Run" : "Enter to send · Shift+Enter for a new line"}</span><button aria-disabled={!canSend} className="composer-send" disabled={!canSend} type="submit">{sending ? "Sending…" : composerIntent.kind === "turn" && activeRun ? "Queue" : "Send"}</button></div></form>
          <p aria-atomic="true" aria-live="polite" className="console-notice" role="status">{visibleNotice}</p>
        </section>
        <ActivityRail activity={activity} activityState={activityState} collapsed={rightCollapsed} expandedAgents={expandedAgents} onSelectConversation={selectActivityConversation} onToggle={() => setRightCollapsed((current) => !current)} onToggleAgent={(agentId) => setExpandedAgents((current) => { const next = new Set(current); if (next.has(agentId)) next.delete(agentId); else next.add(agentId); return next; })} />
      </div>
      {conversationState === "unavailable" ? <StatusMessage state="unavailable">Conversation data is temporarily unavailable. Try refreshing the page.</StatusMessage> : null}
      {conversationState === "unsupported" ? <StatusMessage state="unsupported">The current Python bridge does not support Conversations yet.</StatusMessage> : null}
      {conversationState === "error" ? <StatusMessage state="error">Mentat could not safely load Conversations.</StatusMessage> : null}
    </section>
  );
}
