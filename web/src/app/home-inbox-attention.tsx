"use client";

import { useEffect, useRef, useState } from "react";
import { type InboxPage } from "@/lib/owner-inbox-contract";
import { ownerInbox } from "@/lib/public-owner-inbox";

const REFRESH_INTERVAL_MS = 30_000;

export function HomeInboxAttention() {
  const [page, setPage] = useState<InboxPage | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "unavailable">("loading");
  const [refreshing, setRefreshing] = useState(false);
  const mounted = useRef(false), generation = useRef(0), pending = useRef<number | null>(null);
  const trailing = useRef(false), hasPage = useRef(false);
  const refreshRef = useRef<() => void>(() => undefined);
  useEffect(() => {
    mounted.current = true;
    const mountedRef = mounted, generationRef = generation, pendingRef = pending, trailingRef = trailing, hasPageRef = hasPage;
    async function refresh() {
      if (!mountedRef.current || pendingRef.current !== null) return;
      trailingRef.current = false;
      const current = ++generationRef.current;
      pendingRef.current = current;
      if (!hasPageRef.current) setState("loading");
      setRefreshing(true);
      try {
        const result = await ownerInbox("page", { view: "needs_me", after: null });
        if (mountedRef.current && generationRef.current === current && !trailingRef.current) {
          hasPageRef.current = true;
          setPage(result); setState(result.counts.needs_me === 0 ? "empty" : "ready");
        }
      } catch {
        if (mountedRef.current && generationRef.current === current && !trailingRef.current) setState("unavailable");
      } finally {
        if (pendingRef.current === current) {
          pendingRef.current = null;
          if (mountedRef.current) setRefreshing(false);
          if (trailingRef.current && mountedRef.current && !document.hidden) {
            trailingRef.current = false;
            queueMicrotask(() => { void refresh(); });
          }
        }
      }
    }
    refreshRef.current = () => { void refresh(); };
    queueMicrotask(() => { if (mountedRef.current) void refresh(); });
    const visible = () => { if (!document.hidden) { if (pendingRef.current !== null) trailingRef.current = true; else void refresh(); } };
    document.addEventListener("visibilitychange", visible);
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, REFRESH_INTERVAL_MS);
    return () => {
      mountedRef.current = false; generationRef.current++; pendingRef.current = null; trailingRef.current = false; refreshRef.current = () => undefined;
      document.removeEventListener("visibilitychange", visible);
      window.clearInterval(timer);
    };
  }, []);
  const items = page?.items.slice(0, 3) ?? [];
  return <section aria-label="Inbox attention" className="planning-attention home-inbox-attention">
    <div className="planning-attention-heading"><div><p className="console-kicker">Owner Inbox</p><h3>{state === "unavailable" && page ? "Last checked Inbox" : "Needs your review"}{page ? ` · ${page.counts.needs_me}` : ""}</h3></div><button aria-label="Refresh Inbox attention" disabled={refreshing} onClick={() => refreshRef.current()} type="button">Refresh</button></div>
    {refreshing && page ? <span className="home-inbox-refreshing">Checking…</span> : null}
    <p aria-live="polite">{state === "loading" ? "Checking Inbox…" : state === "unavailable" ? page ? "Inbox could not refresh. Last checked items are shown." : "Inbox attention is temporarily unavailable." : state === "empty" ? "No Inbox review items right now." : ""}</p>
    {(state === "ready" || state === "unavailable") && page ? <ul>{items.map((item) => <li key={item.id}><a href={`/inbox?item=${encodeURIComponent(item.id)}`}><strong>{item.title}</strong><span>{item.state === "needs_review" ? "Review saved results" : item.state === "activation_required" ? "Project needs activation" : "Source changed · inspect in Inbox"}</span></a></li>)}</ul> : null}
    <a className="planning-view-all" href="/inbox">Open Inbox</a>
  </section>;
}
