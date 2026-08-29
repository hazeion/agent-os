"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";

import type { PublicConversation } from "@/lib/bridge-conversations";
import {
  archiveConversation,
  fetchConversationHistory,
  renameConversation,
} from "@/lib/public-conversations";

type HistoryFilter = "all" | "active" | "archived";
type HistoryState = "idle" | "loading" | "ready" | "empty" | "error";

function title(conversation: PublicConversation): string {
  return conversation.title_source === "default" ? "New conversation" : conversation.title;
}

export const ConversationHistoryManager = memo(function ConversationHistoryManager({
  onChanged,
  initialConversations,
  onNotice,
  onOpen,
}: Readonly<{
  onChanged: (conversation: PublicConversation) => void;
  initialConversations: PublicConversation[];
  onNotice: (message: string) => void;
  onOpen: (conversation: PublicConversation) => void;
}>) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [rows, setRows] = useState<PublicConversation[]>(initialConversations);
  const [cursor, setCursor] = useState<string | null>(null);
  const [state, setState] = useState<HistoryState>("idle");
  const [loadingMore, setLoadingMore] = useState(false);
  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const requestSequence = useRef(0);
  const viewSequence = useRef(0);
  const visibleRows = query.trim() === "" && filter === "all" && rows.length === 0
    ? initialConversations
    : rows;

  const read = useCallback(async (nextCursor: string | null = null) => {
    const request = requestSequence.current + 1;
    requestSequence.current = request;
    if (nextCursor) setLoadingMore(true);
    else setState("loading");
    try {
      const payload = await fetchConversationHistory(filter, query.trim() || null, nextCursor);
      if (requestSequence.current !== request) return;
      setRows((current) => nextCursor
        ? [...current, ...payload.conversations.filter((item) => !current.some((existing) => existing.id === item.id))]
        : payload.conversations);
      setCursor(payload.next_cursor);
      setState(payload.count === 0 && !nextCursor ? "empty" : "ready");
    } catch {
      if (requestSequence.current === request) setState("error");
    } finally {
      if (requestSequence.current === request) setLoadingMore(false);
    }
  }, [filter, query]);

  useEffect(() => {
    if (!open) return;
    void read();
    return () => { requestSequence.current += 1; };
  }, [open, read]);

  function focusHistory(id: string, action: "rename" | "lifecycle") {
    window.setTimeout(() => {
      const prefix = action === "rename" ? "history-rename" : "history-lifecycle";
      const target = document.getElementById(`${prefix}-${id}`)
        ?? document.getElementById("conversation-history-search")
        ?? document.getElementById("recent-conversations-summary");
      target?.focus();
    }, 0);
  }

  function focusRenameEditor(id: string) {
    window.setTimeout(() => {
      const target = document.getElementById(`history-title-${id}`)
        ?? document.getElementById("conversation-history-search")
        ?? document.getElementById("recent-conversations-summary");
      target?.focus();
    }, 0);
  }

  async function changeArchive(conversation: PublicConversation) {
    if (busyIds.has(conversation.id)) return;
    const archived = conversation.state !== "archived";
    const view = viewSequence.current;
    setBusyIds((current) => new Set(current).add(conversation.id));
    try {
      const result = await archiveConversation(conversation.id, conversation.revision, archived);
      onChanged(result.conversation);
      onNotice(archived
        ? "Conversation archived. Its work and evidence were not changed."
        : "Conversation restored and ready to reopen.");
      if (viewSequence.current === view) {
        setRows((current) => current.map((item) => item.id === conversation.id ? result.conversation : item));
        await read();
        focusHistory(conversation.id, "lifecycle");
      }
    } catch {
      onNotice("That Conversation changed or could not be updated. History was refreshed.");
      if (viewSequence.current === view) {
        await read();
        focusHistory(conversation.id, "lifecycle");
      }
    } finally {
      setBusyIds((current) => { const next = new Set(current); next.delete(conversation.id); return next; });
    }
  }

  async function saveRename(conversation: PublicConversation) {
    if (busyIds.has(conversation.id)) return;
    const nextTitle = renameDraft.trim();
    const view = viewSequence.current;
    if (!nextTitle || Array.from(nextTitle).length > 160 || nextTitle === conversation.title) return;
    setBusyIds((current) => new Set(current).add(conversation.id));
    try {
      const result = await renameConversation(conversation.id, conversation.revision, nextTitle);
      onChanged(result.conversation);
      onNotice("Conversation renamed.");
      if (viewSequence.current === view) {
        setRows((current) => current.map((item) => item.id === conversation.id ? result.conversation : item));
        setEditingId(null);
        await read();
        focusHistory(conversation.id, "rename");
      }
    } catch {
      onNotice("That Conversation changed or could not be renamed. Your title was kept for review.");
      if (viewSequence.current === view) {
        await read();
        focusRenameEditor(conversation.id);
      }
    } finally {
      setBusyIds((current) => { const next = new Set(current); next.delete(conversation.id); return next; });
    }
  }

  return <details className="conversation-history" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary id="recent-conversations-summary">Recent Conversations</summary>
    <div className="history-manager">
      <div className="history-toolbar">
        <label><span>Search titles</span><input autoComplete="off" id="conversation-history-search" onChange={(event) => { viewSequence.current += 1; setRows([]); setCursor(null); setQuery(event.target.value); }} placeholder="Find a Conversation" type="search" value={query} /></label>
        <label><span>State</span><select aria-label="Conversation history state" onChange={(event) => { viewSequence.current += 1; setRows([]); setCursor(null); setFilter(event.target.value as HistoryFilter); }} value={filter}><option value="all">All</option><option value="active">Active</option><option value="archived">Archived</option></select></label>
      </div>
      <p aria-live="polite" className="history-status">{state === "loading" ? "Searching Conversation titles…" : state === "empty" ? "No Conversations match this search." : state === "error" ? "Conversation history could not be read safely." : state === "ready" ? `${visibleRows.length} Conversation${visibleRows.length === 1 ? "" : "s"} shown.` : ""}</p>
      {visibleRows.length ? <ul>{visibleRows.map((conversation, index) => { const busy = busyIds.has(conversation.id); const editing = editingId === conversation.id; const rowName = `${title(conversation)}, Conversation ${index + 1}`; return <li key={conversation.id}>
        <div className="history-copy">
          {editing ? <label htmlFor={`history-title-${conversation.id}`}><span>Conversation title</span><input autoFocus disabled={busy} id={`history-title-${conversation.id}`} onChange={(event) => { if (Array.from(event.target.value).length <= 161) setRenameDraft(event.target.value); }} onKeyDown={(event) => { if (event.key === "Escape") { setEditingId(null); focusHistory(conversation.id, "rename"); } else if (event.key === "Enter") { event.preventDefault(); void saveRename(conversation); } }} value={renameDraft} /></label> : <><strong>{title(conversation)}</strong><small>{conversation.state === "archived" ? "Archived" : "Active"} · {new Date(conversation.updated_at).toLocaleDateString()}</small></>}
        </div>
        <div className="history-actions">
          {editing ? <><button disabled={busy || !renameDraft.trim() || Array.from(renameDraft.trim()).length > 160 || renameDraft.trim() === conversation.title} onClick={() => void saveRename(conversation)} type="button">Save</button><button disabled={busy} onClick={() => { setEditingId(null); focusHistory(conversation.id, "rename"); }} type="button">Cancel</button></> : <><button aria-label={`Open ${rowName}`} className="history-open" onClick={() => onOpen(conversation)} type="button">Open</button><button aria-label={`Rename ${rowName}`} id={`history-rename-${conversation.id}`} onClick={() => { setEditingId(conversation.id); setRenameDraft(conversation.title); }} type="button">Rename</button><button aria-label={`${conversation.state === "archived" ? "Restore" : "Archive"} ${rowName}`} disabled={busy} id={`history-lifecycle-${conversation.id}`} onClick={() => void changeArchive(conversation)} type="button">{busy ? "Updating…" : conversation.state === "archived" ? "Restore" : "Archive"}</button></>}
        </div>
      </li>; })}</ul> : null}
      {cursor ? <button className="history-load-more" disabled={loadingMore} onClick={() => void read(cursor)} type="button">{loadingMore ? "Loading…" : "Load more"}</button> : null}
    </div>
  </details>;
});
