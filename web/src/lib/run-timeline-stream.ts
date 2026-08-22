import { BridgeRunEventsError, type PublicBridgeRunEvents, type PublicRunEvent } from "./bridge-run-events.ts";

type TimelineReader = (runId: string, after: number) => Promise<PublicBridgeRunEvents>;
type StreamOptions = { runId: string; after: number; read: TimelineReader; signal: AbortSignal; polls?: number; pollMilliseconds?: number };

const encoder = new TextEncoder();

function frame(event: string, id: number, data: object) {
  return encoder.encode(`event: ${event}\nid: ${id}\ndata: ${JSON.stringify(data)}\n\n`);
}

function pause(milliseconds: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const timeout = setTimeout(resolve, milliseconds);
    signal.addEventListener("abort", () => { clearTimeout(timeout); resolve(); }, { once: true });
  });
}

function publicError(error: unknown) {
  if (error instanceof BridgeRunEventsError && ["bridge_unavailable", "bridge_unsupported", "run_not_found"].includes(error.code)) return error.code;
  return "bridge_error";
}

export function createRunTimelineStream(options: StreamOptions): ReadableStream<Uint8Array> {
  const polls = options.polls ?? 13;
  const pollMilliseconds = options.pollMilliseconds ?? 2_000;
  let cancelled = false;
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      let cursor = options.after;
      controller.enqueue(encoder.encode("retry: 1500\n\n"));
      for (let poll = 0; poll < polls && !cancelled && !options.signal.aborted; poll += 1) {
        try {
          const payload = await options.read(options.runId, cursor);
          if (cancelled || options.signal.aborted) break;
          if (poll === 0) {
            controller.enqueue(frame("snapshot", payload.next_cursor, { events: payload.events, cursor: payload.next_cursor, reset: payload.cursor_reset_required }));
          } else if (payload.cursor_reset_required) {
            controller.enqueue(frame("reset", payload.next_cursor, { events: payload.events, cursor: payload.next_cursor, reset: true }));
          } else if (payload.events.length) {
            for (const event of payload.events) controller.enqueue(frame("timeline", event.sequence, { event }));
          } else {
            controller.enqueue(encoder.encode(": keepalive\n\n"));
          }
          cursor = payload.next_cursor;
        } catch (error) {
          if (!cancelled && !options.signal.aborted) controller.enqueue(frame("error", cursor, { code: publicError(error) }));
          break;
        }
        if (poll + 1 < polls && !cancelled && !options.signal.aborted) await pause(pollMilliseconds, options.signal);
      }
      if (!cancelled) controller.close();
    },
    cancel() { cancelled = true; },
  });
}

export type { PublicRunEvent };
