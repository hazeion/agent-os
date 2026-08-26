"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  PublicActivityPayload,
  PublicConversation,
  PublicConversationAgent,
  PublicConversationDetail,
} from "@/lib/bridge-conversations";
import {
  createConversation,
  fetchActivity,
  fetchConversation,
  fetchConversations,
  type PublicConversationError,
} from "@/lib/public-conversations";

const SUGGESTIONS = [
  "Help me plan the work I need to finish today",
  "Summarize what is currently waiting for my attention",
  "Turn a rough idea into a clear next step",
];

type LoadingState = "loading" | "ready" | "empty" | "unavailable" | "unsupported" | "error";

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
  selectedConversationId,
}: Readonly<{
  detail: PublicConversationDetail | null;
  detailState: LoadingState;
  selectedAgentName: string | null;
  draftSuggestion: (suggestion: string) => void;
  loadOlder: () => void;
  loadingOlder: boolean;
  selectedConversationId: string | null;
}>) {
  const isEmpty = detailState === "empty" || detailState === "ready" && detail?.messages.length === 0;
  return (
    <div className="conversation-transcript" id="conversation-panel" role="tabpanel" aria-labelledby={selectedConversationId ? `conversation-tab-${selectedConversationId}` : undefined} tabIndex={-1}>
      {detailState === "loading" ? <StatusMessage state="loading">Loading the selected Conversation…</StatusMessage> : null}
      {detailState === "unavailable" ? <StatusMessage state="unavailable">Conversation data is temporarily unavailable.</StatusMessage> : null}
      {detailState === "error" ? <StatusMessage state="error">Mentat could not safely read this Conversation.</StatusMessage> : null}
      {isEmpty ? <div className="conversation-empty-state"><span className="empty-state-mark" aria-hidden="true">✦</span><h2>{detail?.conversation.title ?? "A clear place to begin"}</h2><p>Choose a suggestion or write a prompt below. Sending remains unavailable until the next Console slice.</p><div className="suggestion-list">{SUGGESTIONS.map((suggestion) => <button key={suggestion} onClick={() => draftSuggestion(suggestion)} type="button">{suggestion}</button>)}</div></div> : null}
      {detailState === "ready" && detail?.messages.length ? <>{detail.next_message_cursor ? <button className="load-older" disabled={loadingOlder} onClick={loadOlder} type="button">{loadingOlder ? "Loading older messages…" : "Load older messages"}</button> : null}<ol className="message-list">{detail.messages.slice(-200).map((message) => <li className={`message-row message-${message.role}`} key={message.id}><span className="message-role">{message.role === "user" ? "You" : selectedAgentName ?? "Agent"}</span><p>{message.content.parts[0].text}</p></li>)}</ol></> : null}
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
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const detail = selectedConversationId ? details[selectedConversationId] ?? null : null;
  const selectedAgent = detail?.agent ?? agents.find((agent) => agent.id === selectedAgentId) ?? null;
  const setupRequired = directAgentId === null;
  const selectedIsDirect = selectedAgent?.id === directAgentId && directAgentId !== null;
  const loadedConversationIds = useMemo(() => new Set(conversations.map((item) => item.id)), [conversations]);
  const mounted = useRef(true);
  const displayedDetailState = selectedConversationId === null
    ? conversationState === "empty" ? "empty" : conversationState
    : detail?.conversation.id === selectedConversationId ? detailState : "loading";

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

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
    void fetchConversation(selectedConversationId).then((value) => { if (!cancelled) { setDetails((current) => ({ ...current, [value.conversation.id]: value })); setDetailState("ready"); } }).catch((error: unknown) => { if (!cancelled) setDetailState(statusFrom(error)); });
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
    setCreating(true); setNotice("");
    try { const created = await createConversation(selectedAgentId); setDetails((current) => ({ ...current, [created.conversation.id]: created })); setDetailState("ready"); setSelectedConversationId(created.conversation.id); setConversations((current) => [created.conversation, ...current.filter((item) => item.id !== created.conversation.id)]); setConversationState("ready"); setNotice("Conversation created and ready for a prompt."); } catch { setNotice("Mentat could not create that Conversation. Try again."); } finally { setCreating(false); }
  }

  return (
    <section aria-label="Agent Console Home" className="home-console">
      <div className="home-console-heading"><div><p className="console-kicker">Agent Console</p><h1>What can Mentat help with?</h1><p className="console-subtitle">Start a durable Conversation, then keep the work visible as it moves.</p></div><button className="console-primary-action" disabled={creating || conversationState === "unsupported" || selectedAgentId === null} onClick={() => void createNewConversation()} type="button">{creating ? "Creating…" : "New conversation"}</button></div>
      <div className="home-console-layout" data-right-collapsed={rightCollapsed ? "true" : "false"}>
        <section aria-label="Conversation workspace" className="conversation-workspace">
          <div className="conversation-tabs-heading"><div><p className="console-kicker">Conversations</p><h2>Workspace</h2></div><label className="agent-picker"><span>Agent</span><select aria-label="Agent for new conversations" onChange={(event) => setSelectedAgentId(event.target.value || null)} value={selectedAgentId ?? ""}><option value="">{setupRequired ? "Direct Agent setup required" : "Choose an Agent"}</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label></div>
          <div aria-label="Conversation tabs" aria-orientation="horizontal" className="conversation-tabs" role="tablist">{conversations.map((conversation, index) => <button aria-controls="conversation-panel" aria-selected={conversation.id === selectedConversationId} className="conversation-tab" data-conversation-tab-index={index} id={`conversation-tab-${conversation.id}`} key={conversation.id} onClick={() => selectConversation(conversation.id)} onKeyDown={(event) => tabKeyDown(event, index, conversations.length, (next) => selectConversation(conversations[next].id))} role="tab" tabIndex={conversation.id === selectedConversationId ? 0 : -1} type="button"><span>{conversationLabel(conversation)}</span><small>{readable(conversation.state)}</small></button>)}{conversationState === "loading" ? <StatusMessage state="loading">Loading Conversations…</StatusMessage> : null}{conversationCursor ? <button className="load-more-conversations" disabled={loadingConversations} onClick={loadMoreConversations} type="button">{loadingConversations ? "Loading…" : "Load older"}</button> : null}</div>
          <Transcript detail={detail} detailState={displayedDetailState} draftSuggestion={setDraft} loadOlder={loadOlder} loadingOlder={loadingOlder} selectedAgentName={selectedAgent?.name ?? null} selectedConversationId={selectedConversationId} />
          <form className="console-composer" onSubmit={(event) => event.preventDefault()}><label htmlFor="console-prompt">Prompt</label><textarea id="console-prompt" onChange={(event) => setDraft(event.target.value)} placeholder="Write a prompt for your Agent…" rows={1} value={draft} /><div className="composer-footer"><span className="composer-context">{selectedAgent ? `${selectedAgent.name} · ${selectedIsDirect ? "Direct mode" : "Selected Agent"}` : setupRequired ? "Direct Agent setup required" : "Select an Agent to continue"}</span><span className="composer-boundary">Dispatch available in Slice 2</span><button aria-disabled="true" className="composer-send" disabled type="submit">Send</button></div></form>
          {notice ? <p aria-live="polite" className="console-notice">{notice}</p> : null}
        </section>
        <ActivityRail activity={activity} activityState={activityState} collapsed={rightCollapsed} expandedAgents={expandedAgents} onSelectConversation={selectActivityConversation} onToggle={() => setRightCollapsed((current) => !current)} onToggleAgent={(agentId) => setExpandedAgents((current) => { const next = new Set(current); if (next.has(agentId)) next.delete(agentId); else next.add(agentId); return next; })} />
      </div>
      {conversationState === "unavailable" ? <StatusMessage state="unavailable">Conversation data is temporarily unavailable. Try refreshing the page.</StatusMessage> : null}
      {conversationState === "unsupported" ? <StatusMessage state="unsupported">The current Python bridge does not support Conversations yet.</StatusMessage> : null}
      {conversationState === "error" ? <StatusMessage state="error">Mentat could not safely load Conversations.</StatusMessage> : null}
    </section>
  );
}
