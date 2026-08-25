// THROWAWAY PROTOTYPE #132: pure interaction model, not production code.

export type RunStatus =
  | "running"
  | "waiting_for_approval"
  | "waiting_for_clarification"
  | "completed"
  | "failed"
  | "stopped";

export type Message = Readonly<{
  id: string;
  role: "user" | "assistant";
  text: string;
  state: "accepted" | "optimistic" | "cancelled";
  sequence: number;
}>;

export type PendingTurn = Readonly<{
  id: string;
  messageId: string;
  text: string;
  state: "pending" | "optimistic" | "blocked" | "cancelled";
}>;

export type Conversation = Readonly<{
  id: string;
  title: string;
  agent: string;
  draft: string;
  messages: readonly Message[];
  queue: readonly PendingTurn[];
  run: Readonly<{ id: string; status: RunStatus }>;
  cursor: number;
  attention: string | null;
  activityHint: string;
}>;

export type PrototypeState = Readonly<{
  conversations: Readonly<Record<string, Conversation>>;
  conversationOrder: readonly string[];
  openTabs: readonly string[];
  selectedId: string;
  visibleMessageLimit: number;
  renderMode: "paged" | "all";
  failNextSend: boolean;
  stream: Readonly<{
    activeConversationId: string | null;
    activeRunId: string | null;
    connects: number;
    cleanups: number;
    ignoredEvents: number;
  }>;
  notice: string;
  lastChange: string;
}>;

export type PrototypeAction =
  | Readonly<{ type: "select"; conversationId: string }>
  | Readonly<{ type: "close"; conversationId: string }>
  | Readonly<{ type: "set_draft"; conversationId: string; value: string }>
  | Readonly<{ type: "send_begin"; conversationId: string; clientId: string }>
  | Readonly<{ type: "send_accept"; conversationId: string; clientId: string }>
  | Readonly<{ type: "send_reject"; conversationId: string; clientId: string }>
  | Readonly<{ type: "queue_edit"; conversationId: string; turnId: string; value: string }>
  | Readonly<{ type: "queue_cancel"; conversationId: string; turnId: string }>
  | Readonly<{ type: "stream_connected"; conversationId: string; runId: string }>
  | Readonly<{ type: "stream_cleaned"; conversationId: string; runId: string }>
  | Readonly<{
      type: "stream_event";
      conversationId: string;
      runId: string;
      sequence: number;
      text: string;
    }>
  | Readonly<{ type: "global_hint"; conversationId: string; text: string }>
  | Readonly<{ type: "set_attention"; conversationId: string; text: string | null }>
  | Readonly<{ type: "load_stress"; conversationId: string; count: number }>
  | Readonly<{ type: "set_render_mode"; mode: "paged" | "all" }>
  | Readonly<{ type: "load_older"; count: number }>
  | Readonly<{ type: "set_fail_next"; value: boolean }>
  | Readonly<{ type: "reset"; state: PrototypeState }>;

const QUEUE_LIMIT = 8;

function updateConversation(
  state: PrototypeState,
  conversationId: string,
  update: (conversation: Conversation) => Conversation,
): PrototypeState {
  const current = state.conversations[conversationId];
  if (!current) return { ...state, notice: "Conversation not found.", lastChange: "Rejected unknown Conversation" };
  return {
    ...state,
    conversations: { ...state.conversations, [conversationId]: update(current) },
  };
}

function selectConversation(state: PrototypeState, conversationId: string): PrototypeState {
  if (!state.conversations[conversationId]) return state;
  const openTabs = state.openTabs.includes(conversationId)
    ? state.openTabs
    : [...state.openTabs, conversationId];
  return {
    ...state,
    openTabs,
    selectedId: conversationId,
    visibleMessageLimit: 200,
    notice: "Conversation selected from cached state.",
    lastChange: `Focused ${state.conversations[conversationId].title}`,
  };
}

function closeConversation(state: PrototypeState, conversationId: string): PrototypeState {
  if (!state.openTabs.includes(conversationId)) return state;
  const closingIndex = state.openTabs.indexOf(conversationId);
  const openTabs = state.openTabs.filter((id) => id !== conversationId);
  const fallback = openTabs[Math.min(closingIndex, openTabs.length - 1)] ?? state.conversationOrder[0];
  return {
    ...state,
    openTabs,
    selectedId: state.selectedId === conversationId ? fallback : state.selectedId,
    notice: "Tab closed; Conversation state and active work were retained.",
    lastChange: `Closed view for ${state.conversations[conversationId].title}`,
  };
}

export function prototypeReducer(state: PrototypeState, action: PrototypeAction): PrototypeState {
  switch (action.type) {
    case "reset":
      return action.state;
    case "select":
      return selectConversation(state, action.conversationId);
    case "close":
      return closeConversation(state, action.conversationId);
    case "set_draft":
      return {
        ...updateConversation(state, action.conversationId, (conversation) => ({
          ...conversation,
          draft: action.value,
        })),
        lastChange: `Updated the isolated draft for ${state.conversations[action.conversationId]?.title ?? "Conversation"}`,
      };
    case "set_fail_next":
      return { ...state, failNextSend: action.value, lastChange: action.value ? "Next Send will fail" : "Send failure disabled" };
    case "send_begin": {
      const conversation = state.conversations[action.conversationId];
      const text = conversation?.draft.trim() ?? "";
      if (!conversation || !text) return { ...state, notice: "Enter a message first.", lastChange: "Send rejected" };
      const activeQueue = conversation.queue.filter((turn) => ["pending", "optimistic", "blocked"].includes(turn.state));
      if (activeQueue.length >= QUEUE_LIMIT) {
        return { ...state, notice: "Queue is full at eight turns. Draft preserved.", lastChange: "Ninth queued turn rejected" };
      }
      const messageId = `msg_${action.clientId}`;
      const turnId = `turn_${action.clientId}`;
      return {
        ...updateConversation(state, action.conversationId, (current) => ({
          ...current,
          draft: "",
          messages: [
            ...current.messages,
            { id: messageId, role: "user", text, state: "optimistic", sequence: current.messages.length + 1 },
          ],
          queue: [...current.queue, { id: turnId, messageId, text, state: "optimistic" }],
        })),
        notice: "Message painted optimistically; waiting for server acceptance.",
        lastChange: `Optimistic Send ${action.clientId}`,
      };
    }
    case "send_accept":
      return {
        ...updateConversation(state, action.conversationId, (conversation) => ({
          ...conversation,
          messages: conversation.messages.map((message) => (
            message.id === `msg_${action.clientId}` ? { ...message, state: "accepted" } : message
          )),
          queue: conversation.queue.map((turn) => (
            turn.id === `turn_${action.clientId}` ? { ...turn, state: "pending" } : turn
          )),
        })),
        failNextSend: false,
        notice: "Server accepted the queued turn.",
        lastChange: `Accepted Send ${action.clientId}`,
      };
    case "send_reject": {
      const conversation = state.conversations[action.conversationId];
      const message = conversation?.messages.find((item) => item.id === `msg_${action.clientId}`);
      return {
        ...updateConversation(state, action.conversationId, (current) => ({
          ...current,
          draft: current.draft || message?.text || "",
          messages: current.messages.filter((item) => item.id !== `msg_${action.clientId}`),
          queue: current.queue.filter((turn) => turn.id !== `turn_${action.clientId}`),
        })),
        failNextSend: false,
        notice: "Send was rejected. The draft was restored without affecting another Conversation.",
        lastChange: `Rolled back Send ${action.clientId}`,
      };
    }
    case "queue_edit":
      return {
        ...updateConversation(state, action.conversationId, (conversation) => {
          const target = conversation.queue.find((turn) => turn.id === action.turnId);
          if (!target || !["pending", "blocked"].includes(target.state)) return conversation;
          return {
            ...conversation,
            queue: conversation.queue.map((turn) => (
              turn.id === action.turnId ? { ...turn, text: action.value } : turn
            )),
            messages: conversation.messages.map((message) => (
              message.id === target.messageId ? { ...message, text: action.value } : message
            )),
          };
        }),
        notice: "Queued turn edited under its current revision.",
        lastChange: `Edited ${action.turnId}`,
      };
    case "queue_cancel":
      return {
        ...updateConversation(state, action.conversationId, (conversation) => {
          const target = conversation.queue.find((turn) => turn.id === action.turnId);
          if (!target || !["pending", "blocked"].includes(target.state)) return conversation;
          return {
            ...conversation,
            queue: conversation.queue.map((turn) => (
              turn.id === action.turnId ? { ...turn, state: "cancelled" } : turn
            )),
            messages: conversation.messages.map((message) => (
              message.id === target.messageId ? { ...message, state: "cancelled" } : message
            )),
          };
        }),
        notice: "Queued turn cancelled; later turns keep FIFO order.",
        lastChange: `Cancelled ${action.turnId}`,
      };
    case "stream_connected":
      return {
        ...state,
        stream: {
          ...state.stream,
          activeConversationId: action.conversationId,
          activeRunId: action.runId,
          connects: state.stream.connects + 1,
        },
        lastChange: `Connected selected detail stream to ${action.runId}`,
      };
    case "stream_cleaned": {
      const ownsActiveStream = state.stream.activeConversationId === action.conversationId
        && state.stream.activeRunId === action.runId;
      return {
        ...state,
        stream: {
          ...state.stream,
          activeConversationId: ownsActiveStream ? null : state.stream.activeConversationId,
          activeRunId: ownsActiveStream ? null : state.stream.activeRunId,
          cleanups: state.stream.cleanups + 1,
        },
        lastChange: `Cleaned selected detail stream for ${action.runId}`,
      };
    }
    case "stream_event": {
      const conversation = state.conversations[action.conversationId];
      if (
        !conversation
        || conversation.run.id !== action.runId
        || action.sequence <= conversation.cursor
        || state.stream.activeConversationId !== action.conversationId
        || state.stream.activeRunId !== action.runId
      ) {
        return {
          ...state,
          stream: { ...state.stream, ignoredEvents: state.stream.ignoredEvents + 1 },
          notice: "A stale or crossed detail event was ignored.",
          lastChange: `Ignored event for ${action.runId}`,
        };
      }
      return {
        ...updateConversation(state, action.conversationId, (current) => ({
          ...current,
          cursor: action.sequence,
          messages: [
            ...current.messages,
            {
              id: `event_${action.runId}_${action.sequence}`,
              role: "assistant",
              text: action.text,
              state: "accepted",
              sequence: current.messages.length + 1,
            },
          ],
        })),
        notice: "Selected Run event painted in its owning Conversation.",
        lastChange: `Applied event ${action.sequence} to ${action.runId}`,
      };
    }
    case "global_hint":
      return {
        ...updateConversation(state, action.conversationId, (conversation) => ({
          ...conversation,
          activityHint: action.text,
        })),
        notice: "Bounded global activity updated the rail only.",
        lastChange: `Updated global hint for ${action.conversationId}`,
      };
    case "set_attention":
      return {
        ...updateConversation(state, action.conversationId, (conversation) => ({
          ...conversation,
          attention: action.text,
          run: { ...conversation.run, status: action.text ? "waiting_for_clarification" : "running" },
        })),
        notice: action.text ? "Operator attention is visible in the rail." : "Attention resolved.",
        lastChange: `${action.text ? "Raised" : "Resolved"} attention for ${action.conversationId}`,
      };
    case "load_stress": {
      const count = Math.max(1, Math.min(action.count, 5_000));
      const messages = Array.from({ length: count }, (_, index): Message => ({
        id: `stress_${action.conversationId}_${index + 1}`,
        role: index % 2 === 0 ? "user" : "assistant",
        text: `${index % 2 === 0 ? "Operator" : "Mentat"} message ${index + 1}. Bounded transcript content for the rendering fixture.`,
        state: "accepted",
        sequence: index + 1,
      }));
      return {
        ...updateConversation(state, action.conversationId, (conversation) => ({ ...conversation, messages })),
        visibleMessageLimit: 200,
        notice: `Loaded ${count.toLocaleString()} ordered messages into memory.`,
        lastChange: `Loaded ${count} message fixture`,
      };
    }
    case "set_render_mode":
      return {
        ...state,
        renderMode: action.mode,
        visibleMessageLimit: action.mode === "paged" ? 200 : 5_000,
        notice: action.mode === "paged"
          ? "Rendering the newest bounded page with accessible Load older control."
          : "Rendering every loaded Message for comparison.",
        lastChange: `Changed transcript rendering to ${action.mode}`,
      };
    case "load_older":
      return {
        ...state,
        visibleMessageLimit: Math.min(5_000, state.visibleMessageLimit + action.count),
        notice: "Loaded an older bounded page while preserving DOM order.",
        lastChange: `Expanded transcript by ${action.count}`,
      };
    default:
      return state;
  }
}

export function createInitialState(): PrototypeState {
  const conversation = (
    id: string,
    title: string,
    agent: string,
    runId: string,
    activityHint: string,
    attention: string | null = null,
  ): Conversation => ({
    id,
    title,
    agent,
    draft: "",
    messages: [
      { id: `${id}_m1`, role: "user", text: `Help me with ${title.toLowerCase()}.`, state: "accepted", sequence: 1 },
      { id: `${id}_m2`, role: "assistant", text: "I have the task and I’m beginning with a focused pass.", state: "accepted", sequence: 2 },
    ],
    queue: [],
    run: { id: runId, status: attention ? "waiting_for_clarification" : "running" },
    cursor: 2,
    attention,
    activityHint,
  });

  const conversations = {
    conv_research: conversation("conv_research", "Research launch options", "Researcher", "run_research", "Reviewing primary sources"),
    conv_build: conversation("conv_build", "Implement gateway tests", "Builder", "run_build", "Running focused checks"),
    conv_plan: conversation("conv_plan", "Plan console migration", "Planner", "run_plan", "Waiting for your answer", "Clarify the first milestone"),
  } satisfies Record<string, Conversation>;

  return {
    conversations,
    conversationOrder: Object.keys(conversations),
    openTabs: ["conv_research", "conv_build"],
    selectedId: "conv_research",
    visibleMessageLimit: 200,
    renderMode: "paged",
    failNextSend: false,
    stream: {
      activeConversationId: null,
      activeRunId: null,
      connects: 0,
      cleanups: 0,
      ignoredEvents: 0,
    },
    notice: "Prototype ready. All authority is in-memory fixture state.",
    lastChange: "Initialized prototype",
  };
}

export const PROTOTYPE_QUEUE_LIMIT = QUEUE_LIMIT;
