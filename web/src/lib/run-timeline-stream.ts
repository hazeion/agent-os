import { BridgeRunEventsError, type PublicBridgeRunEvents, type PublicRunEvent } from "./bridge-run-events.ts";

type TimelineReader = (runId: string, after: number) => Promise<PublicBridgeRunEvents>;
type StreamOptions = { runId: string; after: number; read: TimelineReader; signal: AbortSignal; polls?: number; pollMilliseconds?: number; authorize?: () => Promise<boolean>; release?: () => Promise<void> };

const encoder = new TextEncoder();

function frame(event: string, id: number, data: object) {
  return encoder.encode(`event: ${event}\nid: ${id}\ndata: ${JSON.stringify(data)}\n\n`);
}

function pause(milliseconds: number, signal: AbortSignal) {
  if (signal.aborted) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const done = () => { clearTimeout(timeout); signal.removeEventListener("abort", done); resolve(); };
    const timeout = setTimeout(done, milliseconds);
    signal.addEventListener("abort", done, { once: true });
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
  let releaseTask: Promise<void> | undefined;
  const release = () => releaseTask ??= (async () => { try { await options.release?.(); } catch { /* Startup/expiry also collects leases. */ } })();
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      let cursor = options.after;
      const authorized = async () => {
        if (!options.authorize || await options.authorize()) return true;
        if (!cancelled && !options.signal.aborted) controller.enqueue(encoder.encode('event: owner-auth-required\ndata: {}\n\n'));
        return false;
      };
      try {
      controller.enqueue(encoder.encode("retry: 1500\n\n"));
      for (let poll = 0; poll < polls && !cancelled && !options.signal.aborted; poll += 1) {
        try {
          if (!await authorized()) break;
          const payload = await options.read(options.runId, cursor);
          if (cancelled || options.signal.aborted) break;
          if (!await authorized()) break;
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
          if (!cancelled && !options.signal.aborted) {
            let allowed = true;
            try { allowed = await authorized(); } catch { /* Emit only a fixed availability error. */ }
            if (allowed) controller.enqueue(frame("error", cursor, { code: publicError(error) }));
          }
          break;
        }
        if (poll + 1 < polls && !cancelled && !options.signal.aborted) await pause(pollMilliseconds, options.signal);
      }
      } finally { await release(); if (!cancelled) controller.close(); }
    },
    cancel() { cancelled = true; return release(); },
  });
}

export type { PublicRunEvent };
