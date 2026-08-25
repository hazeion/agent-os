"use client";

// THROWAWAY PROTOTYPE #132: this entire route is evidence, not production code.

import {
  memo,
  Profiler,
  type ProfilerOnRenderCallback,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import {
  createInitialState,
  PROTOTYPE_QUEUE_LIMIT,
  prototypeReducer,
  type Conversation,
  type Message,
  type PrototypeState,
} from "./model";
import "./prototype.css";

type BenchmarkResult = Readonly<{
  fixture_messages: number;
  paged_dom_messages: number;
  all_dom_messages: number;
  paged_render_ms: number;
  all_render_ms: number;
  input_latency_ms: readonly number[];
  switch_latency_ms: readonly number[];
  stream_paint_ms: readonly number[];
  profiler_commit_ms: Readonly<{ median: number; maximum: number; samples: number }>;
  stale_event_ignored: boolean;
  crossed_event_visible: boolean;
  draft_isolation: boolean;
  queue_cap_holds: boolean;
  focus_retained: boolean;
  scroll_anchor_delta_px: number;
  transcript_dom_order: boolean;
  reduced_motion: boolean;
}>;

declare global {
  interface Window {
    __MENTAT_PROTOTYPE__?: Readonly<{
      benchmark: () => Promise<BenchmarkResult>;
      snapshot: () => PrototypeState;
      version: 1;
    }>;
  }
}

type StreamRegistration = {
  conversationId: string;
  runId: string;
  emit: (sequence: number, text: string) => void;
};

const streamHarness: {
  active: StreamRegistration | null;
  retired: StreamRegistration[];
} = { active: null, retired: [] };

function nextFrame() {
  return new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
}

async function waitFor(check: () => boolean, label: string, timeoutMs = 5_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    if (check()) return;
    await nextFrame();
  }
  throw new Error(`Timed out waiting for ${label}`);
}

function median(values: readonly number[]) {
  if (!values.length) return 0;
  const ordered = [...values].sort((a, b) => a - b);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
}

function rounded(value: number) {
  return Math.round(value * 100) / 100;
}

function statusLabel(status: Conversation["run"]["status"]) {
  return status.replaceAll("_", " ");
}

const Transcript = memo(function Transcript({
  agent,
  messages,
  title,
  renderMode,
  visibleMessageLimit,
  onLoadOlder,
}: Readonly<{
  agent: string;
  messages: readonly Message[];
  title: string;
  renderMode: PrototypeState["renderMode"];
  visibleMessageLimit: number;
  onLoadOlder: () => void;
}>) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<{ id: string; top: number } | null>(null);
  const previousLength = useRef(messages.length);
  const shown = renderMode === "all"
    ? messages
    : messages.slice(-visibleMessageLimit);
  const hiddenCount = messages.length - shown.length;

  const loadOlder = useCallback(() => {
    const root = scrollRef.current;
    if (root) {
      const first = root.querySelector<HTMLElement>("[data-message-id]");
      if (first) anchorRef.current = { id: first.dataset.messageId ?? "", top: first.getBoundingClientRect().top };
    }
    onLoadOlder();
  }, [onLoadOlder]);

  useLayoutEffect(() => {
    const root = scrollRef.current;
    const anchor = anchorRef.current;
    if (root && anchor) {
      const current = root.querySelector<HTMLElement>(`[data-message-id="${CSS.escape(anchor.id)}"]`);
      if (current) root.scrollTop += current.getBoundingClientRect().top - anchor.top;
      anchorRef.current = null;
    }
    if (root && messages.length > previousLength.current) {
      const distanceFromBottom = root.scrollHeight - root.scrollTop - root.clientHeight;
      if (distanceFromBottom < 120) root.scrollTop = root.scrollHeight;
    }
    previousLength.current = messages.length;
  }, [messages.length, shown.length]);

  return (
    <div className="proto-transcript" data-transcript-scroll ref={scrollRef}>
      {hiddenCount > 0 ? (
        <div className="proto-history-control">
          <span>Showing {shown.length.toLocaleString()} of {messages.length.toLocaleString()} messages</span>
          <button data-action="load-older" onClick={loadOlder} type="button">Load 200 older</button>
        </div>
      ) : null}
      <ol aria-label={`${title} transcript`} className="proto-message-list" data-transcript-list>
        {shown.map((message) => (
          <li
            className={`proto-message proto-message-${message.role}`}
            data-message-id={message.id}
            data-sequence={message.sequence}
            data-state={message.state}
            key={message.id}
          >
            <span className="proto-message-role">{message.role === "user" ? "You" : agent}</span>
            <p>{message.text}</p>
            {message.state !== "accepted" ? <small>{message.state}</small> : null}
          </li>
        ))}
      </ol>
    </div>
  );
});

const ConversationTabs = memo(function ConversationTabs({
  conversations,
  openTabs,
  selectedId,
  onClose,
  onSelect,
}: Readonly<{
  conversations: PrototypeState["conversations"];
  openTabs: PrototypeState["openTabs"];
  selectedId: string;
  onClose: (id: string) => void;
  onSelect: (id: string) => void;
}>) {
  return (
    <div aria-label="Open Conversations" className="proto-tabs" role="tablist">
      {openTabs.map((id) => {
        const conversation = conversations[id];
        if (!conversation) return null;
        return (
          <div className="proto-tab-shell" key={id}>
            <button
              aria-controls="prototype-conversation-panel"
              aria-selected={id === selectedId}
              className="proto-tab"
              data-conversation-id={id}
              onClick={() => onSelect(id)}
              role="tab"
              type="button"
            >
              <span>{conversation.title}</span>
              <small>{statusLabel(conversation.run.status)}</small>
            </button>
            <button
              aria-label={`Close ${conversation.title} tab`}
              className="proto-tab-close"
              onClick={() => onClose(id)}
              type="button"
            >×</button>
          </div>
        );
      })}
    </div>
  );
});

const ActivityRail = memo(function ActivityRail({
  conversations,
  order,
  selectedId,
  onSelect,
}: Readonly<{
  conversations: PrototypeState["conversations"];
  order: PrototypeState["conversationOrder"];
  selectedId: string;
  onSelect: (id: string) => void;
}>) {
  const groups = useMemo(() => {
    const result = new Map<string, Conversation[]>();
    for (const id of order) {
      const conversation = conversations[id];
      const group = result.get(conversation.agent) ?? [];
      group.push(conversation);
      result.set(conversation.agent, group);
    }
    return [...result.entries()];
  }, [conversations, order]);

  return (
    <aside aria-label="Agent activity" className="proto-activity-rail">
      <header><h2>Agent activity</h2><p>Global bounded hints</p></header>
      {groups.map(([agent, items]) => (
        <section className="proto-agent-group" key={agent}>
          <h3><span aria-hidden="true">●</span>{agent}</h3>
          {items.map((conversation) => (
            <button
              aria-current={conversation.id === selectedId ? "true" : undefined}
              className="proto-rail-conversation"
              data-rail-conversation={conversation.id}
              key={conversation.id}
              onClick={() => onSelect(conversation.id)}
              type="button"
            >
              <span>{conversation.title}</span>
              <small>{conversation.attention ?? conversation.activityHint}</small>
              <em>{statusLabel(conversation.run.status)}</em>
            </button>
          ))}
        </section>
      ))}
    </aside>
  );
});

function Queue({
  conversation,
  onCancel,
  onEdit,
}: Readonly<{
  conversation: Conversation;
  onCancel: (turnId: string) => void;
  onEdit: (turnId: string, value: string) => void;
}>) {
  const visible = conversation.queue.filter((turn) => turn.state !== "cancelled");
  if (!visible.length) return null;
  return (
    <section aria-label="Queued turns" className="proto-queue">
      <header><strong>Queued</strong><span>{visible.length}/{PROTOTYPE_QUEUE_LIMIT}</span></header>
      {visible.map((turn, index) => (
        <div className="proto-queue-row" data-turn-id={turn.id} key={turn.id}>
          <span>{index + 1}</span>
          <input
            aria-label={`Queued turn ${index + 1}`}
            disabled={turn.state === "optimistic"}
            onChange={(event) => onEdit(turn.id, event.currentTarget.value)}
            value={turn.text}
          />
          <small>{turn.state}</small>
          <button disabled={turn.state === "optimistic"} onClick={() => onCancel(turn.id)} type="button">Cancel</button>
        </div>
      ))}
    </section>
  );
}

const SCENARIOS = [
  {
    id: "tabs",
    title: "Tabs and drafts",
    description: "Close and reopen a live Conversation, then confirm each draft stays with its Conversation.",
  },
  {
    id: "streams",
    title: "Streams and concurrent work",
    description: "Switch selected detail streams while background activity continues in the rail.",
  },
  {
    id: "queue",
    title: "Queue and rollback",
    description: "Accept eight turns, reject the ninth, and restore a draft when Send fails.",
  },
  {
    id: "transcript",
    title: "Long transcript",
    description: "Compare all-message rendering with bounded pages and inspect ordered accessibility semantics.",
  },
] as const;

export function AgentConsoleStatePrototype() {
  const [state, dispatch] = useReducer(prototypeReducer, undefined, createInitialState);
  const [scenario, setScenario] = useState<(typeof SCENARIOS)[number]["id"]>("tabs");
  const [benchmark, setBenchmark] = useState<BenchmarkResult | null>(null);
  const [benchmarking, setBenchmarking] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const stateRef = useRef(state);
  const profilerSamples = useRef<number[]>([]);
  const sendCounter = useRef(0);

  const selected = state.conversations[state.selectedId] ?? state.conversations[state.conversationOrder[0]];

  useLayoutEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    const preference = matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(preference.matches);
    update();
    preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, []);

  const recordProfile = useCallback<ProfilerOnRenderCallback>((_id, _phase, actualDuration) => {
    profilerSamples.current.push(actualDuration);
    if (profilerSamples.current.length > 200) profilerSamples.current.shift();
  }, []);

  const selectConversation = useCallback((conversationId: string) => {
    dispatch({ type: "select", conversationId });
  }, []);

  const closeConversation = useCallback((conversationId: string) => {
    dispatch({ type: "close", conversationId });
  }, []);

  const loadOlder = useCallback(() => {
    dispatch({ type: "load_older", count: 200 });
  }, []);

  const send = useCallback(() => {
    const current = stateRef.current;
    const conversationId = current.selectedId;
    const shouldFail = current.failNextSend;
    const clientId = `client_${++sendCounter.current}`;
    dispatch({ type: "send_begin", conversationId, clientId });
    window.setTimeout(() => {
      dispatch({ type: shouldFail ? "send_reject" : "send_accept", conversationId, clientId });
    }, 180);
  }, []);

  const emitSelectedEvent = useCallback((text = "Selected Run reported useful progress.") => {
    const registration = streamHarness.active;
    if (!registration) return;
    const conversation = stateRef.current.conversations[registration.conversationId];
    registration.emit(conversation.cursor + 1, text);
  }, []);

  const emitStaleEvent = useCallback(() => {
    const registration = [...streamHarness.retired].reverse().find((item) => (
      item.conversationId !== stateRef.current.selectedId
    ));
    if (!registration) return;
    registration.emit(9_999, "CROSSED STALE EVENT — this must never render");
  }, []);

  useEffect(() => {
    const registration: StreamRegistration = {
      conversationId: selected.id,
      runId: selected.run.id,
      emit: (sequence, text) => dispatch({
        type: "stream_event",
        conversationId: selected.id,
        runId: selected.run.id,
        sequence,
        text,
      }),
    };
    streamHarness.active = registration;
    dispatch({ type: "stream_connected", conversationId: selected.id, runId: selected.run.id });
    return () => {
      streamHarness.retired.push(registration);
      if (streamHarness.active === registration) streamHarness.active = null;
      dispatch({ type: "stream_cleaned", conversationId: selected.id, runId: selected.run.id });
    };
  }, [selected.id, selected.run.id]);

  const fillQueue = useCallback(() => {
    const conversationId = stateRef.current.selectedId;
    for (let index = 0; index < PROTOTYPE_QUEUE_LIMIT; index += 1) {
      const clientId = `fill_${Date.now()}_${index}`;
      dispatch({ type: "set_draft", conversationId, value: `Queued follow-up ${index + 1}` });
      dispatch({ type: "send_begin", conversationId, clientId });
      dispatch({ type: "send_accept", conversationId, clientId });
    }
  }, []);

  const tryNinth = useCallback(() => {
    const conversationId = stateRef.current.selectedId;
    dispatch({ type: "set_draft", conversationId, value: "Ninth turn must remain in the composer" });
    dispatch({ type: "send_begin", conversationId, clientId: `ninth_${Date.now()}` });
  }, []);

  const runBenchmark = useCallback(async () => {
    setBenchmarking(true);
    setBenchmark(null);
    profilerSamples.current = [];
    dispatch({ type: "reset", state: createInitialState() });
    await waitFor(() => document.querySelector("[data-prototype-selected]")?.getAttribute("data-prototype-selected") === "conv_research", "prototype reset");

    dispatch({ type: "load_stress", conversationId: "conv_research", count: 2_000 });
    await waitFor(() => stateRef.current.conversations.conv_research.messages.length === 2_000, "stress fixture");
    await nextFrame();

    const measureMode = async (mode: "paged" | "all") => {
      const started = performance.now();
      dispatch({ type: "set_render_mode", mode });
      await waitFor(() => stateRef.current.renderMode === mode, `${mode} state`);
      await nextFrame();
      await nextFrame();
      return rounded(performance.now() - started);
    };
    const allRender = await measureMode("all");
    const allDomMessages = document.querySelectorAll("[data-message-id]").length;
    const pagedRender = await measureMode("paged");
    const pagedDomMessages = document.querySelectorAll("[data-message-id]").length;

    const switchTimes: number[] = [];
    for (const conversationId of ["conv_build", "conv_research", "conv_build", "conv_research", "conv_build", "conv_research", "conv_build"]) {
      const started = performance.now();
      dispatch({ type: "select", conversationId });
      await waitFor(() => document.querySelector("[data-prototype-selected]")?.getAttribute("data-prototype-selected") === conversationId, "tab switch paint");
      switchTimes.push(rounded(performance.now() - started));
    }

    dispatch({ type: "select", conversationId: "conv_research" });
    await waitFor(() => stateRef.current.selectedId === "conv_research", "research selection");
    const inputTimes: number[] = [];
    for (let index = 0; index < 7; index += 1) {
      const value = `Draft latency sample ${index + 1}`;
      const started = performance.now();
      dispatch({ type: "set_draft", conversationId: "conv_research", value });
      await waitFor(() => (document.querySelector("[data-composer]") as HTMLTextAreaElement | null)?.value === value, "draft paint");
      inputTimes.push(rounded(performance.now() - started));
    }

    const streamTimes: number[] = [];
    for (let index = 0; index < 7; index += 1) {
      const text = `Benchmark stream event ${index + 1}`;
      const started = performance.now();
      emitSelectedEvent(text);
      await waitFor(() => document.querySelector("[data-transcript-list]")?.textContent?.includes(text) === true, "stream paint");
      streamTimes.push(rounded(performance.now() - started));
    }

    dispatch({ type: "set_draft", conversationId: "conv_research", value: "research draft" });
    dispatch({ type: "set_draft", conversationId: "conv_build", value: "builder draft" });
    await waitFor(() => stateRef.current.conversations.conv_build.draft === "builder draft", "draft isolation state");
    const draftIsolation = stateRef.current.conversations.conv_research.draft === "research draft"
      && stateRef.current.conversations.conv_build.draft === "builder draft";

    dispatch({ type: "select", conversationId: "conv_build" });
    await waitFor(() => stateRef.current.stream.activeConversationId === "conv_build", "stream handoff");
    const ignoredBefore = stateRef.current.stream.ignoredEvents;
    emitStaleEvent();
    await waitFor(() => stateRef.current.stream.ignoredEvents > ignoredBefore, "stale event rejection");
    const crossedEventVisible = Object.values(stateRef.current.conversations).some((conversation) => (
      conversation.messages.some((message) => message.text.includes("CROSSED STALE EVENT"))
    ));

    dispatch({ type: "select", conversationId: "conv_plan" });
    await waitFor(() => stateRef.current.selectedId === "conv_plan", "queue fixture selection");
    for (let index = 0; index < PROTOTYPE_QUEUE_LIMIT; index += 1) {
      const clientId = `bench_queue_${index}`;
      dispatch({ type: "set_draft", conversationId: "conv_plan", value: `Queue benchmark ${index + 1}` });
      dispatch({ type: "send_begin", conversationId: "conv_plan", clientId });
      dispatch({ type: "send_accept", conversationId: "conv_plan", clientId });
    }
    dispatch({ type: "set_draft", conversationId: "conv_plan", value: "Ninth remains" });
    dispatch({ type: "send_begin", conversationId: "conv_plan", clientId: "bench_ninth" });
    await waitFor(() => stateRef.current.conversations.conv_plan.queue.length === PROTOTYPE_QUEUE_LIMIT, "queue cap");
    const queueCapHolds = stateRef.current.conversations.conv_plan.queue.length === PROTOTYPE_QUEUE_LIMIT
      && stateRef.current.conversations.conv_plan.draft === "Ninth remains";

    dispatch({ type: "select", conversationId: "conv_research" });
    await waitFor(() => stateRef.current.selectedId === "conv_research", "anchor selection");
    const transcript = document.querySelector<HTMLElement>("[data-transcript-scroll]");
    if (transcript) transcript.scrollTop = 260;
    await nextFrame();
    const anchor = transcript?.querySelector<HTMLElement>("[data-message-id]");
    const anchorTop = anchor?.getBoundingClientRect().top ?? 0;
    document.querySelector<HTMLButtonElement>("[data-action='load-older']")?.click();
    await nextFrame();
    await nextFrame();
    const anchorAfter = anchor?.getBoundingClientRect().top ?? anchorTop;
    const scrollAnchorDelta = rounded(Math.abs(anchorAfter - anchorTop));

    const railTarget = document.querySelector<HTMLButtonElement>("[data-rail-conversation='conv_build']");
    railTarget?.focus();
    railTarget?.click();
    await waitFor(() => stateRef.current.selectedId === "conv_build", "rail focus switch");
    const focusRetained = document.activeElement === railTarget;

    dispatch({ type: "select", conversationId: "conv_research" });
    await waitFor(() => stateRef.current.selectedId === "conv_research", "order selection");
    const sequences = [...document.querySelectorAll<HTMLElement>("[data-sequence]")].map((item) => Number(item.dataset.sequence));
    const transcriptOrder = sequences.every((value, index) => index === 0 || sequences[index - 1] < value);
    const profile = profilerSamples.current;
    const result: BenchmarkResult = {
      fixture_messages: 2_000,
      paged_dom_messages: pagedDomMessages,
      all_dom_messages: allDomMessages,
      paged_render_ms: pagedRender,
      all_render_ms: allRender,
      input_latency_ms: inputTimes,
      switch_latency_ms: switchTimes,
      stream_paint_ms: streamTimes,
      profiler_commit_ms: {
        median: rounded(median(profile)),
        maximum: rounded(Math.max(0, ...profile)),
        samples: profile.length,
      },
      stale_event_ignored: stateRef.current.stream.ignoredEvents > ignoredBefore,
      crossed_event_visible: crossedEventVisible,
      draft_isolation: draftIsolation,
      queue_cap_holds: queueCapHolds,
      focus_retained: focusRetained,
      scroll_anchor_delta_px: scrollAnchorDelta,
      transcript_dom_order: transcriptOrder,
      reduced_motion: matchMedia("(prefers-reduced-motion: reduce)").matches,
    };
    setBenchmark(result);
    setBenchmarking(false);
    return result;
  }, [emitSelectedEvent, emitStaleEvent]);

  useEffect(() => {
    window.__MENTAT_PROTOTYPE__ = {
      benchmark: runBenchmark,
      snapshot: () => stateRef.current,
      version: 1,
    };
    document.documentElement.dataset.prototypeReady = "true";
    performance.mark("mentat-agent-console-prototype-ready");
  }, [runBenchmark]);

  const scenarioControls = {
    tabs: (
      <>
        <button onClick={() => dispatch({ type: "set_draft", conversationId: "conv_research", value: "Research draft survives switching" })} type="button">1. Write Researcher draft</button>
        <button onClick={() => dispatch({ type: "close", conversationId: "conv_research" })} type="button">2. Close Researcher tab</button>
        <button onClick={() => dispatch({ type: "select", conversationId: "conv_research" })} type="button">3. Reopen from rail</button>
      </>
    ),
    streams: (
      <>
        <button onClick={() => emitSelectedEvent()} type="button">1. Emit selected detail</button>
        <button onClick={() => dispatch({ type: "select", conversationId: "conv_build" })} type="button">2. Switch to Builder</button>
        <button onClick={() => dispatch({ type: "global_hint", conversationId: "conv_research", text: "Background Run completed a tool" })} type="button">3. Emit Researcher global hint</button>
        <button onClick={emitStaleEvent} type="button">4. Deliver stale old-stream event</button>
      </>
    ),
    queue: (
      <>
        <button onClick={fillQueue} type="button">1. Fill eight-turn queue</button>
        <button onClick={tryNinth} type="button">2. Try ninth turn</button>
        <button onClick={() => dispatch({ type: "set_fail_next", value: true })} type="button">3. Fail next Send</button>
        <button onClick={send} type="button">4. Send and restore draft</button>
      </>
    ),
    transcript: (
      <>
        <button onClick={() => dispatch({ type: "load_stress", conversationId: stateRef.current.selectedId, count: 2_000 })} type="button">1. Load 2,000 messages</button>
        <button onClick={() => dispatch({ type: "set_render_mode", mode: "all" })} type="button">2. Render all</button>
        <button onClick={() => dispatch({ type: "set_render_mode", mode: "paged" })} type="button">3. Use bounded pages</button>
        <button onClick={() => void runBenchmark()} type="button">4. Run evidence pass</button>
      </>
    ),
  };

  return (
    <div className="prototype-page">
      <header className="prototype-intro">
        <div>
          <p className="prototype-kicker">Throwaway prototype · GitHub #132</p>
          <h1>Can React built-ins keep Mentat’s Conversations fast and isolated?</h1>
          <p>
            Drive tabs, drafts, queues, selected-Run events, background activity, and a 2,000-message
            transcript. This page uses in-memory fixture state and cannot call Mentat’s backend.
          </p>
        </div>
        <button className="prototype-reset" onClick={() => dispatch({ type: "reset", state: createInitialState() })} type="button">Reset prototype</button>
      </header>

      <section aria-label="Guided walkthroughs" className="prototype-lab">
        <div className="prototype-scenario-tabs" role="tablist">
          {SCENARIOS.map((item) => (
            <button aria-selected={scenario === item.id} key={item.id} onClick={() => setScenario(item.id)} role="tab" type="button">{item.title}</button>
          ))}
        </div>
        <p>{SCENARIOS.find((item) => item.id === scenario)?.description}</p>
        <div className="prototype-steps">{scenarioControls[scenario]}</div>
      </section>

      <Profiler id="agent-console-state-prototype" onRender={recordProfile}>
        <div className="prototype-console" data-prototype-selected={selected.id}>
          <aside aria-label="Workspace" className="proto-workspace-rail">
            <strong aria-label="Mentat">M</strong>
            <nav>
              {['⌂ Home', '◉ Agents', '▤ Projects & Tasks', '□ Calendar', '◌ Runs', '⚙ Settings'].map((item) => <span key={item}>{item}</span>)}
            </nav>
            <small>Prototype only<br />Python authority untouched</small>
          </aside>

          <main className="proto-center">
            <ConversationTabs
              conversations={state.conversations}
              onClose={closeConversation}
              onSelect={selectConversation}
              openTabs={state.openTabs}
              selectedId={selected.id}
            />
            <section aria-labelledby="prototype-conversation-title" className="proto-conversation" id="prototype-conversation-panel" role="tabpanel">
              <header className="proto-conversation-header">
                <div><p>{selected.agent}</p><h2 id="prototype-conversation-title">{selected.title}</h2></div>
                <span data-run-status={selected.run.status}>{statusLabel(selected.run.status)}</span>
              </header>
              <Transcript
                agent={selected.agent}
                messages={selected.messages}
                onLoadOlder={loadOlder}
                renderMode={state.renderMode}
                title={selected.title}
                visibleMessageLimit={state.visibleMessageLimit}
              />
              <Queue
                conversation={selected}
                onCancel={(turnId) => dispatch({ type: "queue_cancel", conversationId: selected.id, turnId })}
                onEdit={(turnId, value) => dispatch({ type: "queue_edit", conversationId: selected.id, turnId, value })}
              />
              <form className="proto-composer" onSubmit={(event) => { event.preventDefault(); send(); }}>
                <textarea
                  aria-label={`Message ${selected.agent}`}
                  data-composer
                  onChange={(event) => dispatch({ type: "set_draft", conversationId: selected.id, value: event.currentTarget.value })}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                      event.preventDefault();
                      send();
                    }
                  }}
                  placeholder="Message Mentat…"
                  rows={1}
                  value={selected.draft}
                />
                <footer>
                  <span>Agent <strong>{selected.agent}</strong></span>
                  <span>Provider <strong>OpenAI</strong></span>
                  <span>Model <strong>GPT-5</strong></span>
                  <button aria-label="Send message" type="submit">↑</button>
                </footer>
              </form>
            </section>
          </main>

          <ActivityRail
            conversations={state.conversations}
            onSelect={selectConversation}
            order={state.conversationOrder}
            selectedId={selected.id}
          />
        </div>
      </Profiler>

      <section aria-labelledby="prototype-state-title" className="prototype-state">
        <div className="prototype-state-heading">
          <div><p className="prototype-kicker">Full relevant state</p><h2 id="prototype-state-title">What just changed</h2></div>
          <span aria-live="polite">{state.notice}</span>
        </div>
        <dl>
          <div><dt>Selected</dt><dd>{selected.title}</dd></div>
          <div><dt>Open tabs</dt><dd>{state.openTabs.length ? state.openTabs.map((id) => state.conversations[id]?.title).join(" · ") : "None"}</dd></div>
          <div><dt>Selected stream</dt><dd>{state.stream.activeRunId ?? "Connecting"}</dd></div>
          <div><dt>Stream lifecycle</dt><dd>{state.stream.connects} connects · {state.stream.cleanups} cleanups · {state.stream.ignoredEvents} ignored</dd></div>
          <div><dt>Drafts</dt><dd>{state.conversationOrder.map((id) => `${state.conversations[id].agent}: ${state.conversations[id].draft || "empty"}`).join(" · ")}</dd></div>
          <div><dt>Transcript strategy</dt><dd>{state.renderMode} · limit {state.visibleMessageLimit}</dd></div>
          <div><dt>Last transition</dt><dd>{state.lastChange}</dd></div>
          <div><dt>Motion preference</dt><dd>{reducedMotion ? "reduced" : "standard"}</dd></div>
        </dl>
        <div className="prototype-free-play" aria-label="Free-play actions">
          <button onClick={() => emitSelectedEvent()} type="button">Emit selected detail</button>
          <button onClick={() => dispatch({ type: "global_hint", conversationId: selected.id === "conv_research" ? "conv_build" : "conv_research", text: `Background hint ${Date.now()}` })} type="button">Emit background hint</button>
          <button onClick={() => dispatch({ type: "set_attention", conversationId: selected.id, text: selected.attention ? null : "Approval needs your answer" })} type="button">Toggle attention</button>
          <button onClick={fillQueue} type="button">Fill queue</button>
          <button onClick={tryNinth} type="button">Try ninth turn</button>
          <button disabled={benchmarking} onClick={() => void runBenchmark()} type="button">{benchmarking ? "Measuring…" : "Run measurements"}</button>
        </div>
        {benchmark ? <pre aria-label="Latest measurement evidence" data-benchmark-output>{JSON.stringify(benchmark, null, 2)}</pre> : null}
      </section>
    </div>
  );
}
