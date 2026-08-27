"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  PublicActivityPayload,
  PublicConversation,
  PublicConversationAgent,
  PublicConversationDetail,
  PublicCodexReadiness,
} from "@/lib/bridge-conversations";
import {
  createConversation,
  fetchActivity,
  fetchCodexReadiness,
  fetchConversation,
  fetchConversations,
  submitConversationTurn,
  type PublicConversationError,
} from "@/lib/public-conversations";

const SUGGESTIONS = [
  "Help me plan the work I need to finish today",
  "Summarize what is currently waiting for my attention",
  "Turn a rough idea into a clear next step",
];

type LoadingState = "loading" | "ready" | "empty" | "unavailable" | "unsupported" | "error";
type OptimisticMessage = { conversationId: string; key: string; text: string };
type NoticeEntry = { message: string; sequence: number };
const UNBOUND_DRAFT_KEY = "new-conversation";

const ACTIVE_RUN_STATUSES = new Set([
  "reserved", "queued", "submitting", "starting", "running", "cancelling",
  "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown",
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
      {detailState === "ready" && detail && (detail.messages.length > 0 || optimistic) ? <>{detail.next_message_cursor ? <button className="load-older" disabled={loadingOlder} onClick={loadOlder} type="button">{loadingOlder ? "Loading older messages…" : "Load older messages"}</button> : null}<ol className="message-list">{detail.messages.slice(-200).map((message) => <li className={`message-row message-${message.role}`} key={message.id}><span className="message-role">{message.role === "user" ? "You" : selectedAgentName ?? "Agent"}</span><p>{message.content.parts[0].text}</p></li>)}{optimistic ? <li aria-label="Sending message" className="message-row message-user message-optimistic"><span className="message-role">You · Sending…</span><p>{optimistic.text}</p></li> : null}</ol></> : null}
    </div>
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
  const [admissionBlockedConversationIds, setAdmissionBlockedConversationIds] = useState<ReadonlySet<string>>(new Set());
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
  const codexSendReady = !selectedNeedsCodexReadiness || codexReadiness === "ready";
  const activeRun = detail?.current_run && ACTIVE_RUN_STATUSES.has(detail.current_run.status)
    ? detail.current_run
    : null;
  const admissionBlocked = selectedConversationId !== null
    && admissionBlockedConversationIds.has(selectedConversationId);
  const initialWorkspaceLoading = selectedConversationId === null && conversationState === "loading";
  const draftIsValid = !!draft.trim() && draft.trim() === draft && Array.from(draft).length <= 6_000 && !draft.includes("\0");
  const canSend = !!selectedConversationId && detail?.conversation.state === "active" && draftIsValid && !sending && !admissionBlocked && activeRun === null && codexSendReady;
  const loadedConversationIds = useMemo(() => new Set(conversations.map((item) => item.id)), [conversations]);
  const mounted = useRef(true);
  const compositionActive = useRef(false);
  const retryByConversationRef = useRef(new Map<string, OptimisticMessage>());
  const displayedDetailState = selectedConversationId === null
    ? conversationState === "empty" ? "empty" : conversationState
    : detail?.conversation.id === selectedConversationId ? detailState : "loading";

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const setSelectedDraft = useCallback((value: string) => {
    setDrafts((current) => current[draftKey] === value
      ? current
      : { ...current, [draftKey]: value });
  }, [draftKey]);

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
    void fetchConversation(selectedConversationId).then((value) => { if (!cancelled) { setDetails((current) => ({ ...current, [value.conversation.id]: value })); if (!value.current_run || !ACTIVE_RUN_STATUSES.has(value.current_run.status)) setAdmissionBlockedConversationIds((current) => { if (!current.has(value.conversation.id)) return current; const next = new Set(current); next.delete(value.conversation.id); return next; }); setDetailState("ready"); } }).catch((error: unknown) => { if (!cancelled) setDetailState(statusFrom(error)); });
    return () => { cancelled = true; };
  }, [selectedConversationId]);

  const loadMoreConversations = useCallback(() => {
    if (!conversationCursor || loadingConversations) return;
    setLoadingConversations(true);
    void fetchConversations(conversationCursor).then((payload) => { if (mounted.current) { setConversations((current) => [...current, ...payload.conversations.filter((item) => !current.some((existing) => existing.id === item.id))]); setConversationCursor(payload.next_cursor); } }).catch((error: unknown) => setNotice(`Could not load older Conversations (${statusFrom(error)}).`)).finally(() => setLoadingConversations(false));
  }, [conversationCursor, loadingConversations]);

  const loadOlder = useCallback(() => {
    if (!detail?.next_message_cursor || loadingOlder || !selectedConversationId) return;
    setLoadingOlder(true);
    void fetchConversation(selectedConversationId, detail.next_message_cursor).then((older) => { if (mounted.current) setDetails((current) => { const existing = current[selectedConversationId]; if (!existing) return { ...current, [selectedConversationId]: older }; const messages = [...older.messages, ...existing.messages].filter((message, index, all) => all.findIndex((candidate) => candidate.id === message.id) === index).sort((left, right) => left.sequence - right.sequence).slice(0, 200); return { ...current, [selectedConversationId]: { ...existing, messages, next_message_cursor: older.next_message_cursor } }; }); }).catch((error: unknown) => setNotice(`Could not load older messages (${statusFrom(error)}).`)).finally(() => setLoadingOlder(false));
  }, [detail, loadingOlder, selectedConversationId]);

  const selectConversation = useCallback((conversationId: string) => {
    setDetailState(details[conversationId] ? "ready" : "loading");
    setSelectedConversationId(conversationId);
  }, [details]);

  const selectActivityConversation = useCallback((conversationId: string) => {
    setNotice("");
    if (loadedConversationIds.has(conversationId)) { selectConversation(conversationId); return; }
    void fetchConversation(conversationId).then((value) => { if (mounted.current) { setConversations((current) => [value.conversation, ...current.filter((item) => item.id !== conversationId)]); setDetails((current) => ({ ...current, [value.conversation.id]: value })); setDetailState("ready"); setSelectedConversationId(conversationId); } }).catch(() => setNotice("Mentat could not reopen that Conversation safely."));
  }, [loadedConversationIds, selectConversation]);

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
    if (!canSend || !selectedConversationId) return;
    const conversationId = selectedConversationId;
    const text = draft;
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
      setAdmissionBlockedConversationIds((current) => { if (!current.has(conversationId)) return current; const next = new Set(current); next.delete(conversationId); return next; });
      setDetails((current) => {
        const existing = current[conversationId];
        if (!existing) return current;
        const messages = [...existing.messages.filter((message) => message.id !== submitted.message.id), submitted.message]
          .sort((left, right) => left.sequence - right.sequence)
          .slice(-200);
        return { ...current, [conversationId]: { ...existing, conversation: submitted.conversation, messages, current_run: submitted.run } };
      });
      setConversations((current) => [submitted.conversation, ...current.filter((item) => item.id !== submitted.conversation.id)]);
      if (submitted.disposition === "accepted") {
        setDrafts((current) => current[conversationId] === text
          ? { ...current, [conversationId]: "" }
          : current);
        retryByConversationRef.current.delete(conversationId);
        setConversationNotice(conversationId, submitted.duplicate ? "This Turn was already accepted; no duplicate Run was started." : "Turn accepted. The Run is now visible in this Conversation.");
      } else if (submitted.disposition === "rejected") {
        retryByConversationRef.current.delete(conversationId);
        setConversationNotice(conversationId, "The Turn is saved, but the runtime rejected this Run.");
      } else if (submitted.disposition === "unknown") {
        setConversationNotice(conversationId, "The Turn is saved, but runtime acceptance is unknown. Mentat will not retry it automatically.");
      } else {
        setConversationNotice(conversationId, "The exact Turn is already being submitted.");
      }
    } catch (error) {
      setOptimisticMessages((current) => { const next = { ...current }; delete next[conversationId]; return next; });
      setDrafts((current) => ({ ...current, [conversationId]: text }));
      const code = error && typeof error === "object" && "code" in error ? String((error as PublicConversationError).code) : "";
      if (code === "sign_in_required" || code === "cli_missing") {
        setCodexReadiness(code);
        setConversationNotice(conversationId, code === "sign_in_required" ? "Codex sign-in is required. Run codex login, then Recheck." : "The Codex CLI is not available yet.");
      } else if (code === "active_run") {
        setAdmissionBlockedConversationIds((current) => new Set(current).add(conversationId));
        setConversationNotice(conversationId, "This Conversation already has an active Run. The draft was kept.");
        try {
          const refreshed = await fetchConversation(conversationId);
          if (mounted.current) {
            setDetails((current) => ({ ...current, [conversationId]: refreshed }));
            if (!refreshed.current_run || !ACTIVE_RUN_STATUSES.has(refreshed.current_run.status)) setAdmissionBlockedConversationIds((current) => { const next = new Set(current); next.delete(conversationId); return next; });
          }
        } catch {
          // Keep the local admission block until a canonical refresh succeeds.
        }
      }
      else if (code === "capacity_unavailable") setConversationNotice(conversationId, "Runtime capacity is unavailable. The draft was kept.");
      else if (code === "idempotency_conflict") { retryByConversationRef.current.delete(conversationId); setConversationNotice(conversationId, "This Send key no longer matches the draft. Please send again."); }
      else setConversationNotice(conversationId, "Mentat could not confirm admission. The draft and exact retry key were kept; Send again to retry safely.");
    } finally { setSendingConversationIds((current) => { const next = new Set(current); next.delete(conversationId); return next; }); }
  }

  return (
    <section aria-label="Agent Console Home" className="home-console">
      <div className="home-console-heading"><div><p className="console-kicker">Agent Console</p><h1>What can Mentat help with?</h1><p className="console-subtitle">Start a durable Conversation, then keep the work visible as it moves.</p></div><button className="console-primary-action" disabled={creating || conversationState === "unsupported" || selectedAgentId === null} onClick={() => void createNewConversation()} type="button">{creating ? "Creating…" : "New conversation"}</button></div>
      <div className="home-console-layout" data-right-collapsed={rightCollapsed ? "true" : "false"}>
        <section aria-label="Conversation workspace" className="conversation-workspace">
          <div className="conversation-tabs-heading"><div><p className="console-kicker">Conversations</p><h2>Workspace</h2></div><label className="agent-picker"><span>Agent</span><select aria-label="Agent for new conversations" onChange={(event) => setSelectedAgentId(event.target.value || null)} value={selectedAgentId ?? ""}><option value="">{setupRequired ? "Direct Agent setup required" : "Choose an Agent"}</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label></div>
          <div aria-label="Conversation tabs" aria-orientation="horizontal" className="conversation-tabs" role="tablist">{conversations.map((conversation, index) => <button aria-controls="conversation-panel" aria-selected={conversation.id === selectedConversationId} className="conversation-tab" data-conversation-tab-index={index} id={`conversation-tab-${conversation.id}`} key={conversation.id} onClick={() => selectConversation(conversation.id)} onKeyDown={(event) => tabKeyDown(event, index, conversations.length, (next) => selectConversation(conversations[next].id))} role="tab" tabIndex={conversation.id === selectedConversationId ? 0 : -1} type="button"><span>{conversationLabel(conversation)}</span><small>{readable(conversation.state)}</small></button>)}{conversationState === "loading" ? <StatusMessage state="loading">Loading Conversations…</StatusMessage> : null}{conversationCursor ? <button className="load-more-conversations" disabled={loadingConversations} onClick={loadMoreConversations} type="button">{loadingConversations ? "Loading…" : "Load older"}</button> : null}</div>
          <Transcript detail={detail} detailState={displayedDetailState} draftSuggestion={setSelectedDraft} loadOlder={loadOlder} loadingOlder={loadingOlder} optimisticMessage={optimisticMessage} selectedAgentName={selectedAgent?.name ?? null} selectedConversationId={selectedConversationId} />
          {setupRequired || selectedNeedsCodexReadiness ? <div className="codex-setup" data-state={codexReadiness ?? "unchecked"}><div><strong>{codexReadiness === "ready" ? "Codex ready" : "Codex subscription sign-in"}</strong><p>{codexReadiness === "sign_in_required" ? <>Run <code>codex login</code> in a terminal, finish the browser sign-in, then Recheck.</> : codexReadiness === "cli_missing" ? <>Install the Codex CLI, run <code>codex login</code>, then restart Mentat.</> : codexReadiness === "unavailable" ? "Mentat could not confirm local Codex readiness." : codexReadiness === "ready" ? "The local Codex CLI is signed in. Mentat never receives your credentials." : "Mentat uses the Codex CLI's existing ChatGPT subscription sign-in; credentials stay with Codex."}</p></div><button disabled={checkingCodex} onClick={() => void recheckCodex()} type="button">{checkingCodex ? "Checking…" : codexReadiness === null ? "Check readiness" : "Recheck"}</button></div> : null}
          <form className="console-composer" onSubmit={(event) => { event.preventDefault(); void sendTurn(); }}><label htmlFor="console-prompt">Prompt</label><textarea disabled={initialWorkspaceLoading || sending || admissionBlocked || activeRun !== null} id="console-prompt" onChange={(event) => setSelectedDraft(event.target.value)} onCompositionEnd={() => { compositionActive.current = false; }} onCompositionStart={() => { compositionActive.current = true; }} onKeyDown={(event) => { const native = event.nativeEvent; const composing = compositionActive.current || native.isComposing || native.keyCode === 229; if (event.key === "Enter" && !event.shiftKey && !composing) { event.preventDefault(); void sendTurn(); } }} placeholder={initialWorkspaceLoading ? "Loading Conversations" : sending ? "Submitting this Turn" : admissionBlocked || activeRun ? "This Conversation has an active Run" : "Write a prompt for your Agent…"} rows={1} value={draft} /><div className="composer-footer"><span className="composer-context">{selectedAgent ? `${selectedAgent.name} · ${selectedIsDirect ? "Direct mode" : "Selected Agent"}` : setupRequired ? "Direct Agent setup required" : "Select an Agent to continue"}</span><span className="composer-boundary">{sending ? "Submitting exact Turn…" : admissionBlocked ? "Refreshing the active Run" : activeRun ? `Run ${readable(activeRun.status)}` : selectedNeedsCodexReadiness && codexReadiness !== "ready" ? "Check Codex readiness before sending" : "Enter to send · Shift+Enter for a new line"}</span><button aria-disabled={!canSend} className="composer-send" disabled={!canSend} type="submit">{sending ? "Sending…" : "Send"}</button></div></form>
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
