"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

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
} from "@/lib/bridge-conversations";
import {
  conversationComposerIntent,
  validConversationComposerText,
} from "@/lib/conversation-composer";
import {
  cancelConversationTurn,
  continueConversationTurn,
  createConversation,
  editConversationTurn,
  fetchActivity,
  fetchCodexReadiness,
  fetchConversation,
  fetchConversations,
  steerConversation,
  submitConversationTurn,
  PublicConversationError,
} from "@/lib/public-conversations";

const SUGGESTIONS = [
  "Help me plan the work I need to finish today",
  "Summarize what is currently waiting for my attention",
  "Turn a rough idea into a clear next step",
];

type LoadingState = "loading" | "ready" | "empty" | "unavailable" | "unsupported" | "error";
type OptimisticMessage = { conversationId: string; key: string; text: string };
type NoticeEntry = { message: string; sequence: number };
type QueueEditorGuard = { revision: number; turnId: string | null };
const UNBOUND_DRAFT_KEY = "new-conversation";
const MAX_TRANSCRIPT_MESSAGES = 200;

const ACTIVE_RUN_STATUSES = new Set([
  "reserved", "queued", "submitting", "starting", "running", "cancelling",
  "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown",
  "finalizing",
]);

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

function StatusMessage({ state, children }: Readonly<{ state: LoadingState; children: React.ReactNode }>) {
  return <p aria-live="polite" className={`console-status console-status-${state}`}>{children}</p>;
}

const Transcript = memo(function Transcript({
  detail,
  detailState,
  selectedAgentName,
  draftSuggestion,
  loadOlder,
  loadingOlder,
  optimisticMessage,
  selectedConversationId,
}: Readonly<{
  detail: PublicConversationDetail | null;
  detailState: LoadingState;
  selectedAgentName: string | null;
  draftSuggestion: (suggestion: string) => void;
  loadOlder: () => void;
  loadingOlder: boolean;
  optimisticMessage: OptimisticMessage | null;
  selectedConversationId: string | null;
}>) {
  const optimistic = optimisticMessage?.conversationId === selectedConversationId ? optimisticMessage : null;
  const isEmpty = detailState === "empty" || detailState === "ready" && detail?.messages.length === 0 && optimistic === null;
  return (
    <div className="conversation-transcript" id="conversation-panel" role="tabpanel" aria-labelledby={selectedConversationId ? `conversation-tab-${selectedConversationId}` : undefined} tabIndex={-1}>
      {detailState === "loading" ? <StatusMessage state="loading">Loading the selected Conversation…</StatusMessage> : null}
      {detailState === "unavailable" ? <StatusMessage state="unavailable">Conversation data is temporarily unavailable.</StatusMessage> : null}
      {detailState === "error" ? <StatusMessage state="error">Mentat could not safely read this Conversation.</StatusMessage> : null}
      {isEmpty ? <div className="conversation-empty-state"><span className="empty-state-mark" aria-hidden="true">✦</span><h2>{detail?.conversation.title ?? "A clear place to begin"}</h2><p>Choose a suggestion or write a prompt below. Mentat will keep the accepted Turn and its Run visible here.</p><div className="suggestion-list">{SUGGESTIONS.map((suggestion) => <button key={suggestion} onClick={() => draftSuggestion(suggestion)} type="button">{suggestion}</button>)}</div></div> : null}
      {detailState === "ready" && detail && (detail.messages.length > 0 || optimistic) ? <>{detail.next_message_cursor ? <button className="load-older" disabled={loadingOlder} onClick={loadOlder} type="button">{loadingOlder ? "Loading older messages…" : "Load older messages"}</button> : null}<ol className="message-list">{detail.messages.slice(-200).map((message) => <li className={`message-row message-${message.role}${message.state === "cancelled" ? " message-cancelled" : ""}`} key={message.id}><span className="message-role">{message.role === "user" ? `You${message.state === "cancelled" ? " · Cancelled" : ""}` : selectedAgentName ?? "Agent"}</span><p>{message.content.parts[0].text}</p></li>)}{optimistic ? <li aria-label="Sending message" className="message-row message-user message-optimistic"><span className="message-role">You · Sending…</span><p>{optimistic.text}</p></li> : null}</ol></> : null}
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

export function HomeConsole() {
  const [conversations, setConversations] = useState<PublicConversation[]>([]);
  const [conversationCursor, setConversationCursor] = useState<string | null>(null);
  const [agents, setAgents] = useState<PublicConversationAgent[]>([]);
  const [directAgentId, setDirectAgentId] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
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
  const [codexReadiness, setCodexReadiness] = useState<PublicCodexReadiness["state"] | null>(null);
  const [checkingCodex, setCheckingCodex] = useState(false);
  const [notice, setNoticeState] = useState<NoticeEntry>({ message: "", sequence: 0 });
  const [conversationNotices, setConversationNotices] = useState<Record<string, NoticeEntry>>({});
  const [creating, setCreating] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const noticeSequence = useRef(0);
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
  const setupRequired = directAgentId === null;
  const selectedIsDirect = selectedAgent?.id === directAgentId && directAgentId !== null;
  const selectedNeedsCodexReadiness = selectedAgent?.runtime_type === "codex";
  const activeRun = detail?.current_run && ACTIVE_RUN_STATUSES.has(detail.current_run.status)
    ? detail.current_run
    : null;
  const activeRunId = activeRun?.id ?? null;
  const initialWorkspaceLoading = selectedConversationId === null && conversationState === "loading";
  const composerIntent = conversationComposerIntent(draft);
  const draftIsValid = validConversationComposerText(composerIntent.text);
  const queueAtCapacity = (detail?.queued_turns.length ?? 0) >= 8;
  const codexSendReady = !selectedNeedsCodexReadiness
    || codexReadiness === "ready"
    || activeRun !== null
    || (detail?.queued_turns.length ?? 0) > 0;
  const canSend = !!selectedConversationId
    && detail?.conversation.state === "active"
    && draftIsValid
    && !sending
    && (composerIntent.kind === "steer" || !queueAtCapacity && codexSendReady);
  const loadedConversationIds = useMemo(() => new Set(conversations.map((item) => item.id)), [conversations]);
  const mounted = useRef(true);
  const compositionActive = useRef(false);
  const retryByConversationRef = useRef(new Map<string, OptimisticMessage>());
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

  const setSelectedDraft = useCallback((value: string) => {
    setDrafts((current) => current[draftKey] === value
      ? current
      : { ...current, [draftKey]: value });
  }, [draftKey]);

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
        setSelectedConversationId((current) => current && payload.conversations.some((item) => item.id === current) ? current : payload.conversations[0]?.id ?? null);
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
    const receive = (event: Event) => {
      if (closed) return;
      const data = (event as MessageEvent<string>).data;
      if (typeof data !== "string") return;
      const summary = liveSummary(data, runId);
      if (summary) setLiveProgress({ runId, summary });
      void refreshConversationDetail(conversationId).catch(() => {
        if (!closed) setLiveProgress({ runId, summary: "Live updates are reconnecting…" });
      });
    };
    source.addEventListener("snapshot", receive);
    source.addEventListener("reset", receive);
    source.addEventListener("timeline", receive);
    source.onerror = () => {
      if (!closed) setLiveProgress({ runId, summary: "Live updates are reconnecting…" });
    };
    return () => { closed = true; source.close(); };
  }, [activeRunId, refreshConversationDetail, selectedConversationId]);

  const hasActiveActivity = activity?.activity.some((item) => item.conversations.some(
    (conversation) => ACTIVE_RUN_STATUSES.has(conversation.run_status),
  )) ?? false;
  useEffect(() => {
    if (!hasActiveActivity) return;
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
  }, [hasActiveActivity, refreshActivityHints]);

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
    setDetailState(details[conversationId] ? "ready" : "loading");
    setSelectedConversationId(conversationId);
  }, [details]);

  const selectActivityConversation = useCallback((conversationId: string) => {
    setNotice("");
    if (loadedConversationIds.has(conversationId)) { selectConversation(conversationId); return; }
    void refreshConversationDetail(conversationId).then(() => { if (mounted.current) { setDetailState("ready"); setSelectedConversationId(conversationId); } }).catch(() => setNotice("Mentat could not reopen that Conversation safely."));
  }, [loadedConversationIds, refreshConversationDetail, selectConversation]);

  async function createNewConversation() {
    if (creating || !selectedAgentId) return;
    setCreating(true); setNotice("Creating a new Conversation…");
    try { const created = await createConversation(selectedAgentId); setDetails((current) => ({ ...current, [created.conversation.id]: created })); setDrafts((current) => { const next = { ...current }; const carriedDraft = next[UNBOUND_DRAFT_KEY] ?? ""; delete next[UNBOUND_DRAFT_KEY]; if (carriedDraft) next[created.conversation.id] = carriedDraft; return next; }); setDetailState("ready"); setSelectedConversationId(created.conversation.id); setConversations((current) => [created.conversation, ...current.filter((item) => item.id !== created.conversation.id)]); setConversationState("ready"); setNotice("Conversation created and ready for a prompt."); } catch { setNotice("Mentat could not create that Conversation. Try again."); } finally { setCreating(false); }
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
      setDrafts((current) => current[conversationId] === draftAtSend
        ? { ...current, [conversationId]: "" }
        : current);
      retryByConversationRef.current.delete(conversationId);
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
          <div className="conversation-tabs-heading"><div><p className="console-kicker">Conversations</p><h2>Workspace</h2></div><label className="agent-picker"><span>Agent</span><select aria-label="Agent for new conversations" onChange={(event) => setSelectedAgentId(event.target.value || null)} value={selectedAgentId ?? ""}><option value="">{setupRequired ? "Direct Agent setup required" : "Choose an Agent"}</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label></div>
          <div aria-label="Conversation tabs" aria-orientation="horizontal" className="conversation-tabs" role="tablist">{conversations.map((conversation, index) => <button aria-controls="conversation-panel" aria-selected={conversation.id === selectedConversationId} className="conversation-tab" data-conversation-tab-index={index} id={`conversation-tab-${conversation.id}`} key={conversation.id} onClick={() => selectConversation(conversation.id)} onKeyDown={(event) => tabKeyDown(event, index, conversations.length, (next) => selectConversation(conversations[next].id))} role="tab" tabIndex={conversation.id === selectedConversationId ? 0 : -1} type="button"><span>{conversationLabel(conversation)}</span><small>{readable(conversation.state)}</small></button>)}{conversationState === "loading" ? <StatusMessage state="loading">Loading Conversations…</StatusMessage> : null}{conversationCursor ? <button className="load-more-conversations" disabled={loadingConversations} onClick={loadMoreConversations} type="button">{loadingConversations ? "Loading…" : "Load older"}</button> : null}</div>
          <Transcript detail={detail} detailState={displayedDetailState} draftSuggestion={setSelectedDraft} loadOlder={loadOlder} loadingOlder={loadingOlder} optimisticMessage={optimisticMessage} selectedAgentName={selectedAgent?.name ?? null} selectedConversationId={selectedConversationId} />
          {activeRun ? <div aria-live="polite" className="selected-run-progress"><span className="activity-state-dot" aria-hidden="true" /><div><strong>Run {readable(activeRun.status)}</strong><p>{liveProgress?.runId === activeRun.id ? liveProgress.summary : "Waiting for the next verified Run update…"}</p></div></div> : null}
          <QueuedTurns busyTurnIds={queueBusyTurnIds} editDrafts={queueEditDrafts} editingTurnId={editingTurnId} onBeginEdit={(turn) => { if (!selectedConversationId) return; setConversationEditor(selectedConversationId, turn.id); setQueueEditDrafts((current) => ({ ...current, [turn.id]: turn.text })); }} onCancel={(turn) => void cancelQueuedTurn(turn)} onContinue={(turn) => void continueQueuedTurn(turn)} onDiscardEdit={(turn) => { if (!selectedConversationId) return; const conversationId = selectedConversationId; if (editingTurnIdsRef.current[conversationId] !== turn.id) return; setConversationEditor(conversationId, null); focusQueueTarget(conversationId, turn.id); }} onEditDraft={(turnId, text) => setQueueEditDrafts((current) => ({ ...current, [turnId]: text }))} onSaveEdit={(turn) => void editQueuedTurn(turn)} turns={detail?.queued_turns ?? []} />
          {setupRequired || selectedNeedsCodexReadiness ? <div className="codex-setup" data-state={codexReadiness ?? "unchecked"}><div><strong>{codexReadiness === "ready" ? "Codex ready" : "Codex subscription sign-in"}</strong><p>{codexReadiness === "sign_in_required" ? <>Run <code>codex login</code> in a terminal, finish the browser sign-in, then Recheck.</> : codexReadiness === "cli_missing" ? <>Install the Codex CLI, run <code>codex login</code>, then restart Mentat.</> : codexReadiness === "unavailable" ? "Mentat could not confirm local Codex readiness." : codexReadiness === "ready" ? "The local Codex CLI is signed in. Mentat never receives your credentials." : "Mentat uses the Codex CLI's existing ChatGPT subscription sign-in; credentials stay with Codex."}</p></div><button disabled={checkingCodex} onClick={() => void recheckCodex()} type="button">{checkingCodex ? "Checking…" : codexReadiness === null ? "Check readiness" : "Recheck"}</button></div> : null}
          <form className="console-composer" onSubmit={(event) => { event.preventDefault(); void sendTurn(); }}><label htmlFor="console-prompt">Prompt</label><textarea disabled={initialWorkspaceLoading || sending} id="console-prompt" onChange={(event) => setSelectedDraft(event.target.value)} onCompositionEnd={() => { compositionActive.current = false; }} onCompositionStart={() => { compositionActive.current = true; }} onKeyDown={(event) => { const native = event.nativeEvent; const composing = compositionActive.current || native.isComposing || native.keyCode === 229; if (event.key === "Enter" && !event.shiftKey && !composing) { event.preventDefault(); void sendTurn(); } }} placeholder={initialWorkspaceLoading ? "Loading Conversations" : sending ? composerIntent.kind === "steer" ? "Steering this Run" : "Submitting this Turn" : activeRun ? "Write a follow-up to queue, or begin with /steer" : "Write a prompt for your Agent…"} rows={1} value={draft} /><div className="composer-footer"><span className="composer-context">{selectedAgent ? `${selectedAgent.name} · ${selectedIsDirect ? "Direct mode" : "Selected Agent"}` : setupRequired ? "Direct Agent setup required" : "Select an Agent to continue"}</span><span className="composer-boundary">{sending ? composerIntent.kind === "steer" ? "Steering exact active Run…" : "Submitting exact Turn…" : composerIntent.kind === "steer" ? draftIsValid ? "Steering is never queued" : "Add guidance after /steer" : queueAtCapacity ? "Queue full · edit, cancel, or continue existing work" : activeRun ? `Run ${readable(activeRun.status)} · ordinary Send queues` : selectedNeedsCodexReadiness && codexReadiness !== "ready" && !(detail?.queued_turns.length) ? "Check Codex readiness before starting a Run" : "Enter to send · Shift+Enter for a new line"}</span><button aria-disabled={!canSend} className="composer-send" disabled={!canSend} type="submit">{sending ? "Sending…" : composerIntent.kind === "turn" && activeRun ? "Queue" : "Send"}</button></div></form>
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
