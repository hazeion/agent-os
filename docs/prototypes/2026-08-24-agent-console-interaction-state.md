# Agent Console interaction-state prototype verdict

GitHub issue: [#132](https://github.com/hazeion/agent-os/issues/132)

Branch: `codex/prototype-agent-console-state`

Status: decision complete; this branch is a quarantined throwaway artifact and
must not be merged as production implementation.

## Question

What is the lightest React/Next.js client-state and transcript-rendering design
that satisfies the approved Agent Console interaction and performance contracts?

## Scope

The prototype uses in-memory fixture state to exercise:

- open, close, reopen, and cached switching of Conversation tabs;
- isolated per-Conversation drafts;
- two concurrently active Conversations;
- exact selected-Conversation/Run stream handoff and cleanup;
- bounded global activity hints in the right rail;
- optimistic Send acceptance and rollback;
- an eight-turn editable/cancellable queue with a rejected ninth turn;
- operator-attention state;
- a 2,000-message transcript fixture;
- reduced motion, focus retention, scroll anchoring, and ordered transcript DOM.

It does not call Mentat's backend, persist authority, or implement production
visual details. In particular, the approved centered collapse handles for the
left and right rails remain mandatory Slice 1 behavior; omitting them here keeps
this experiment focused on interaction state and rendering.

## How to reproduce

From `web/` on this branch:

```bash
npm ci --ignore-scripts
npm run prototype:agent-console
```

Then open
`http://127.0.0.1:8893/prototype/agent-console-state`.

With a local Chromium executable and the prototype server running:

```bash
CHROME_PATH='/Applications/Chromium.app/Contents/MacOS/Chromium' \
  npm run prototype:agent-console:measure
```

The measurement command runs three standard-motion passes and one reduced-motion
pass. It fails when identity isolation, queue capacity, focus, anchoring, DOM
order, or the timing budgets fail.

## Evidence

Reference run:

- Apple macOS local reference machine;
- Headless Chromium 152;
- viewport 1512 by 982 at device-pixel ratio 1;
- 2,000-message fixture;
- three standard-motion passes and one reduced-motion pass.

Aggregate medians from the passing run:

| Measurement | Result |
| --- | ---: |
| Render all 2,000 Message rows | 563.8 ms |
| Return to bounded 200-row page | 171.1 ms |
| Composer input paint | 16.7 ms |
| Cached Conversation switch | 28.7 ms |
| Selected stream-event paint | 17.5 ms |
| React Profiler commit | 3.2 ms |

Every pass also demonstrated:

- the 200-row DOM bound and ordered screen-reader DOM;
- exact stale-event rejection with no crossed Conversation output;
- per-Conversation draft isolation;
- the eight-turn queue cap with the ninth draft preserved;
- focus retention after right-rail navigation;
- 0.22 px scroll-anchor movement after loading older Messages;
- reduced-motion preference recognition.

The first implementation rendered the same 200 transcript rows on every draft
change because `Transcript` received the whole mutable Conversation object. Its
composer-input median was approximately 52.5 ms. Passing only the immutable
Message array and stable scalar props through a memoized transcript boundary
reduced the passing median to 16.7 ms. A later development-mode rerun measured
22.6 ms, which is why implementation acceptance must be collected against the
production build and fixed reference environment rather than treating one dev
sample as a release gate.

## Decision

Use React built-ins for Slice 1. Do not add a client-state library or transcript
virtualization dependency.

The production client boundary should contain:

1. a normalized Conversation projection cache keyed by canonical Conversation
   ID;
2. small presentation state for open tabs, selected tab, per-Conversation draft,
   optimistic turn overlays, and rail collapse state;
3. one selected-detail stream effect keyed by exact Conversation ID and Run ID,
   with cleanup plus a reducer identity guard;
4. a separate bounded global-activity hint channel that causes authoritative
   readback and never writes detailed transcript events;
5. a memoized transcript receiving only the selected immutable Message page and
   stable callbacks/scalars.

Start with server pages of 100 Messages, retain a bounded 200-row ordered DOM
window, and expose an explicit keyboard-accessible **Load older** control. This
keeps native copy, find, zoom, focus, and screen-reader order intact. Reconsider
virtualization only if a later production fixture requires materially more than
200 simultaneously mounted rows and the accessibility gates can still pass.

React Virtuoso was the strongest fallback candidate. At the decision date,
`react-virtuoso` 4.18.12 is MIT licensed, declares React and React DOM as peers,
and publishes a 242,666-byte, six-file unpacked package. It is compatible, but
the prototype did not justify its additional code or the interaction and
accessibility complexity of virtualization. The accepted dependency cost is
therefore zero. The production prototype route's own generated client chunk was
27,641 bytes raw and 7,976 bytes gzip, recorded only as context; it is not a
production bundle budget.

Sources:

- [React Virtuoso repository and license](https://github.com/petyosi/react-virtuoso)
- [React Virtuoso npm package](https://www.npmjs.com/package/react-virtuoso)

## Production prerequisite discovered

The webpack production build compiles the prototype route successfully. The
current static Emerald-shell Content Security Policy uses `script-src 'self'`
and intentionally does not permit Next.js's inline hydration bootstrap, so the
Client Component does not become interactive in that build. Slice 1 must adopt
a reviewed CSP-compatible hydration strategy, such as request-scoped nonces,
without restoring a broad unsafe script policy. Production performance evidence
must be rerun after that boundary exists.

## Disposition

- Keep this route, measurement harness, and evidence only on the throwaway
  branch.
- Carry the state, rendering, dependency, and CSP decisions into the canonical
  specification and Slice 1 acceptance criteria.
- Do not merge the prototype UI as the implementation of Slice 1.
